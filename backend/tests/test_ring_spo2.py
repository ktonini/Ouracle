"""Blood oxygen from the ring's ratio-of-ratios."""

from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.src.models import Base, RingEventRaw, Sleep, SleepSession
from backend.src.ring_events.decoders import decode_spo2_r_pi
from backend.src.ring_events.night import to_ring_ds
from backend.src.ring_events.spo2 import (
    DEFAULT_A, estimate, fit_calibration, load_calibration, ratios_between,
)

EPOCH = 1_700_000_000.0


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(
        RingEventRaw(id="42-0", tag=0x42, timestamp=0, body="",
                     decoded={"unix_time": EPOCH})
    )
    session.commit()
    return session


def test_decodes_the_four_ratio_readings():
    """A real frame: leading byte, then four (R, ?, ?) triplets."""
    decoded = decode_spo2_r_pi(bytes.fromhex("002b159630ff5c30da5e306c5e"))
    assert decoded is not None
    assert decoded["ratio"] == [0x2B, 0x30, 0x30, 0x30]
    assert len(decoded["unidentified"]) == 4


def test_decodes_a_short_frame():
    """The ring emits three-triplet frames too; a fixed length rejected 49."""
    decoded = decode_spo2_r_pi(bytes.fromhex("002c56ff36caff28a3ff"))
    assert decoded is not None
    assert decoded["ratio"] == [0x2C, 0x36, 0x28]


def test_rejects_the_wrong_shape():
    assert decode_spo2_r_pi(b"\x00\x01\x02") is None
    # Not a whole number of triplets.
    assert decode_spo2_r_pi(bytes(12)) is None
    # A ratio of zero is not a reading.
    assert decode_spo2_r_pi(bytes(13)) is None


def _night(db, day, ratio, count=80):
    start = datetime(2026, 8, day, 22, 0, tzinfo=timezone.utc)
    db.add(
        SleepSession(
            id=f"s-{day}", day=date(2026, 8, day),
            bedtime_start=start.replace(tzinfo=None),
            bedtime_end=(start + timedelta(hours=7)).replace(tzinfo=None),
            sleep_phase_5_min="2" * 60,
        )
    )
    for i in range(count):
        ds = to_ring_ds(start + timedelta(minutes=i), EPOCH)
        db.add(
            RingEventRaw(
                id=f"8b-{ds}", tag=0x8B, timestamp=ds, body="00",
                decoded={"ratio": [ratio] * 4},
            )
        )
    db.commit()
    return start


def test_estimate_needs_enough_readings(db_session):
    assert estimate([46] * 10) is None
    value = estimate([46] * 400)
    assert value is not None
    assert 70 <= value <= 100


def test_estimate_falls_back_to_the_textbook_curve(tmp_path, monkeypatch):
    """Before any nights are paired there is still an answer, from the
    population calibration rather than this ring's."""
    monkeypatch.setenv("OURACLE_DATA_DIR", str(tmp_path))
    calibration = load_calibration()
    assert calibration["fitted"] is False
    assert calibration["a"] == DEFAULT_A


def test_estimate_rejects_an_impossible_saturation():
    """An oximeter reporting 103% is broken, not remarkable."""
    assert estimate([1] * 400) is None      # R far too low -> over 100
    assert estimate([200] * 400) is None    # R far too high -> under 70


def test_calibration_needs_several_paired_nights(db_session, tmp_path, monkeypatch):
    monkeypatch.setenv("OURACLE_DATA_DIR", str(tmp_path))
    _night(db_session, 5, 46)
    db_session.add(Sleep(id="sl-5", day=date(2026, 8, 5), average_spo2=94.7))
    db_session.commit()
    result = fit_calibration(db_session)
    assert result["fitted"] is False
    assert "paired nights" in result["reason"]


def test_calibration_recovers_a_known_curve(db_session, tmp_path, monkeypatch):
    """Given nights generated from SpO2 = 110 - 0.34R, the fit must find it."""
    monkeypatch.setenv("OURACLE_DATA_DIR", str(tmp_path))
    for day, ratio in ((5, 44), (6, 47), (7, 50), (8, 53), (9, 56)):
        _night(db_session, day, ratio)
        db_session.add(
            Sleep(id=f"sl-{day}", day=date(2026, 8, day), average_spo2=round(110 - 0.34 * ratio, 2))
        )
    db_session.commit()

    result = fit_calibration(db_session)
    assert result["fitted"] is True
    assert result["nights"] == 5
    assert result["a"] == pytest.approx(110.0, abs=0.1)
    assert result["b"] == pytest.approx(0.34, abs=0.005)
    assert result["error"] < 0.05

    # And it is what estimate() then uses.
    saved = load_calibration()
    assert saved["fitted"] is True
    assert estimate([50] * 400, saved) == pytest.approx(93.0, abs=0.2)


def test_ratios_between_reads_only_the_window(db_session):
    start = _night(db_session, 5, 46)
    inside = ratios_between(db_session, start.replace(tzinfo=None),
                            (start + timedelta(hours=7)).replace(tzinfo=None))
    assert len(inside) == 320  # 80 events x 4 readings
    after = ratios_between(db_session, (start + timedelta(days=2)).replace(tzinfo=None),
                           (start + timedelta(days=3)).replace(tzinfo=None))
    assert after == []
