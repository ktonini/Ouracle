"""Map Oura API v2 documents onto the existing SQLAlchemy models.

The models were shaped after the CSV export, which the v2 API mirrors almost
field-for-field; each mapper returns a dict of column values (never a model
instance) so the sync layer can decide between insert and update.

Known gaps versus the CSV export:
- No v2 collection for the skin-temperature time series (``temperature`` table);
  only the readiness deviations are available.
- ``activity.stress`` sequence has no v2 equivalent (``daily_stress`` totals
  merge into readiness instead).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, Optional


def parse_day(value: Optional[str]) -> Optional[date]:
    return date.fromisoformat(value) if value else None


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    """ISO-8601 → naive UTC, matching SQLite DateTime column conventions."""
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _int(value: Any) -> Optional[int]:
    return int(value) if value is not None else None


# --- Day-keyed summaries -----------------------------------------------------

def map_daily_sleep(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc["id"],
        "day": parse_day(doc.get("day")),
        "score": _int(doc.get("score")),
        "contributors": doc.get("contributors"),
    }


def merge_daily_spo2(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Merges into the ``sleep`` row for the same day."""
    spo2 = doc.get("spo2_percentage") or {}
    return {
        "day": parse_day(doc.get("day")),
        "average_spo2": spo2.get("average"),
        "breathing_disturbance_index": _int(doc.get("breathing_disturbance_index")),
    }


