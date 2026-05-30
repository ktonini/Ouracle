"""Unit tests for the action card rules engine."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from backend.src.insights import sync_freshness as sf_module
from backend.src.insights.action_cards import build_action_cards
from backend.src.models import (
    Activity,
    Readiness,
    RingBattery,
    Sleep,
    SleepSession,
)


def test_returns_no_data_card_when_database_empty(db_session):
    cards = build_action_cards(db_session, date(2025, 5, 1))
    ids = [c.id for c in cards]
    assert any(i.startswith("sync-empty-") for i in ids)
    assert all(c.severity in {"warning", "info", "critical"} for c in cards)


def test_short_sleep_and_low_score_emit_sleep_cards(db_session):
    day = date(2025, 5, 10)
    db_session.add(Sleep(id="s", day=day, score=50))
    db_session.add(SleepSession(
        id="ss", day=day, type="long_sleep",
        total_sleep_duration=5 * 60 * 60,  # 5h - under floor
    ))
    db_session.commit()

    cards = build_action_cards(db_session, day)
    ids = {c.id for c in cards}
    assert f"sleep-low-{day.isoformat()}" in ids
    assert f"sleep-duration-{day.isoformat()}" in ids


def test_low_battery_and_not_charging_emits_device_card(db_session):
    day = date(2025, 5, 12)
    db_session.add(Sleep(id="s", day=day, score=80))
    db_session.add(RingBattery(
        timestamp=datetime(2025, 5, 12, 8, 0, 0),
        level=15, charging=False, in_charger=False,
    ))
    db_session.commit()

    cards = build_action_cards(db_session, day)
    battery = next(c for c in cards if c.id.startswith("battery-low-"))
    assert battery.category == "device"
    assert any(e.metric == "ring_battery.level" for e in battery.evidence)


def test_activity_below_target_emits_info_card(db_session):
    day = date(2025, 5, 15)
    db_session.add(Activity(
        id="a", day=day, steps=3000,
        target_meters=8000, meters_to_target=5000,
    ))
    db_session.commit()

    cards = build_action_cards(db_session, day)
    activity_card = next(c for c in cards if c.id.startswith("activity-low-"))
    assert activity_card.severity == "info"
    metrics = {e.metric for e in activity_card.evidence}
    assert {"activity.steps", "activity.meters_to_target"}.issubset(metrics)


def test_hrv_drop_card_uses_14d_baseline(db_session):
    day = date(2025, 6, 1)
    # 14 prior days at hrv 60 - baseline is 60. Today is 45 → 15 below → triggers.
    for offset in range(1, 15):
        d = day - timedelta(days=offset)
        db_session.add(SleepSession(
            id=f"p-{d}", day=d, type="long_sleep",
            average_hrv=60, lowest_heart_rate=55,
            total_sleep_duration=8 * 60 * 60,
        ))
    db_session.add(SleepSession(
        id="today", day=day, type="long_sleep",
        average_hrv=45, lowest_heart_rate=55,
        total_sleep_duration=8 * 60 * 60,
    ))
    db_session.commit()

    cards = build_action_cards(db_session, day)
    assert any(c.id.startswith("hrv-drop-") for c in cards)


def test_stale_sync_card_uses_expected_day_not_calendar_today(db_session, monkeypatch):
    """Matches sync_freshness: tonight's sleep is not counted as missing."""

    today = date(2026, 5, 29)
    monkeypatch.setattr(sf_module, "date", type("D", (), {"today": staticmethod(lambda: today)})())

    latest = today - timedelta(days=3)  # 2026-05-26
    db_session.add(Sleep(id="s", day=latest, score=80))
    db_session.commit()

    cards = build_action_cards(db_session, today)
    sync_card = next(c for c in cards if c.id.startswith("sync-stale-"))
    assert "2 days behind" in sync_card.title
    assert "2026-05-28" in sync_card.reason


def test_card_results_are_capped_to_five(db_session):
    day = date(2025, 6, 10)
    # Trigger several rules at once.
    db_session.add(Sleep(id="s", day=day, score=40))
    db_session.add(Readiness(
        id="r", day=day, score=50,
        stress_high=400, recovery_high=50, temperature_deviation=0.8,
    ))
    db_session.add(Activity(
        id="a", day=day, steps=1000,
        target_meters=10000, meters_to_target=9000,
    ))
    db_session.add(SleepSession(
        id="ss", day=day, type="long_sleep",
        total_sleep_duration=4 * 60 * 60,
    ))
    db_session.add(RingBattery(
        timestamp=datetime(2025, 6, 10, 6, 0, 0),
        level=10, charging=False, in_charger=False,
    ))
    db_session.commit()
    cards = build_action_cards(db_session, day)
    assert len(cards) <= 5
