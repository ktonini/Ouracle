import json
import ipaddress
import logging
import os
import secrets
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..config import config_manager
from ..database import get_db
from ..mobile_server_manager import mobile_server_manager
from ..models import (
    Activity,
    CardiovascularAge,
    Readiness,
    Resilience,
    RingBattery,
    Sleep,
    SleepSession,
    Workout,
)
from ..insights import (
    build_action_cards,
    build_baseline_bundle,
    build_contributor_summaries,
    build_daily_guidance,
    build_sync_freshness,
)

logger = logging.getLogger("MobileAPI")

mobile_client_router = APIRouter(tags=["mobile"])
mobile_admin_router = APIRouter(tags=["mobile-admin"])
# Desktop app includes both; the LAN mobile process includes only mobile_client_router.
router = APIRouter()
router.include_router(mobile_client_router)
router.include_router(mobile_admin_router)

DEFAULT_WINDOW_DAYS = 180
DEFAULT_BIND_HOST = "0.0.0.0"
DEFAULT_PORT = 8037
TOKEN_HEADER = "X-Cracked-Oura-Token"


class MobileSettingsUpdate(BaseModel):
    enabled: Optional[bool] = None
    token: Optional[str] = None
    regenerate_token: bool = False
    default_window_days: Optional[int] = Field(default=None, ge=7, le=730)
    bind_host: Optional[str] = None
    port: Optional[int] = Field(default=None, ge=1024, le=65535)


class MobileSettingsResponse(BaseModel):
    enabled: bool
    token: str
    default_window_days: int
    bind_host: str
    port: int
    latest_day: Optional[date] = None
    has_data: bool
    run_command: str
    server_running: bool
    server_status: str


class MobileServerStatusResponse(BaseModel):
    status: str
    generated_at: datetime
    latest_day: Optional[date] = None
    default_window_days: int
    server_version: str


class MobileWorkoutResponse(BaseModel):
    id: str
    day: date
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    activity: Optional[str] = None
    calories: Optional[float] = None
    distance: Optional[float] = None
    intensity: Optional[str] = None
    label: Optional[str] = None
    source: Optional[str] = None


class MobileDailySummaryResponse(BaseModel):
    day: date
    sleep_score: Optional[int] = None
    sleep_contributors: Optional[Dict[str, Any]] = None
    sleep_status: Optional[str] = None
    sleep_recommendation: Optional[str] = None
    average_spo2: Optional[float] = None
    breathing_disturbance_index: Optional[int] = None
    activity_score: Optional[int] = None
    steps: Optional[int] = None
    total_calories: Optional[int] = None
    active_calories: Optional[int] = None
    average_met: Optional[float] = None
    equivalent_walking_distance: Optional[int] = None
    target_calories: Optional[int] = None
    target_meters: Optional[int] = None
    meters_to_target: Optional[int] = None
    inactivity_alerts: Optional[int] = None
    resting_time: Optional[int] = None
    sedentary_time: Optional[int] = None
    low_activity_time: Optional[int] = None
    medium_activity_time: Optional[int] = None
    high_activity_time: Optional[int] = None
    activity_contributors: Optional[Dict[str, Any]] = None
    readiness_score: Optional[int] = None
    readiness_contributors: Optional[Dict[str, Any]] = None
    temperature_deviation: Optional[float] = None
    temperature_trend_deviation: Optional[float] = None
    stress_high: Optional[int] = None
    recovery_high: Optional[int] = None
    day_summary: Optional[str] = None
    resilience_level: Optional[str] = None
    resilience_sleep_recovery: Optional[float] = None
    resilience_daytime_recovery: Optional[float] = None
    resilience_stress: Optional[float] = None
    vascular_age: Optional[int] = None
    sleep_type: Optional[str] = None
    sleep_start_time: Optional[datetime] = None
    sleep_end_time: Optional[datetime] = None
    bedtime_start: Optional[datetime] = None
    bedtime_end: Optional[datetime] = None
    sleep_efficiency: Optional[int] = None
    total_sleep_duration: Optional[int] = None
    deep_sleep_duration: Optional[int] = None
    rem_sleep_duration: Optional[int] = None
    light_sleep_duration: Optional[int] = None
    awake_time: Optional[int] = None
    average_heart_rate: Optional[float] = None
    average_hrv: Optional[int] = None
    lowest_heart_rate: Optional[int] = None
    readiness_score_delta: Optional[float] = None
    sleep_score_delta: Optional[int] = None
    time_in_bed: Optional[int] = None
    total_sleep_duration_all_sessions: Optional[int] = None
    nap_sleep_duration: Optional[int] = None
    sleep_session_count: Optional[int] = None


