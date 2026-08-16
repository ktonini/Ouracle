"""Deterministic action-card rules engine.

Mirrors the Oura "Today" action feed using only data already in the local
database. Each card is traceable to the metric, value, day, and source path
that triggered it, and the engine is fully recomputable for any given day.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from ..models import Activity, Readiness, RingBattery, Sleep, SleepSession
from .baselines import build_baseline_bundle
from .sync_freshness import _latest_day, data_lag_days, expected_latest_day

# Severity ranking used for ordering. Higher numbers render first.
_SEVERITY_RANK = {"critical": 3, "warning": 2, "info": 1}


@dataclass
class ActionEvidence:
    metric: str
    value: Any
    day: Optional[str]
    source_path: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ActionCard:
    id: str
    day: str
    severity: str  # critical | warning | info
    category: str  # sync | recovery | sleep | activity | data | device
    title: str
    reason: str
    recommendation: str
    evidence: List[ActionEvidence] = field(default_factory=list)
    dismissible: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "day": self.day,
            "severity": self.severity,
            "category": self.category,
            "title": self.title,
            "reason": self.reason,
            "recommendation": self.recommendation,
            "evidence": [e.to_dict() for e in self.evidence],
            "dismissible": self.dismissible,
        }


def _latest_battery(db: Session) -> Optional[RingBattery]:
    return (
        db.query(RingBattery)
        .order_by(RingBattery.timestamp.desc())
        .limit(1)
        .one_or_none()
    )


def _primary_session(db: Session, day: date) -> Optional[SleepSession]:
    sessions = (
        db.query(SleepSession)
        .filter(SleepSession.day == day)
        .filter(SleepSession.type.in_(["long_sleep", "sleep"]))
        .all()
    )
    if not sessions:
        return None
    return max(sessions, key=lambda s: s.total_sleep_duration or 0)


def build_action_cards(
    db: Session, day: date, today: Optional[date] = None
) -> List[ActionCard]:
    """Evaluate all rules for ``day`` and return ordered ``ActionCard`` list."""

    today = today or date.today()
    cards: List[ActionCard] = []
    day_str = day.isoformat()

    sleep = db.query(Sleep).filter(Sleep.day == day).one_or_none()
    activity = db.query(Activity).filter(Activity.day == day).one_or_none()
    readiness = db.query(Readiness).filter(Readiness.day == day).one_or_none()
    session = _primary_session(db, day)

    # --- Sync freshness (same expected-day model as sync_freshness.py) ------
    latest = _latest_day(db)
    expected = expected_latest_day()
    if latest is None:
        cards.append(ActionCard(
            id=f"sync-empty-{day_str}", day=day_str, severity="warning",
            category="sync", title="No Oura data ingested yet",
            reason="The local database has no daily summaries.",
            recommendation="Run a sync or upload an Oura export ZIP from Settings.",
        ))
    else:
        lag_days = data_lag_days(latest)
        if lag_days is not None and lag_days >= 1:
            day_word = "day" if lag_days == 1 else "days"
            cards.append(ActionCard(
                id=f"sync-stale-{day_str}", day=day_str, severity="warning",
                category="sync",
                title=f"Local data is {lag_days} {day_word} behind",
                reason=(
                    f"Latest ingested day is {latest.isoformat()}; "
                    f"expecting through {expected.isoformat()}."
                ),
                recommendation="Trigger a fresh export request from Settings.",
                evidence=[
                    ActionEvidence(
                        metric="latest_day",
                        value=latest.isoformat(),
                        day=latest.isoformat(),
                        source_path="sync.latest_day",
                    ),
                    ActionEvidence(
                        metric="expected_latest_day",
                        value=expected.isoformat(),
                        day=expected.isoformat(),
                        source_path="sync.expected_latest_day",
                    ),
                ],
            ))

    # --- Ring battery -------------------------------------------------------
    battery = _latest_battery(db)
    if battery is not None and battery.level is not None and battery.level <= 20 and not battery.charging:
        cards.append(ActionCard(
            id=f"battery-low-{day_str}", day=day_str, severity="warning",
            category="device", title=f"Ring battery at {battery.level}%",
            reason="Recent battery reading is low and the ring is not charging.",
            recommendation="Charge the ring before sleep to capture overnight data.",
            evidence=[ActionEvidence(metric="ring_battery.level", value=battery.level,
                                      day=battery.timestamp.date().isoformat() if battery.timestamp else None,
                                      source_path="ring_battery.level")],
        ))

    # --- Readiness ----------------------------------------------------------
    if readiness is not None and readiness.score is not None and readiness.score < 60:
        cards.append(ActionCard(
            id=f"readiness-low-{day_str}", day=day_str, severity="warning",
            category="recovery", title=f"Readiness is {readiness.score}",
            reason="Readiness score is below 60.",
            recommendation="Favor recovery: shorter workouts, hydration, earlier bedtime.",
            evidence=[ActionEvidence(metric="readiness.score", value=readiness.score,
                                      day=day_str, source_path="readiness.score")],
        ))

    # --- Sleep --------------------------------------------------------------
    if sleep is not None and sleep.score is not None and sleep.score < 65:
        cards.append(ActionCard(
            id=f"sleep-low-{day_str}", day=day_str, severity="warning",
            category="sleep", title=f"Sleep score is {sleep.score}",
            reason="Sleep score is below 65.",
            recommendation="Aim for an earlier bedtime tonight and reduce evening stimulants.",
            evidence=[ActionEvidence(metric="sleep.score", value=sleep.score,
                                      day=day_str, source_path="sleep.score")],
        ))

    if session is not None and session.total_sleep_duration is not None:
        minutes = session.total_sleep_duration / 60.0
        if minutes < 360:
            cards.append(ActionCard(
                id=f"sleep-duration-{day_str}", day=day_str, severity="warning",
                category="sleep", title="Sleep was short last night",
                reason=f"Total sleep was {int(minutes)} minutes (under 6 hours).",
                recommendation="Try to bank an extra hour tonight if your schedule allows.",
                evidence=[ActionEvidence(metric="sleep_session.total_sleep_duration",
                                          value=session.total_sleep_duration,
                                          day=day_str,
                                          source_path="sleep_session.total_sleep_duration")],
            ))

    # --- Activity goal ------------------------------------------------------
    if activity is not None:
        steps = activity.steps or 0
        target_meters = activity.target_meters or 0
        meters_to_target = activity.meters_to_target or 0
        if target_meters > 0 and meters_to_target > 0 and steps < 5000:
            cards.append(ActionCard(
                id=f"activity-low-{day_str}", day=day_str, severity="info",
                category="activity", title="Activity target still open",
                reason=f"{steps} steps recorded; {meters_to_target} m to daily goal.",
                recommendation="A 15-20 minute walk would close most of the remaining gap.",
                evidence=[
                    ActionEvidence(metric="activity.steps", value=steps,
                                    day=day_str, source_path="activity.steps"),
                    ActionEvidence(metric="activity.meters_to_target",
                                    value=meters_to_target, day=day_str,
                                    source_path="activity.meters_to_target"),
                ],
            ))

    # --- Baseline-derived signals ------------------------------------------
    bundle = build_baseline_bundle(db, day)
    by_metric = {d.metric: d for d in bundle.deltas}

    hrv = by_metric.get("hrv")
    if hrv and hrv.current is not None and hrv.baseline_14d is not None:
        if hrv.current <= hrv.baseline_14d - 8:
            cards.append(ActionCard(
                id=f"hrv-drop-{day_str}", day=day_str, severity="warning",
                category="recovery", title="HRV is below your baseline",
                reason=f"HRV {hrv.current} ms is {abs(hrv.delta_14d):.1f} ms below your 14-day baseline ({hrv.baseline_14d}).",
                recommendation="Treat today as a recovery day; light activity, fluids, early night.",
                evidence=[ActionEvidence(metric="hrv", value=hrv.current,
                                          day=day_str, source_path="sleep_session.average_hrv")],
            ))

    temp = by_metric.get("temperature_deviation")
    if temp and temp.current is not None and abs(temp.current) >= 0.6:
        cards.append(ActionCard(
            id=f"temp-deviation-{day_str}", day=day_str, severity="warning",
            category="recovery", title="Body temperature is off baseline",
            reason=f"Temperature deviation is {temp.current:+.1f} °C from your baseline.",
            recommendation="Watch for early signs of illness, prioritize rest and hydration.",
            evidence=[ActionEvidence(metric="temperature_deviation", value=temp.current,
                                      day=day_str, source_path="readiness.temperature_deviation")],
        ))

    rhr = by_metric.get("resting_hr")
    if rhr and rhr.current is not None and rhr.baseline_14d is not None:
        if rhr.current >= rhr.baseline_14d + 5:
            cards.append(ActionCard(
                id=f"rhr-up-{day_str}", day=day_str, severity="info",
                category="recovery", title="Resting heart rate is elevated",
                reason=f"Resting HR {rhr.current:.0f} bpm is {rhr.delta_14d:+.1f} bpm vs your 14-day baseline.",
                recommendation="Common after late food, alcohol, or training stress — ease back.",
                evidence=[ActionEvidence(metric="resting_hr", value=rhr.current,
                                          day=day_str, source_path="sleep_session.lowest_heart_rate")],
            ))

    # --- Stress / recovery imbalance ---------------------------------------
    if readiness is not None and readiness.stress_high is not None and readiness.recovery_high is not None:
        if readiness.stress_high > readiness.recovery_high * 2 and readiness.stress_high >= 180:
            cards.append(ActionCard(
                id=f"stress-balance-{day_str}", day=day_str, severity="info",
                category="recovery", title="Stress outweighed recovery yesterday",
                reason=f"{readiness.stress_high} min high stress vs {readiness.recovery_high} min high recovery.",
                recommendation="Schedule a wind-down block this evening.",
                evidence=[
                    ActionEvidence(metric="readiness.stress_high", value=readiness.stress_high,
                                    day=day_str, source_path="readiness.stress_high"),
                    ActionEvidence(metric="readiness.recovery_high", value=readiness.recovery_high,
                                    day=day_str, source_path="readiness.recovery_high"),
                ],
            ))

    # --- Missing-data card --------------------------------------------------
    missing: List[str] = []
    if sleep is None: missing.append("sleep")
    if activity is None: missing.append("activity")
    if readiness is None: missing.append("readiness")
    # Never for today. A day still in progress has nothing missing — the night
    # may not have happened yet, let alone been scored — and warning about it
    # turns every morning into a fault report.
    if missing and latest is not None and day < today and day <= latest:
        cards.append(ActionCard(
            id=f"data-missing-{day_str}", day=day_str, severity="info",
            category="data", title="Some metrics were not exported for this day",
            reason=f"Missing: {', '.join(missing)}.",
            recommendation="Check ring wear time, charge state, and sync window for this date.",
            evidence=[ActionEvidence(metric="missing_domains", value=missing,
                                      day=day_str, source_path="sync.coverage")],
        ))

    # Sort by severity then by category for stable rendering, cap to 5.
    cards.sort(key=lambda c: (-_SEVERITY_RANK.get(c.severity, 0), c.category))
    return cards[:5]

