"""Oura v2 sync driver: upserts, day-merges, watermarks, idempotency."""

from datetime import date, timedelta

import pytest

from backend.src.models import Activity, Readiness, Sleep, SleepSession, Workout
from backend.src.oura_v2 import sync as sync_mod
from backend.src.oura_v2.sync import (
    COLLECTIONS,
    get_watermark,
    run_sync,
    sync_collection,
)

TODAY = date(2026, 8, 4)


class FakeClient:
    """Stands in for OuraV2Client; serves canned documents per collection."""

    def __init__(self, data):
        self.data = data
        self.requests = []

    def fetch_collection(self, collection, start=None, end=None, datetime_params=False):
        self.requests.append((collection, start, end, datetime_params))
        yield from self.data.get(collection, [])


def spec(name):
    return next(s for s in COLLECTIONS if s.name == name)


def test_daily_merge_collections_share_a_row(db_session):
    client = FakeClient(
        {
            "daily_sleep": [
                {"id": "ds-1", "day": "2026-08-03", "score": 80, "contributors": {}}
            ],
            "daily_spo2": [
                {
                    "id": "spo2-1",
                    "day": "2026-08-03",
                    "spo2_percentage": {"average": 96.5},
                    "breathing_disturbance_index": 2,
                }
            ],
            "sleep_time": [
                {
                    "id": "st-1",
                    "day": "2026-08-03",
                    "recommendation": "earlier_bedtime",
                    "status": "not_enough_nights",
                }
            ],
        }
    )
    run_sync(
        db_session,
        client,
        only=["daily_sleep", "daily_spo2", "sleep_time"],
    )
    rows = db_session.query(Sleep).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.id == "ds-1"  # base row id preserved through merges
    assert row.score == 80
    assert row.average_spo2 == 96.5
    assert row.recommendation == "earlier_bedtime"


def test_merge_fragment_without_base_row_synthesizes_id(db_session):
    client = FakeClient(
        {
            "daily_stress": [
                {"id": "stress-1", "day": "2026-08-02", "stress_high": 3600,
                 "recovery_high": 1800, "day_summary": "restored"}
            ]
        }
    )
    run_sync(db_session, client, only=["daily_stress"])
    row = db_session.query(Readiness).one()
    assert row.day == date(2026, 8, 2)
    assert row.stress_high == 3600
    assert row.id  # synthesized, non-empty


def test_rerun_is_idempotent_and_updates_scores(db_session):
    docs = {
        "daily_activity": [
            {"id": "da-1", "day": "2026-08-03", "score": 70, "steps": 8000}
        ]
    }
    run_sync(db_session, FakeClient(docs), only=["daily_activity"])
    docs["daily_activity"][0]["score"] = 75  # Oura rescored the day
    run_sync(db_session, FakeClient(docs), only=["daily_activity"])
    rows = db_session.query(Activity).all()
    assert len(rows) == 1
    assert rows[0].score == 75


def test_duplicate_days_in_one_batch_collapse(db_session):
    # Regression: Oura's sandbox stamps many cardiovascular_age docs with the
    # same day; the second must update the first, not violate day-uniqueness.
    client = FakeClient(
        {
            "daily_cardiovascular_age": [
                {"id": "cva-1", "day": "2021-01-01", "vascular_age": 47},
                {"id": "cva-2", "day": "2021-01-01", "vascular_age": 45},
            ]
        }
    )
    run_sync(db_session, client, only=["daily_cardiovascular_age"])
    from backend.src.models import CardiovascularAge

    rows = db_session.query(CardiovascularAge).all()
    assert len(rows) == 1
    assert rows[0].vascular_age == 45


def test_id_keyed_upsert_merges_by_pk(db_session):
    docs = {
        "workout": [
            {"id": "w-1", "day": "2026-08-01", "activity": "running", "calories": 300}
        ]
    }
    run_sync(db_session, FakeClient(docs), only=["workout"])
    docs["workout"][0]["calories"] = 320
    run_sync(db_session, FakeClient(docs), only=["workout"])
    rows = db_session.query(Workout).all()
    assert len(rows) == 1
    assert rows[0].calories == 320