class MobileContributorSummary(BaseModel):
    domain: str
    key: str
    label: str
    status: str
    value: Optional[int] = None
    unit: str
    explanation: str
    source_path: str


class MobileBaselineDelta(BaseModel):
    metric: str
    label: str
    unit: str
    current: Optional[float] = None
    baseline_7d: Optional[float] = None
    baseline_14d: Optional[float] = None
    baseline_30d: Optional[float] = None
    delta_7d: Optional[float] = None
    delta_14d: Optional[float] = None
    delta_30d: Optional[float] = None
    direction: Optional[str] = None
    sample_count_7d: int = 0
    sample_count_14d: int = 0
    sample_count_30d: int = 0
    preferred: Optional[str] = None


class MobileActionEvidence(BaseModel):
    metric: str
    value: Any = None
    day: Optional[str] = None
    source_path: str


class MobileActionCard(BaseModel):
    id: str
    day: str
    severity: str
    category: str
    title: str
    reason: str
    recommendation: str
    evidence: List[MobileActionEvidence] = Field(default_factory=list)
    dismissible: bool = True


class MobileDailyGuidance(BaseModel):
    day: str
    headline: str
    body: List[str] = Field(default_factory=list)
    citations: List[Dict[str, Any]] = Field(default_factory=list)


class MobileSyncFreshness(BaseModel):
    latest_day: Optional[str] = None
    expected_latest_day: Optional[str] = None
    last_ingest_at: Optional[str] = None
    last_export_request_at: Optional[str] = None
    status: str
    message: Optional[str] = None
    mobile_server_enabled: bool = False
    mobile_server_status: Optional[str] = None
    automation_status: Optional[str] = None
    next_run: Optional[str] = None
    days_behind: Optional[int] = None


class MobileTodayInsights(BaseModel):
    day: Optional[date] = None
    contributors_sleep: List[MobileContributorSummary] = Field(default_factory=list)
    contributors_readiness: List[MobileContributorSummary] = Field(default_factory=list)
    contributors_activity: List[MobileContributorSummary] = Field(default_factory=list)
    baselines: List[MobileBaselineDelta] = Field(default_factory=list)
    action_cards: List[MobileActionCard] = Field(default_factory=list)
    guidance: Optional[MobileDailyGuidance] = None


class MobileRingBattery(BaseModel):
    level: int
    charging: bool
    in_charger: bool
    timestamp: datetime


class MobileSyncResponse(BaseModel):
    generated_at: datetime
    latest_day: Optional[date] = None
    window_days: int
    available_start_day: Optional[date] = None
    days: List[MobileDailySummaryResponse]
    workouts: List[MobileWorkoutResponse]
    today_insights: Optional[MobileTodayInsights] = None
    sync_freshness: Optional[MobileSyncFreshness] = None
    ring_battery: Optional[MobileRingBattery] = None


def _latest_ring_battery(db: Session) -> Optional[MobileRingBattery]:
    row = db.query(RingBattery).order_by(RingBattery.timestamp.desc()).first()
    if row is None:
        return None
    return MobileRingBattery(
        level=row.level,
        charging=row.charging,
        in_charger=row.in_charger,
        timestamp=row.timestamp,
    )


def _device_tokens() -> Dict[str, str]:
    """Named per-device tokens: OURACLE_MOBILE_TOKENS="ios-keith:abc,tv:xyz".

    Each device gets its own revocable credential; remove one entry and only
    that device loses access.
    """
    tokens: Dict[str, str] = {}
    for part in os.environ.get("OURACLE_MOBILE_TOKENS", "").split(","):
        name, sep, value = part.strip().partition(":")
        if sep and name.strip() and value.strip():
            tokens[name.strip()] = value.strip()
    return tokens


