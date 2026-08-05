"""Oura v2 mappers: field mapping and datetime normalization."""

from datetime import date, datetime

from backend.src.oura_v2 import mappers


def test_parse_dt_normalizes_to_naive_utc():
    assert mappers.parse_dt("2026-08-01T02:30:00.000+02:00") == datetime(
        2026, 8, 1, 0, 30
    )
    assert mappers.parse_dt(None) is None


def test_map_daily_sleep():
    values = mappers.map_daily_sleep(
        {
            "id": "daily_sleep-1",
            "day": "2026-08-01",
            "score": 73,
            "contributors": {"deep_sleep": 90},
            "timestamp": "2026-08-01T00:00:00+00:00",
        }
    )
    assert values == {
        "id": "daily_sleep-1",
        "day": date(2026, 8, 1),
        "score": 73,
        "contributors": {"deep_sleep": 90},
    }


def test_merge_daily_spo2_unwraps_aggregate():
    values = mappers.merge_daily_spo2(
        {
            "id": "x",
            "day": "2026-08-01",
            "spo2_percentage": {"average": 97.2},
            "breathing_disturbance_index": 4,
        }
    )
    assert values["average_spo2"] == 97.2
    assert values["breathing_disturbance_index"] == 4
    assert "id" not in values


def test_map_daily_activity_renames_average_met():
    values = mappers.map_daily_activity(
        {"id": "a-1", "day": "2026-08-01", "average_met_minutes": 1.4, "steps": 9000}
    )
    assert values["average_met"] == 1.4
    assert values["steps"] == 9000


def test_map_daily_resilience_flattens_contributors():
    values = mappers.map_daily_resilience(
        {
            "id": "r-1",
            "day": "2026-08-01",
            "level": "solid",
            "contributors": {
                "sleep_recovery": 80.0,
                "daytime_recovery": 70.0,
                "stress": 60.0,
            },
        }
    )
    assert values["level"] == "solid"
    assert values["sleep_recovery"] == 80.0
    assert values["stress"] == 60.0


def test_map_sleep_session_renames_sequences():
    values = mappers.map_sleep_session(
        {
            "id": "sleep-1",
            "day": "2026-08-03",
            "bedtime_start": "2026-08-02T23:10:00+00:00",
            "bedtime_end": "2026-08-03T07:00:00+00:00",
            "heart_rate": {"interval": 60.0, "items": [60, 61]},
            "hrv": {"interval": 60.0, "items": [50, 55]},
            "type": "long_sleep",
        }
    )
    assert values["hr_data"] == {"interval": 60.0, "items": [60, 61]}
    assert values["hrv_data"] == {"interval": 60.0, "items": [50, 55]}
    assert values["start_time"] == datetime(2026, 8, 2, 23, 10)
    assert values["bedtime_end"] == datetime(2026, 8, 3, 7, 0)


def test_map_workout_renames_datetimes():
    values = mappers.map_workout(
        {
            "id": "w-1",
            "day": "2026-08-01",
            "start_datetime": "2026-08-01T10:00:00+00:00",
            "end_datetime": "2026-08-01T11:00:00+00:00",
            "activity": "running",
        }
    )
    assert values["start_time"] == datetime(2026, 8, 1, 10, 0)
    assert values["end_time"] == datetime(2026, 8, 1, 11, 0)


def test_map_enhanced_tag_falls_back_to_custom_name():
    values = mappers.map_enhanced_tag(
        {"id": "t-1", "tag_type_code": None, "comment": None, "custom_name": "sauna"}
    )
    assert values["comment"] == "sauna"


def test_map_heartrate_row():
    values = mappers.map_heartrate_row(
        {"timestamp": "2026-08-01T10:00:00+00:00", "bpm": 62, "source": "ppg"}
    )
    assert values == {
        "timestamp": datetime(2026, 8, 1, 10, 0),
        "bpm": 62,
        "source": "ppg",
    }