def test_first_run_uses_backfill_window(db_session):
    client = FakeClient({})
    sync_collection(
        db_session, client, spec("daily_sleep"), backfill_days=30, overlap_days=3,
        today=TODAY,
    )
    (collection, start, end, datetime_params) = client.requests[0]
    assert collection == "daily_sleep"
    assert start == TODAY - timedelta(days=30)
    assert end == TODAY + timedelta(days=1)
    assert datetime_params is False
    assert get_watermark(db_session, "daily_sleep") == TODAY


def test_subsequent_run_starts_from_watermark_minus_overlap(db_session):
    client = FakeClient({})
    s = spec("daily_sleep")
    sync_collection(db_session, client, s, 30, 3, today=TODAY - timedelta(days=2))
    sync_collection(db_session, client, s, 30, 3, today=TODAY)
    (_, start, _, _) = client.requests[1]
    assert start == (TODAY - timedelta(days=2)) - timedelta(days=3)


def test_datetime_collections_chunk_to_30_day_cap(db_session):
    client = FakeClient({})
    sync_collection(db_session, client, spec("heartrate"), 90, 3, today=TODAY)
    assert all(req[3] is True for req in client.requests)
    # 91-day span (backfill + today+1) in <=28-day chunks: 4 requests,
    # contiguous, none exceeding the API's 30-day limit.
    assert len(client.requests) == 4
    spans = [(req[1], req[2]) for req in client.requests]
    assert spans[0][0].isoformat() == "2026-05-06T00:00:00+00:00"
    assert spans[-1][1].isoformat() == "2026-08-05T00:00:00+00:00"
    for (s, e) in spans:
        assert (e - s).days <= 30
    for prev, nxt in zip(spans, spans[1:]):
        assert prev[1] == nxt[0]


def test_sleep_sessions_and_sequences_round_trip(db_session):
    client = FakeClient(
        {
            "sleep": [
                {
                    "id": "sleep-1",
                    "day": "2026-08-03",
                    "bedtime_start": "2026-08-02T23:00:00+00:00",
                    "bedtime_end": "2026-08-03T07:00:00+00:00",
                    "type": "long_sleep",
                    "heart_rate": {"interval": 60.0, "items": [60, 62]},
                    "efficiency": 88,
                }
            ]
        }
    )
    run_sync(db_session, client, only=["sleep"])
    row = db_session.query(SleepSession).one()
    assert row.type == "long_sleep"
    assert row.hr_data == {"interval": 60.0, "items": [60, 62]}
    assert row.efficiency == 88


def test_windowless_collection_has_no_dates_or_watermark(db_session):
    client = FakeClient(
        {"ring_configuration": [{"id": "rc-1", "color": "silver", "size": 10}]}
    )
    run_sync(db_session, client, only=["ring_configuration"])
    (_, start, end, _) = client.requests[0]
    assert start is None and end is None
    assert get_watermark(db_session, "ring_configuration") is None


def test_credential_403_skips_collection_but_continues(db_session):
    from backend.src.oura_v2.credentials import CredentialError

    class PickyClient(FakeClient):
        def fetch_collection(self, collection, start=None, end=None, datetime_params=False):
            if collection == "daily_cardiovascular_age":
                raise CredentialError("Oura returned 403 for cardio")
            return super().fetch_collection(collection, start, end, datetime_params)

    client = PickyClient(
        {"daily_sleep": [{"id": "ds-1", "day": "2026-08-03", "score": 80}]}
    )
    counts = run_sync(
        db_session, client, only=["daily_cardiovascular_age", "daily_sleep"]
    )
    assert counts["daily_cardiovascular_age"] == -1
    assert counts["daily_sleep"] == 1


def test_non_403_credential_error_aborts(db_session):
    from backend.src.oura_v2.credentials import CredentialError

    class DeadTokenClient(FakeClient):
        def fetch_collection(self, *a, **k):
            raise CredentialError("401 token dead")
            yield  # pragma: no cover

    with pytest.raises(CredentialError):
        run_sync(db_session, DeadTokenClient({}), only=["daily_sleep"])