def _mobile_settings() -> Dict[str, Any]:
    config = config_manager.get_config()

    # Headless/container deployments seed auth via environment instead of the
    # desktop settings UI. Env vars take precedence over the config file.
    env_token = os.environ.get("OURACLE_MOBILE_TOKEN", "").strip()
    env_enabled = os.environ.get("OURACLE_MOBILE_ENABLED", "").strip().lower()
    device_tokens = _device_tokens()

    enabled = bool(config.get("mobile_sync_enabled", False))
    if env_enabled in ("1", "true", "yes", "on"):
        enabled = True
    elif env_enabled in ("0", "false", "no", "off"):
        enabled = False
    elif env_token or device_tokens:
        # A token provided via env implies the operator wants the API on.
        enabled = True

    return {
        "enabled": enabled,
        "device_tokens": device_tokens,
        "token": env_token or config.get("mobile_sync_token", "") or "",
        "default_window_days": int(
            config.get("mobile_sync_default_window_days", DEFAULT_WINDOW_DAYS)
        ),
        "bind_host": config.get("mobile_sync_bind_host", DEFAULT_BIND_HOST)
        or DEFAULT_BIND_HOST,
        "port": int(config.get("mobile_sync_port", DEFAULT_PORT)),
    }


def _generate_token() -> str:
    return secrets.token_urlsafe(24)


def _parse_token(authorization: Optional[str], sync_token: Optional[str]) -> Optional[str]:
    if sync_token:
        return sync_token.strip()

    if not authorization:
        return None

    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer" or not value:
        return None

    return value.strip()


def _parse_json_value(value: Any) -> Any:
    if value is None or isinstance(value, (dict, list)):
        return value

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() == "null":
            return None
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return value

    return value


def _latest_day(db: Session) -> Optional[date]:
    candidates = [
        db.query(Sleep.day).order_by(Sleep.day.desc()).limit(1).scalar(),
        db.query(Activity.day).order_by(Activity.day.desc()).limit(1).scalar(),
        db.query(Readiness.day).order_by(Readiness.day.desc()).limit(1).scalar(),
        db.query(SleepSession.day).order_by(SleepSession.day.desc()).limit(1).scalar(),
    ]
    valid_dates = [candidate for candidate in candidates if candidate is not None]
    return max(valid_dates) if valid_dates else None


def _build_run_command(bind_host: str, port: int) -> str:
    return f"Managed automatically by the desktop app on {bind_host}:{port}"


def _validate_bind_host(bind_host: str) -> str:
    host = bind_host.strip()
    if not host:
        raise HTTPException(status_code=422, detail="Bind host cannot be empty.")

    if host.lower() == "localhost":
        return "127.0.0.1"

    if host == "0.0.0.0":
        return host

    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass

    raise HTTPException(
        status_code=422,
        detail="Bind host must be 0.0.0.0, localhost, or an IP address.",
    )


def _select_primary_sessions(
    sessions: List[SleepSession],
) -> Dict[date, SleepSession]:
    primary_by_day: Dict[date, SleepSession] = {}

    for session in sessions:
        current = primary_by_day.get(session.day)
        if current is None:
            primary_by_day[session.day] = session
            continue

        current_duration = current.total_sleep_duration or 0
        session_duration = session.total_sleep_duration or 0

        if session_duration > current_duration:
            primary_by_day[session.day] = session

    return primary_by_day


def _build_session_aggregates(
    sessions: List[SleepSession],
) -> Dict[date, Dict[str, int]]:
    aggregates: Dict[date, Dict[str, int]] = {}

    for session in sessions:
        bucket = aggregates.setdefault(
            session.day,
            {
                "total_sleep_duration_all_sessions": 0,
                "nap_sleep_duration": 0,
                "sleep_session_count": 0,
            },
        )

        duration = session.total_sleep_duration or 0
        bucket["total_sleep_duration_all_sessions"] += duration
        bucket["sleep_session_count"] += 1

        if (session.type or "").lower() in {"nap", "short_sleep"}:
            bucket["nap_sleep_duration"] += duration

    return aggregates


