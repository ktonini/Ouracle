"""Sleep staging computed locally from the ring's raw signals.

The ring streams the inputs (movement, heart rate, beat-to-beat variability,
temperature) but not the staged hypnogram — per open_oura, triggering its
on-device analysis yields the bedtime window and nothing more, because the
official app finishes staging elsewhere.

So this derives stages here, using the classical actigraphy-plus-cardiac
approach:

* movement dominates wake detection (the basis of every actigraphy method)
* deep sleep pairs minimal movement with heart rate at its nightly floor and
  low beat-to-beat variability
* REM shows near-absent movement but elevated, more variable heart rate
* anything else is light sleep, the default and most common stage

This is an approximation, not Oura's model — theirs uses proprietary
on-device networks. Expect the broad architecture (cycles, deep early, REM
late) to agree and the minute-by-minute detail to differ, so stages carry a
`confidence` and the method is labelled in the output.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean, median, pstdev
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("RingStaging")

# (mtime, forest) — reloaded when the file changes, so retraining takes effect
# without a restart.
_MODEL_CACHE: Tuple[Optional[float], Any] = (None, None)

# Epochs shorter than this get too noisy for movement-based staging.
EPOCH_MINUTES = 5

STAGE_DEEP = "deep"
STAGE_LIGHT = "light"
STAGE_REM = "rem"
STAGE_AWAKE = "awake"


@dataclass
class Epoch:
    start: datetime
    movement: Optional[float]
    heart_rate: Optional[float]
    hr_variability: Optional[float]
    # Peak movement in the epoch: a brief burst signals waking even when the
    # average stays low.
    movement_peak: Optional[float] = None
    temperature: Optional[float] = None
    # From the epoch's raw beat intervals — what actually separates REM from
    # deep sleep, since a single averaged HRV value cannot.
    sdnn_rmssd: Optional[float] = None
    pnn50: Optional[float] = None
    breath_irregularity: Optional[float] = None
    breath_rate: Optional[float] = None
    # Filled in by stage_epochs: position through the night, 0…1. Sleep
    # architecture is strongly time-dependent — deep dominates the first
    # third, REM the last — so this is the single most useful extra feature.
    progress: float = 0.0


def _percentile(values: List[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(int(len(ordered) * fraction), len(ordered) - 1)
    return ordered[index]


def load_model():
    """The fitted forest, if one has been trained. Cached on the file's mtime.

    Absent on a fresh install and on any server that has never had labels to
    learn from, so staging must work without it.
    """
    global _MODEL_CACHE
    from ..paths import get_user_data_dir

    path = get_user_data_dir() / "sleep_model.json"
    try:
        stamp = path.stat().st_mtime
    except OSError:
        _MODEL_CACHE = (None, None)
        return None
    if _MODEL_CACHE[0] == stamp:
        return _MODEL_CACHE[1]

    try:
        from .model import Forest

        forest = Forest.from_json(json.loads(path.read_text()))
    except Exception:  # a corrupt model must not take staging down
        logger.exception("could not load %s; falling back to thresholds", path)
        forest = None
    _MODEL_CACHE = (stamp, forest)
    return forest


def _stage_with_model(epochs: List[Epoch], forest) -> List[Dict[str, Any]]:
    """Stages from the learned model, with its own confidence."""
    from .model import featurise_night

    rows = [
        {
            "heart_rate": e.heart_rate,
            "movement": e.movement,
            "movement_peak": e.movement_peak,
            "temperature": e.temperature,
            "hrv": e.hr_variability,
            "sdnn_rmssd": e.sdnn_rmssd,
            "pnn50": e.pnn50,
            "breath_irregularity": e.breath_irregularity,
            "breath_rate": e.breath_rate,
        }
        for e in epochs
    ]
    # Decoded as a sequence rather than epoch by epoch: sleep runs in stretches,
    # and three quarters of epochs continue the previous stage.
    staged: List[Dict[str, Any]] = []
    for epoch, (stage, confidence) in zip(epochs, forest.decode(featurise_night(rows))):
        staged.append(
            {
                "t": epoch.start.isoformat(),
                "stage": stage,
                # The forest's own vote share, so a marginal call reads as one.
                "confidence": confidence,
                "heart_rate": (
                    round(epoch.heart_rate, 1) if epoch.heart_rate is not None else None
                ),
                "movement": round(epoch.movement or 0.0, 3),
            }
        )
    return staged


def stage_epochs(epochs: List[Epoch], use_model: bool = True) -> List[Dict[str, Any]]:
    """Classify epochs into sleep stages.

    Uses the learned model when one has been fitted; the threshold rules below
    are the fallback for a server with no labels to learn from. Measured
    leave-one-night-out over six nights, the model scores 0.57 against 0.43 for
    the thresholds — which are themselves below simply answering "light".

    Those thresholds are relative to the night itself rather than absolute, so
    they adapt to the person and to sensor drift instead of assuming
    population norms.
    """
    if use_model and epochs:
        forest = load_model()
        if forest is not None:
            staged = _stage_with_model(epochs, forest)
            # The flicker filter exists to impose run-length structure the
            # per-epoch rules lack. A decoded sequence already has it, and
            # smoothing on top would overrule the transition model.
            return staged if forest.transitions else _smooth(staged)

    movements = [e.movement for e in epochs if e.movement is not None]
    rates = [e.heart_rate for e in epochs if e.heart_rate is not None]
    variabilities = [e.hr_variability for e in epochs if e.hr_variability is not None]
    if not rates:
        return []

    # Movement: a quiet night has a very low median, so scale off it.
    move_quiet = _percentile(movements, 0.5) if movements else 0.0

    # Wake is judged on peak movement, so its threshold must come from the
    # peak distribution — comparing peaks against a mean-derived threshold
    # fires on ordinary light sleep.
    peaks = [
        e.movement_peak if e.movement_peak is not None else e.movement
        for e in epochs
        if (e.movement_peak if e.movement_peak is not None else e.movement) is not None
    ]
    peak_typical = _percentile(peaks, 0.5) if peaks else 0.0
    wake_threshold = max(
        _percentile(peaks, 0.9) if peaks else 0.0, peak_typical * 3, 0.2
    )

    hr_floor = _percentile(rates, 0.1)
    hr_typical = median(rates)
    var_typical = median(variabilities) if variabilities else 0.0

    # Stages are separated by *variation* in heart rate. A flat night carries
    # no such signal, and calling it all "deep" because every epoch sits at
    # the floor would be an artefact — only wake (from movement) is safe then.
    # Spread across the night, not median-to-floor: when most epochs share a
    # value the median sits on top of the floor and hides a real excursion.
    hr_range = _percentile(rates, 0.9) - hr_floor
    can_separate = hr_range >= 3.0

    # Baselines for the beat-interval features, again relative to the night.
    ratios = [e.sdnn_rmssd for e in epochs if e.sdnn_rmssd is not None]
    irregulars = [
        e.breath_irregularity for e in epochs if e.breath_irregularity
    ]
    ratio_typical = median(ratios) if ratios else None
    irregular_typical = median(irregulars) if irregulars else None

    # Position through the night, used to weight deep vs REM.
    span = max(len(epochs) - 1, 1)
    for index, epoch in enumerate(epochs):
        epoch.progress = index / span

    staged: List[Dict[str, Any]] = []
    for epoch in epochs:
        movement = epoch.movement or 0.0
        peak = epoch.movement_peak if epoch.movement_peak is not None else movement
        rate = epoch.heart_rate
        variability = epoch.hr_variability

        # Deep sleep concentrates early, REM late: shift each threshold with
        # time rather than applying one rule across the whole night.
        deep_bias = 1.0 - epoch.progress          # 1 at onset → 0 at waking
        rem_bias = epoch.progress
        deep_cut = hr_floor + hr_range * (0.25 + 0.35 * deep_bias)

        if rate is None:
            stage, confidence = STAGE_LIGHT, 0.2
        elif peak >= wake_threshold:
            stage, confidence = STAGE_AWAKE, 0.7
        elif not can_separate:
            stage, confidence = STAGE_LIGHT, 0.3
        elif _looks_like_rem(epoch, ratio_typical, irregular_typical, move_quiet):
            # Ahead of the deep test on purpose: deep sleep is defined by
            # metronomic respiration, so an epoch breathing erratically is not
            # deep however low its heart rate sits.
            stage, confidence = STAGE_REM, 0.4 + 0.3 * rem_bias
        elif (
            rate <= deep_cut
            and movement <= move_quiet * (1.0 + 0.5 * deep_bias)
            and (variability is None or variability <= var_typical * 1.1)
        ):
            stage, confidence = STAGE_DEEP, 0.4 + 0.3 * deep_bias
        elif (
            # Fallback for epochs with no beat intervals to read: heart rate
            # alone, which is weaker — it mistakes ordinary light sleep for REM
            # — so it only runs where the better signal is missing.
            epoch.breath_irregularity is None
            and rate >= hr_typical - hr_range * 0.15 * rem_bias
            and variability is not None
            and variability > var_typical * (1.15 - 0.35 * rem_bias)
            and movement <= move_quiet * 1.5
        ):
            stage, confidence = STAGE_REM, 0.35 + 0.3 * rem_bias
        else:
            stage, confidence = STAGE_LIGHT, 0.5

        staged.append(
            {
                "t": epoch.start.isoformat(),
                "stage": stage,
                "confidence": round(confidence, 2),
                "heart_rate": round(rate, 1) if rate is not None else None,
                "movement": round(movement, 3),
            }
        )

    return _smooth(staged)


def _looks_like_rem(
    epoch: Epoch,
    ratio_typical: Optional[float],
    irregular_typical: Optional[float],
    move_quiet: float,
) -> bool:
    """REM by its beat-interval signature rather than average heart rate.

    Irregular breathing is required, not merely one vote among several: it is
    the one feature that reliably separates REM here, because respiration is
    erratic in REM and metronomic in every other sleep stage. The variability
    ratio and pNN50 then corroborate — on their own they drift high across
    whole stretches of a night and produce false REM.

    Movement must stay low regardless: REM comes with muscle atonia, so a
    moving epoch is not REM.
    """
    if irregular_typical is None or not epoch.breath_irregularity:
        return False
    if (epoch.movement or 0.0) > move_quiet * 1.5:
        return False
    if epoch.breath_irregularity <= irregular_typical * 1.25:
        return False

    ratio_high = (
        ratio_typical is not None
        and epoch.sdnn_rmssd is not None
        and epoch.sdnn_rmssd > ratio_typical * 1.1
    )
    tone_low = epoch.pnn50 is not None and epoch.pnn50 < 0.15
    return ratio_high or tone_low


def _smooth(staged: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Remove single-epoch flickers between two identical neighbours.

    Real stages persist for several minutes; a lone deviating epoch is far
    more likely to be noise than a genuine transition.
    """
    if len(staged) < 3:
        return staged
    for index in range(1, len(staged) - 1):
        previous, current, following = staged[index - 1], staged[index], staged[index + 1]
        if previous["stage"] == following["stage"] != current["stage"]:
            # Never smooth away a wake epoch: brief awakenings are real.
            if current["stage"] != STAGE_AWAKE:
                current["stage"] = previous["stage"]
                current["confidence"] = min(current["confidence"], 0.4)
    return staged


