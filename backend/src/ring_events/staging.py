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

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean, median, pstdev
from typing import Any, Dict, List, Optional

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


def _percentile(values: List[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(int(len(ordered) * fraction), len(ordered) - 1)
    return ordered[index]


def stage_epochs(epochs: List[Epoch]) -> List[Dict[str, Any]]:
    """Classify epochs into sleep stages.

    Thresholds are relative to the night itself rather than absolute, so this
    adapts to the person and to sensor drift instead of assuming population
    norms.
    """
    movements = [e.movement for e in epochs if e.movement is not None]
    rates = [e.heart_rate for e in epochs if e.heart_rate is not None]
    variabilities = [e.hr_variability for e in epochs if e.hr_variability is not None]
    if not rates:
        return []

    # Movement: a quiet night has a very low median, so scale off it.
    move_quiet = _percentile(movements, 0.5) if movements else 0.0
    move_active = _percentile(movements, 0.9) if movements else 0.0
    wake_threshold = max(move_active, move_quiet * 4, 0.15)

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

    staged: List[Dict[str, Any]] = []
    for epoch in epochs:
        movement = epoch.movement or 0.0
        rate = epoch.heart_rate
        variability = epoch.hr_variability

        if rate is None:
            stage, confidence = STAGE_LIGHT, 0.2
        elif movement >= wake_threshold:
            stage, confidence = STAGE_AWAKE, 0.7
        elif not can_separate:
            stage, confidence = STAGE_LIGHT, 0.3
        elif (
            rate <= hr_floor + hr_range * 0.35
            and movement <= move_quiet
            and (variability is None or variability <= var_typical)
        ):
            stage, confidence = STAGE_DEEP, 0.6
        elif (
            rate >= hr_typical
            and variability is not None
            and variability > var_typical
            and movement <= move_quiet * 1.5
        ):
            stage, confidence = STAGE_REM, 0.5
        else:
            stage, confidence = STAGE_LIGHT, 0.5

        staged.append(
            {
                "t": epoch.start.isoformat(),
                "stage": stage,
                "confidence": confidence,
                "heart_rate": round(rate, 1) if rate is not None else None,
                "movement": round(movement, 3),
            }
        )

    return _smooth(staged)


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
        "method": "ouracle-local-v1",
    }


def build_epochs(
    heart_rate: List[Dict[str, Any]],
    movement: List[Dict[str, Any]],
    variability: Optional[Dict[str, float]] = None,
) -> List[Epoch]:
    """Join the per-bucket series into aligned epochs, keyed on timestamp."""
    by_time: Dict[str, Epoch] = {}
    for point in heart_rate:
        by_time[point["t"]] = Epoch(
            start=datetime.fromisoformat(point["t"]),
            movement=None,
            heart_rate=point["value"],
            hr_variability=(variability or {}).get(point["t"]),
        )
    for point in movement:
        existing = by_time.get(point["t"])
        if existing:
            existing.movement = point["value"]
        else:
            by_time[point["t"]] = Epoch(
                start=datetime.fromisoformat(point["t"]),
                movement=point["value"],
                heart_rate=None,
                hr_variability=None,
            )
    return [by_time[key] for key in sorted(by_time)]