def _require_mobile_token(
    authorization: Optional[str] = Header(default=None),
    x_cracked_oura_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    settings = _mobile_settings()

    valid_tokens = dict(settings["device_tokens"])
    if settings["token"]:
        valid_tokens.setdefault("shared", settings["token"])

    if not settings["enabled"] or not valid_tokens:
        raise HTTPException(
            status_code=503,
            detail="Mobile sync is not enabled. Configure a sync token on the desktop app first.",
        )

    provided_token = _parse_token(authorization, x_cracked_oura_token)
    matched = None
    if provided_token:
        for name, token in valid_tokens.items():
            if secrets.compare_digest(provided_token, token):
                matched = name
                break
    if matched is None:
        raise HTTPException(status_code=401, detail="Invalid mobile sync token.")

    logger.debug("Mobile API request authenticated as device %r", matched)
    return settings


def _build_sync_response(db: Session, window_days: int) -> MobileSyncResponse:
    latest_day = _latest_day(db)
    if latest_day is None:
        return MobileSyncResponse(
            generated_at=datetime.now(timezone.utc),
            latest_day=None,
            window_days=window_days,
            available_start_day=None,
            days=[],
            workouts=[],
            ring_battery=_latest_ring_battery(db),
        )

    start_day = latest_day - timedelta(days=window_days - 1)

    sleep_rows = {
        row.day: row
        for row in db.query(Sleep).filter(Sleep.day >= start_day).all()
    }
    activity_rows = {
        row.day: row
        for row in db.query(Activity).filter(Activity.day >= start_day).all()
    }
    readiness_rows = {
        row.day: row
        for row in db.query(Readiness).filter(Readiness.day >= start_day).all()
    }
    resilience_rows = {
        row.day: row
        for row in db.query(Resilience).filter(Resilience.day >= start_day).all()
    }
    cardiovascular_rows = {
        row.day: row
        for row in db.query(CardiovascularAge)
        .filter(CardiovascularAge.day >= start_day)
        .all()
    }

    session_rows = (
        db.query(SleepSession)
        .filter(SleepSession.day >= start_day)
        .filter(SleepSession.type.in_(["long_sleep", "sleep", "nap", "short_sleep"]))
        .all()
    )
    primary_sessions = _select_primary_sessions(session_rows)
    session_aggregates = _build_session_aggregates(session_rows)

    workout_rows = (
        db.query(Workout)
        .filter(Workout.day >= start_day)
        .order_by(Workout.day.desc(), Workout.start_time.desc())
        .all()
    )

    all_days = sorted(
        {
            *sleep_rows.keys(),
            *activity_rows.keys(),
            *readiness_rows.keys(),
            *resilience_rows.keys(),
            *cardiovascular_rows.keys(),
            *primary_sessions.keys(),
        },
        reverse=True,
    )

    day_summaries: List[MobileDailySummaryResponse] = []
    for day_value in all_days:
        sleep = sleep_rows.get(day_value)
        activity = activity_rows.get(day_value)
        readiness = readiness_rows.get(day_value)
        resilience = resilience_rows.get(day_value)
        cardiovascular = cardiovascular_rows.get(day_value)
        session = primary_sessions.get(day_value)
        session_totals = session_aggregates.get(day_value, {})

        day_summaries.append(
            MobileDailySummaryResponse(
                day=day_value,
                sleep_score=sleep.score if sleep else None,
                sleep_contributors=_parse_json_value(sleep.contributors) if sleep else None,
                sleep_status=sleep.status if sleep else None,
                sleep_recommendation=sleep.recommendation if sleep else None,
                average_spo2=sleep.average_spo2 if sleep else None,
                breathing_disturbance_index=sleep.breathing_disturbance_index
                if sleep
                else None,
                activity_score=activity.score if activity else None,
                steps=activity.steps if activity else None,
                total_calories=activity.total_calories if activity else None,
                active_calories=activity.active_calories if activity else None,
                average_met=activity.average_met if activity else None,
                equivalent_walking_distance=activity.equivalent_walking_distance
                if activity
                else None,
                target_calories=activity.target_calories if activity else None,
                target_meters=activity.target_meters if activity else None,
                meters_to_target=activity.meters_to_target if activity else None,
                inactivity_alerts=activity.inactivity_alerts if activity else None,
                resting_time=activity.resting_time if activity else None,
                sedentary_time=activity.sedentary_time if activity else None,
                low_activity_time=activity.low_activity_time if activity else None,
                medium_activity_time=activity.medium_activity_time if activity else None,
                high_activity_time=activity.high_activity_time if activity else None,
                activity_contributors=_parse_json_value(activity.contributors)
                if activity
                else None,
                readiness_score=readiness.score if readiness else None,
                readiness_contributors=_parse_json_value(readiness.contributors)
                if readiness
                else None,
                temperature_deviation=readiness.temperature_deviation
                if readiness
                else None,
                temperature_trend_deviation=readiness.temperature_trend_deviation
                if readiness
                else None,
                stress_high=readiness.stress_high if readiness else None,
                recovery_high=readiness.recovery_high if readiness else None,
                day_summary=readiness.day_summary if readiness else None,
                resilience_level=resilience.level if resilience else None,
                resilience_sleep_recovery=resilience.sleep_recovery
                if resilience
                else None,
                resilience_daytime_recovery=resilience.daytime_recovery
                if resilience
                else None,
                resilience_stress=resilience.stress if resilience else None,
                vascular_age=cardiovascular.vascular_age if cardiovascular else None,
                sleep_type=session.type if session else None,
                sleep_start_time=session.start_time if session else None,
                sleep_end_time=session.end_time if session else None,
                bedtime_start=session.bedtime_start if session else None,
                bedtime_end=session.bedtime_end if session else None,
                sleep_efficiency=session.efficiency if session else None,
                total_sleep_duration=session.total_sleep_duration if session else None,
                deep_sleep_duration=session.deep_sleep_duration if session else None,
                rem_sleep_duration=session.rem_sleep_duration if session else None,
                light_sleep_duration=session.light_sleep_duration if session else None,
                awake_time=session.awake_time if session else None,
                average_heart_rate=session.average_heart_rate if session else None,
                average_hrv=session.average_hrv if session else None,
                lowest_heart_rate=session.lowest_heart_rate if session else None,
                readiness_score_delta=session.readiness_score_delta if session else None,
                sleep_score_delta=session.sleep_score_delta if session else None,
                time_in_bed=session.time_in_bed if session else None,
                total_sleep_duration_all_sessions=session_totals.get(
                    "total_sleep_duration_all_sessions"
                ),
                nap_sleep_duration=session_totals.get("nap_sleep_duration"),
                sleep_session_count=session_totals.get("sleep_session_count"),
            )
        )

    workouts = [
        MobileWorkoutResponse(
            id=row.id,
            day=row.day,
            start_time=row.start_time,
            end_time=row.end_time,
            activity=row.activity,
            calories=row.calories,
            distance=row.distance,
            intensity=row.intensity,
            label=row.label,
            source=row.source,
        )
        for row in workout_rows
    ]

    available_start_day = all_days[-1] if all_days else None

    today_insights = _build_today_insights(db, latest_day)
    sync_freshness = _build_mobile_sync_freshness(db)

    return MobileSyncResponse(
        generated_at=datetime.now(timezone.utc),
        latest_day=latest_day,
        window_days=window_days,
        available_start_day=available_start_day,
        days=day_summaries,
        workouts=workouts,
        today_insights=today_insights,
        sync_freshness=sync_freshness,
        ring_battery=_latest_ring_battery(db),
    )


def _build_today_insights(db: Session, day: Optional[date]) -> Optional[MobileTodayInsights]:
    if day is None:
        return None
    sleep = db.query(Sleep).filter(Sleep.day == day).one_or_none()
    readiness = db.query(Readiness).filter(Readiness.day == day).one_or_none()
    activity = db.query(Activity).filter(Activity.day == day).one_or_none()

    contributors_sleep = [
        MobileContributorSummary(**c.to_dict())
        for c in build_contributor_summaries("sleep", sleep.contributors if sleep else None)
    ]
    contributors_readiness = [
        MobileContributorSummary(**c.to_dict())
        for c in build_contributor_summaries("readiness", readiness.contributors if readiness else None)
    ]
    contributors_activity = [
        MobileContributorSummary(**c.to_dict())
        for c in build_contributor_summaries("activity", activity.contributors if activity else None)
    ]
    baselines = [MobileBaselineDelta(**d.to_dict()) for d in build_baseline_bundle(db, day).deltas]
    action_cards = [MobileActionCard(**c.to_dict()) for c in build_action_cards(db, day)]
    guidance = MobileDailyGuidance(**build_daily_guidance(db, day).to_dict())

    return MobileTodayInsights(
        day=day,
        contributors_sleep=contributors_sleep,
        contributors_readiness=contributors_readiness,
        contributors_activity=contributors_activity,
        baselines=baselines,
        action_cards=action_cards,
        guidance=guidance,
    )


def _build_mobile_sync_freshness(db: Session) -> MobileSyncFreshness:
    """Report desktop ingest/sync state for the phone without starting Oura automation."""
    if os.environ.get("OURACLE_MOBILE_API_ONLY") == "1":
        fresh = build_sync_freshness(db, mobile_server_state=None)
        payload = fresh.to_dict()
        cfg = config_manager.get_config()
        payload["mobile_server_enabled"] = bool(cfg.get("mobile_sync_enabled", False))
        payload["mobile_server_status"] = "Read-only LAN API"
        return MobileSyncFreshness(**payload)

    state = mobile_server_manager.reconcile()
    fresh = build_sync_freshness(db, state)
    return MobileSyncFreshness(**fresh.to_dict())


@mobile_admin_router.get("/api/mobile/settings", response_model=MobileSettingsResponse)
def get_mobile_settings(db: Session = Depends(get_db)):
    settings = _mobile_settings()
    latest_day = _latest_day(db)
    server_state = mobile_server_manager.reconcile()
    return MobileSettingsResponse(
        enabled=settings["enabled"],
        token=settings["token"],
        default_window_days=settings["default_window_days"],
        bind_host=settings["bind_host"],
        port=settings["port"],
        latest_day=latest_day,
        has_data=latest_day is not None,
        run_command=_build_run_command(settings["bind_host"], settings["port"]),
        server_running=server_state.running,
        server_status=server_state.status,
    )


@mobile_admin_router.post("/api/mobile/settings", response_model=MobileSettingsResponse)
def update_mobile_settings(
    request: MobileSettingsUpdate, db: Session = Depends(get_db)
):
    settings = _mobile_settings()
    updates: Dict[str, Any] = {}

    if request.enabled is not None:
        updates["mobile_sync_enabled"] = request.enabled

    if request.default_window_days is not None:
        updates["mobile_sync_default_window_days"] = request.default_window_days

    if request.bind_host is not None:
        updates["mobile_sync_bind_host"] = _validate_bind_host(request.bind_host)

    if request.port is not None:
        updates["mobile_sync_port"] = request.port

    if request.token is not None:
        normalized_token = request.token.strip()
        if normalized_token:
            updates["mobile_sync_token"] = normalized_token
        elif not settings["token"]:
            updates["mobile_sync_token"] = _generate_token()

    if request.regenerate_token:
        updates["mobile_sync_token"] = _generate_token()
    elif not settings["token"] and "mobile_sync_token" not in updates:
        updates["mobile_sync_token"] = _generate_token()

    if updates:
        config_manager.update_config(**updates)
        mobile_server_manager.reconcile()

    return get_mobile_settings(db)


class MobileSleepSessionDetail(BaseModel):
    """Full per-session sleep detail for the day view: stage sequence plus
    overnight HR/HRV series (``{interval, items, timestamp}`` dicts)."""

    id: str
    day: date
    type: Optional[str] = None
    bedtime_start: Optional[datetime] = None
    bedtime_end: Optional[datetime] = None
    efficiency: Optional[int] = None
    latency: Optional[int] = None
    total_sleep_duration: Optional[int] = None
    deep_sleep_duration: Optional[int] = None
    rem_sleep_duration: Optional[int] = None
    light_sleep_duration: Optional[int] = None
    awake_time: Optional[int] = None
    time_in_bed: Optional[int] = None
    average_heart_rate: Optional[float] = None
    average_hrv: Optional[int] = None
    lowest_heart_rate: Optional[int] = None
    average_breath: Optional[float] = None
    restless_periods: Optional[int] = None
    sleep_phase_5_min: Optional[str] = None
    hr_data: Optional[Dict[str, Any]] = None
    hrv_data: Optional[Dict[str, Any]] = None


@mobile_client_router.get(
    "/api/mobile/sleep/{day}", response_model=List[MobileSleepSessionDetail]
)
def mobile_sleep_sessions(
    day: date,
    _: Dict[str, Any] = Depends(_require_mobile_token),
    db: Session = Depends(get_db),
):
    sessions = (
        db.query(SleepSession)
        .filter(SleepSession.day == day)
        .order_by(SleepSession.bedtime_start)
        .all()
    )
    return [
        MobileSleepSessionDetail(
            id=s.id,
            day=s.day,
            type=s.type,
            bedtime_start=s.bedtime_start,
            bedtime_end=s.bedtime_end,
            efficiency=s.efficiency,
            latency=s.latency,
            total_sleep_duration=s.total_sleep_duration,
            deep_sleep_duration=s.deep_sleep_duration,
            rem_sleep_duration=s.rem_sleep_duration,
            light_sleep_duration=s.light_sleep_duration,
            awake_time=s.awake_time,
            time_in_bed=s.time_in_bed,
            average_heart_rate=s.average_heart_rate,
            average_hrv=s.average_hrv,
            lowest_heart_rate=s.lowest_heart_rate,
            average_breath=s.average_breath,
            restless_periods=s.restless_periods,
            sleep_phase_5_min=(
                s.sleep_phase_5_min
                if isinstance(s.sleep_phase_5_min, str)
                else None
            ),
            hr_data=s.hr_data if isinstance(s.hr_data, dict) else None,
            hrv_data=s.hrv_data if isinstance(s.hrv_data, dict) else None,
        )
        for s in sessions
    ]


RING_CURSOR_KEY = "ring_events:cursor"
RING_ATTEMPT_KEY = "ring_events:last_attempt"
RING_ADDED_KEY = "ring_events:last_added"


class RingEventUpload(BaseModel):
    tag: int = Field(ge=0, le=255)
    timestamp: int = Field(ge=0)
    body: str = Field(default="", max_length=2048)  # hex


class RingEventBatch(BaseModel):
    events: List[RingEventUpload] = Field(default_factory=list)
    next_cursor: Optional[int] = None
    # Reported even for empty/failed attempts, so background sync is
    # observable rather than silently doing nothing.
    status: Optional[str] = Field(default=None, max_length=200)


class RingSyncState(BaseModel):
    cursor: int
    stored_events: int
    latest_event_at: Optional[int] = None
    last_attempt_at: Optional[datetime] = None
    last_status: Optional[str] = None
    last_added: Optional[int] = None


@mobile_client_router.get("/api/mobile/ring-events/state", response_model=RingSyncState)
def ring_sync_state(
    _: Dict[str, Any] = Depends(_require_mobile_token),
    db: Session = Depends(get_db),
):
    """Where to resume the ring's history drain."""
    from ..models import IngestState, RingEventRaw

    row = db.get(IngestState, RING_CURSOR_KEY)
    newest = db.query(RingEventRaw).order_by(RingEventRaw.timestamp.desc()).first()
    attempt = db.get(IngestState, RING_ATTEMPT_KEY)
    added = db.get(IngestState, RING_ADDED_KEY)
    return RingSyncState(
        cursor=int(row.value) if row and row.value else 0,
        stored_events=db.query(RingEventRaw).count(),
        latest_event_at=newest.timestamp if newest else None,
        last_attempt_at=attempt.updated_at if attempt else None,
        last_status=attempt.value if attempt else None,
        last_added=int(added.value) if added and added.value else None,
    )


@mobile_client_router.post("/api/mobile/ring-events", response_model=RingSyncState)
def upload_ring_events(
    batch: RingEventBatch,
    _: Dict[str, Any] = Depends(_require_mobile_token),
    db: Session = Depends(get_db),
):
    """Accepts raw history-event frames drained from the ring by the phone."""
    from ..models import IngestState, RingEventRaw

    for event in batch.events:
        key = f"{event.tag:02x}-{event.timestamp}"
        db.merge(
            RingEventRaw(
                id=key,
                tag=event.tag,
                timestamp=event.timestamp,
                body=event.body.lower(),
                received_at=datetime.now(timezone.utc).replace(tzinfo=None),
            )
        )

    if batch.next_cursor is not None:
        row = db.get(IngestState, RING_CURSOR_KEY)
        if row is None:
            row = IngestState(key=RING_CURSOR_KEY)
            db.add(row)
        # Never move the bookmark backwards.
        current = int(row.value) if row.value else 0
        row.value = str(max(current, batch.next_cursor))
        row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    _record_state(db, RING_ATTEMPT_KEY, batch.status or "ok")
    _record_state(db, RING_ADDED_KEY, str(len(batch.events)))

    db.commit()
    return ring_sync_state(_, db)


def _record_state(db: Session, key: str, value: str) -> None:
    from ..models import IngestState

    row = db.get(IngestState, key)
    if row is None:
        row = IngestState(key=key)
        db.add(row)
    row.value = value
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)