def summarise(staged: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Per-stage minutes and efficiency, as the app shows for cloud sessions."""
    minutes = {STAGE_DEEP: 0, STAGE_LIGHT: 0, STAGE_REM: 0, STAGE_AWAKE: 0}
    for epoch in staged:
        minutes[epoch["stage"]] = minutes.get(epoch["stage"], 0) + EPOCH_MINUTES
    asleep = minutes[STAGE_DEEP] + minutes[STAGE_LIGHT] + minutes[STAGE_REM]
    total = asleep + minutes[STAGE_AWAKE]
    return {
        "deep_minutes": minutes[STAGE_DEEP],
        "light_minutes": minutes[STAGE_LIGHT],
        "rem_minutes": minutes[STAGE_REM],
        "awake_minutes": minutes[STAGE_AWAKE],
        "asleep_minutes": asleep,
        "efficiency_percent": round(asleep / total * 100) if total else None,
        "method": "ouracle-model-v1" if load_model() is not None else "ouracle-local-v1",
    }


def build_epochs(
    heart_rate: List[Dict[str, Any]],
    movement: List[Dict[str, Any]],
    variability: Optional[Dict[str, float]] = None,
    movement_peak: Optional[List[Dict[str, Any]]] = None,
    temperature: Optional[List[Dict[str, Any]]] = None,
    ibi_features: Optional[Dict[str, Dict[str, float]]] = None,
) -> List[Epoch]:
    """Join the per-bucket series into aligned epochs, keyed on timestamp."""
    by_time: Dict[str, Epoch] = {}

    def epoch_at(timestamp: str) -> Epoch:
        if timestamp not in by_time:
            by_time[timestamp] = Epoch(
                start=datetime.fromisoformat(timestamp),
                movement=None,
                heart_rate=None,
                hr_variability=None,
            )
        return by_time[timestamp]

    for point in heart_rate:
        epoch = epoch_at(point["t"])
        epoch.heart_rate = point["value"]
        epoch.hr_variability = (variability or {}).get(point["t"])
    for point in movement:
        epoch_at(point["t"]).movement = point["value"]
    for point in movement_peak or []:
        epoch_at(point["t"]).movement_peak = point["value"]
    for point in temperature or []:
        epoch_at(point["t"]).temperature = point["value"]
    for timestamp, features in (ibi_features or {}).items():
        epoch = epoch_at(timestamp)
        epoch.sdnn_rmssd = features.get("sdnn_rmssd")
        epoch.pnn50 = features.get("pnn50")
        epoch.breath_irregularity = features.get("breath_irregularity")
        epoch.breath_rate = features.get("breath_rate")

    return [by_time[key] for key in sorted(by_time)]