def merge_sleep_time(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Merges into the ``sleep`` row for the same day."""
    return {
        "day": parse_day(doc.get("day")),
        "optimal_bedtime": doc.get("optimal_bedtime"),
        "recommendation": doc.get("recommendation"),
        "status": doc.get("status"),
    }


def map_daily_activity(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc["id"],
        "day": parse_day(doc.get("day")),
        "score": _int(doc.get("score")),
        "steps": _int(doc.get("steps")),
        "total_calories": _int(doc.get("total_calories")),
        "active_calories": _int(doc.get("active_calories")),
        # v2 calls the daily average MET "average_met_minutes"; same metric as
        # the export's "Average MET".
        "average_met": doc.get("average_met_minutes"),
        "equivalent_walking_distance": _int(doc.get("equivalent_walking_distance")),
        "contributors": doc.get("contributors"),
        "class_5_min": doc.get("class_5_min"),
        "met": doc.get("met"),
        "high_activity_met_minutes": _int(doc.get("high_activity_met_minutes")),
        "high_activity_time": _int(doc.get("high_activity_time")),
        "inactivity_alerts": _int(doc.get("inactivity_alerts")),
        "low_activity_met_minutes": _int(doc.get("low_activity_met_minutes")),
        "low_activity_time": _int(doc.get("low_activity_time")),
        "medium_activity_met_minutes": _int(doc.get("medium_activity_met_minutes")),
        "medium_activity_time": _int(doc.get("medium_activity_time")),
        "meters_to_target": _int(doc.get("meters_to_target")),
        "non_wear_time": _int(doc.get("non_wear_time")),
        "resting_time": _int(doc.get("resting_time")),
        "sedentary_met_minutes": _int(doc.get("sedentary_met_minutes")),
        "sedentary_time": _int(doc.get("sedentary_time")),
        "target_calories": _int(doc.get("target_calories")),
        "target_meters": _int(doc.get("target_meters")),
    }


def map_daily_readiness(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc["id"],
        "day": parse_day(doc.get("day")),
        "score": _int(doc.get("score")),
        "temperature_deviation": doc.get("temperature_deviation"),
        "temperature_trend_deviation": doc.get("temperature_trend_deviation"),
        "contributors": doc.get("contributors"),
    }


def merge_daily_stress(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Merges into the ``readiness`` row for the same day."""
    return {
        "day": parse_day(doc.get("day")),
        "stress_high": _int(doc.get("stress_high")),
        "recovery_high": _int(doc.get("recovery_high")),
        "day_summary": doc.get("day_summary"),
    }


def map_daily_resilience(doc: Dict[str, Any]) -> Dict[str, Any]:
    contributors = doc.get("contributors") or {}
    return {
        "id": doc["id"],
        "day": parse_day(doc.get("day")),
        "level": doc.get("level"),
        "sleep_recovery": contributors.get("sleep_recovery"),
        "daytime_recovery": contributors.get("daytime_recovery"),
        "stress": contributors.get("stress"),
    }


def map_daily_cardiovascular_age(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc["id"],
        "day": parse_day(doc.get("day")),
        "vascular_age": _int(doc.get("vascular_age")),
    }


# --- Id-keyed documents ------------------------------------------------------

def map_sleep_session(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc["id"],
        "day": parse_day(doc.get("day")),
        "start_time": parse_dt(doc.get("bedtime_start")),
        "end_time": parse_dt(doc.get("bedtime_end")),
        "bedtime_start": parse_dt(doc.get("bedtime_start")),
        "bedtime_end": parse_dt(doc.get("bedtime_end")),
        "type": doc.get("type"),
        "efficiency": _int(doc.get("efficiency")),
        "latency": _int(doc.get("latency")),
        "total_sleep_duration": _int(doc.get("total_sleep_duration")),
        "deep_sleep_duration": _int(doc.get("deep_sleep_duration")),
        "rem_sleep_duration": _int(doc.get("rem_sleep_duration")),
        "light_sleep_duration": _int(doc.get("light_sleep_duration")),
        "awake_time": _int(doc.get("awake_time")),
        "average_heart_rate": doc.get("average_heart_rate"),
        "average_hrv": _int(doc.get("average_hrv")),
        "average_breath": doc.get("average_breath"),
        "lowest_heart_rate": _int(doc.get("lowest_heart_rate")),
        "low_battery_alert": doc.get("low_battery_alert"),
        "period": _int(doc.get("period")),
        "restless_periods": _int(doc.get("restless_periods")),
        "sleep_algorithm_version": doc.get("sleep_algorithm_version"),
        "sleep_score_delta": _int(doc.get("sleep_score_delta")),
        "readiness_score_delta": doc.get("readiness_score_delta"),
        "time_in_bed": _int(doc.get("time_in_bed")),
        "sleep_phase_5_min": doc.get("sleep_phase_5_min"),
        "sleep_phase_30_sec": doc.get("sleep_phase_30_sec"),
        "movement_30_sec": doc.get("movement_30_sec"),
        "hr_data": doc.get("heart_rate"),
        "hrv_data": doc.get("hrv"),
        "readiness": doc.get("readiness"),
    }


def map_workout(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc["id"],
        "day": parse_day(doc.get("day")),
        "start_time": parse_dt(doc.get("start_datetime")),
        "end_time": parse_dt(doc.get("end_datetime")),
        "activity": doc.get("activity"),
        "calories": doc.get("calories"),
        "distance": doc.get("distance"),
        "intensity": doc.get("intensity"),
        "label": doc.get("label"),
        "source": doc.get("source"),
    }


def map_session(doc: Dict[str, Any]) -> Dict[str, Any]:
    """v2 ``session`` documents land in the ``meditation`` table."""
    return {
        "id": doc["id"],
        "day": parse_day(doc.get("day")),
        "start_time": parse_dt(doc.get("start_datetime")),
        "end_time": parse_dt(doc.get("end_datetime")),
        "type": doc.get("type"),
        "mood": doc.get("mood"),
    }


def map_enhanced_tag(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc["id"],
        "start_time": parse_dt(doc.get("start_time")),
        "end_time": parse_dt(doc.get("end_time")),
        "tag_type_code": doc.get("tag_type_code"),
        "comment": doc.get("comment") or doc.get("custom_name"),
    }


def map_ring_configuration(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": doc["id"],
        "firmware_version": doc.get("firmware_version"),
        "size": _int(doc.get("size")),
        "color": doc.get("color"),
        "hardware_type": doc.get("hardware_type"),
    }


# --- Timestamp-keyed time series ---------------------------------------------

def map_heartrate_row(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "timestamp": parse_dt(doc.get("timestamp")),
        "bpm": _int(doc.get("bpm")),
        "source": doc.get("source"),
    }


def map_ring_battery_row(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "timestamp": parse_dt(doc.get("timestamp")),
        "level": _int(doc.get("level")),
        "charging": doc.get("charging"),
        "in_charger": doc.get("in_charger"),
    }