class RingNightPoint(BaseModel):
    t: datetime
    value: float


class RingNightResponse(BaseModel):
    """A night reconstructed purely from events read off the ring."""

    start: datetime
    end: datetime
    heart_rate: List[RingNightPoint] = Field(default_factory=list)
    movement: List[RingNightPoint] = Field(default_factory=list)
    temperature: List[RingNightPoint] = Field(default_factory=list)
    beats: int = 0
    lowest_hr: Optional[int] = None
    average_hr: Optional[int] = None
    event_count: int = 0
    detected_bedtimes: List[Dict[str, Any]] = Field(default_factory=list)
    coverage: Optional[Dict[str, Any]] = None
    # Locally derived; see ring_events.staging for the method and its limits.
    stages: List[Dict[str, Any]] = Field(default_factory=list)
    stage_summary: Optional[Dict[str, Any]] = None


@mobile_client_router.get("/api/mobile/ring-night/{day}", response_model=RingNightResponse)
def ring_night(
    day: date,
    _: Dict[str, Any] = Depends(_require_mobile_token),
    db: Session = Depends(get_db),
):
    """Ring-derived night for `day`, spanning the previous evening to midday.

    Uses the sleep session's own window when the cloud has scored the night,
    falling back to a fixed 18:00→12:00 window otherwise, so this works even
    when Oura has produced nothing.
    """
    from ..ring_events.night import build_night, coverage, detected_bedtimes

    session = (
        db.query(SleepSession)
        .filter(SleepSession.day == day)
        .order_by(SleepSession.total_sleep_duration.desc())
        .first()
    )
    if session and session.bedtime_start and session.bedtime_end:
        start, end = session.bedtime_start, session.bedtime_end
    else:
        start = datetime.combine(day - timedelta(days=1), time(18, 0))
        end = datetime.combine(day, time(12, 0))

    from ..ring_events.staging import build_epochs, stage_epochs, summarise

    night = build_night(db, start, end)
    night["detected_bedtimes"] = detected_bedtimes(db)
    night["coverage"] = coverage(db)

    # Stages are derived here, not read from the ring: it streams the inputs
    # but finishes staging elsewhere.
    epochs = build_epochs(
        night.get("heart_rate", []),
        night.get("movement", []),
        night.pop("hrv", {}),
        movement_peak=night.get("movement_peak", []),
        temperature=night.get("temperature", []),
        ibi_features=night.pop("ibi_features", {}),
    )
    staged = stage_epochs(epochs)
    night["stages"] = staged
    night["stage_summary"] = summarise(staged) if staged else None
    return RingNightResponse(**night)


