"""Recovering events the phone's frame splitter glued together."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.src.models import Base, RingEventRaw
from backend.src.ring_events.repair import repair_packed, split_packed


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def frame(tag: int, timestamp: int, body: bytes) -> bytes:
    """`<tag><length><timestamp×4><body>` as the ring sends it."""
    return bytes([tag, 4 + len(body)]) + timestamp.to_bytes(4, "little") + body


def test_splits_a_packed_row_into_its_events():
    parent = bytes(range(14))
    body = parent + frame(0x81, 1401, bytes(14)) + frame(0x72, 1402, bytes(12))
    own, events = split_packed(body, 1400)
    assert own == parent
    assert [(tag, ts) for tag, ts, _ in events] == [(0x81, 1401), (0x72, 1402)]
    assert len(events[1][2]) == 12


def test_leaves_an_ordinary_row_alone():
    # A plain 14-byte IBI body must not be mistaken for packed frames.
    assert split_packed(bytes.fromhex("696a6a6b7072c8c3bfa3aec04a31"), 1400) is None
    assert split_packed(b"", 1400) is None


def test_rejects_a_tail_that_does_not_land_exactly():
    body = bytes(range(14)) + frame(0x81, 1401, bytes(14)) + b"\x99\x99"
    assert split_packed(body, 1400) is None


def test_rejects_implausible_tags():
    """0x20 is a command response, never a packed history event."""
    body = bytes(range(14)) + frame(0x20, 1401, bytes(14))
    assert split_packed(body, 1400) is None


def test_rejects_timestamps_far_from_the_parent():
    body = bytes(range(14)) + frame(0x81, 9_999_999, bytes(14))
    assert split_packed(body, 1400) is None


def test_repair_reports_before_it_writes(db_session):
    body = bytes(range(14)) + frame(0x81, 1401, bytes(14))
    db_session.add(
        RingEventRaw(id="60-1400", tag=0x60, timestamp=1400, body=body.hex())
    )
    db_session.commit()

    result = repair_packed(db_session, apply=False)
    assert result["rows_repaired"] == 1
    assert result["events_recovered"] == 1
    assert result["applied"] is False
    # Nothing changed.
    assert db_session.query(RingEventRaw).count() == 1
    assert db_session.get(RingEventRaw, "60-1400").body == body.hex()


def test_repair_unpacks_and_trims_the_parent(db_session):
    parent = bytes(range(14))
    body = parent + frame(0x81, 1401, bytes(14)) + frame(0x72, 1402, bytes(12))
    db_session.add(
        RingEventRaw(
            id="60-1400", tag=0x60, timestamp=1400, body=body.hex(),
            decoded={"stale": True},
        )
    )
    db_session.commit()

    result = repair_packed(db_session, apply=True)
    assert result["rows_repaired"] == 1
    assert result["events_recovered"] == 2

    assert db_session.query(RingEventRaw).count() == 3
    parent_row = db_session.get(RingEventRaw, "60-1400")
    assert parent_row.body == parent.hex()
    # The old decode described the glued body, so it must not survive.
    assert parent_row.decoded is None
    assert db_session.get(RingEventRaw, "81-1401") is not None
    assert db_session.get(RingEventRaw, "72-1402").tag == 0x72


def test_repair_is_idempotent(db_session):
    body = bytes(range(14)) + frame(0x81, 1401, bytes(14))
    db_session.add(
        RingEventRaw(id="60-1400", tag=0x60, timestamp=1400, body=body.hex())
    )
    db_session.commit()

    repair_packed(db_session, apply=True)
    again = repair_packed(db_session, apply=True)
    assert again["rows_repaired"] == 0
    assert db_session.query(RingEventRaw).count() == 2


def test_repeated_events_in_one_run_do_not_collide(db_session):
    """Tag plus timestamp is the identity, and a packed run can carry the same
    event twice — inserting blind raised a UNIQUE violation and lost the lot."""
    body = (
        bytes(range(14))
        + frame(0x81, 1401, bytes(14))
        + frame(0x81, 1401, bytes(14))  # same event again
    )
    db_session.add(
        RingEventRaw(id="60-1400", tag=0x60, timestamp=1400, body=body.hex())
    )
    db_session.commit()

    result = repair_packed(db_session, apply=True)
    assert result["events_recovered"] == 2
    assert result["unique_events"] == 1
    assert db_session.query(RingEventRaw).count() == 2


def test_cleared_decode_is_sql_null_so_it_gets_redecoded(db_session):
    """Regression: a plain JSON column stores None as the JSON value 'null',
    which satisfies "IS NOT NULL" but reads back as None. Repaired rows then
    looked decoded to every query, crashed on use, and were never re-decoded."""
    from backend.src.ring_events.runner import decode_stored

    # 0x72 needs 12 bytes; give it that plus a packed 0x81 behind it.
    parent = bytes.fromhex("01" * 12)
    body = parent + frame(0x81, 1401, bytes(14))
    db_session.add(
        RingEventRaw(
            id="72-1400", tag=0x72, timestamp=1400, body=body.hex(),
            decoded={"stale": True},
        )
    )
    db_session.commit()

    repair_packed(db_session, apply=True)
    # The stale decode must be gone in a way the next pass can see.
    assert (
        db_session.query(RingEventRaw)
        .filter(RingEventRaw.decoded.is_(None))
        .count()
        == 2
    )
    decode_stored(db_session)
    parent_row = db_session.get(RingEventRaw, "72-1400")
    assert parent_row.decoded is not None
    assert parent_row.decoded["_event"] == "sleep_acm_period"