class PushTokenRequest(BaseModel):
    token: str = Field(min_length=16, max_length=200)
    device_name: str = Field(default="iPhone", max_length=64)


@mobile_client_router.post("/api/mobile/push-token")
def register_push_token(
    request: PushTokenRequest,
    _: Dict[str, Any] = Depends(_require_mobile_token),
    db: Session = Depends(get_db),
):
    """Registers an APNs device token for wake reports and alerts."""
    from ..models import IngestState
    from ..notify import DEVICE_TOKEN_PREFIX

    key = DEVICE_TOKEN_PREFIX + request.token.strip().lower()
    row = db.get(IngestState, key)
    if row is None:
        row = IngestState(key=key)
        db.add(row)
    row.value = request.device_name
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.commit()
    return {"status": "registered", "device_name": request.device_name}


@mobile_client_router.get("/api/mobile/ping", response_model=MobileServerStatusResponse)
def mobile_ping(
    _: Dict[str, Any] = Depends(_require_mobile_token),
    db: Session = Depends(get_db),
):
    settings = _mobile_settings()
    return MobileServerStatusResponse(
        status="ok",
        generated_at=datetime.now(timezone.utc),
        latest_day=_latest_day(db),
        default_window_days=settings["default_window_days"],
        server_version="1",
    )


@mobile_client_router.get("/api/mobile/sync", response_model=MobileSyncResponse)
def mobile_sync(
    window_days: Optional[int] = Query(default=None, ge=7, le=730),
    _: Dict[str, Any] = Depends(_require_mobile_token),
    db: Session = Depends(get_db),
):
    settings = _mobile_settings()
    requested_window = window_days or settings["default_window_days"]
    try:
        return _build_sync_response(db, requested_window)
    except Exception as exc:
        logger.exception("Mobile sync failed")
        raise HTTPException(status_code=500, detail=f"Sync failed: {exc}")


@mobile_client_router.get("/api/mobile/insights/{day}", response_model=MobileTodayInsights)
def mobile_insights_for_day(
    day: date,
    _: Dict[str, Any] = Depends(_require_mobile_token),
    db: Session = Depends(get_db),
):
    try:
        insights = _build_today_insights(db, day)
    except Exception as exc:
        logger.exception("Mobile per-day insights failed day=%s", day)
        raise HTTPException(status_code=500, detail=f"Insights failed: {exc}")

    if insights is None:
        return MobileTodayInsights(day=day)
    return insights
