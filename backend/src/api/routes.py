
import logging
import os
import shutil
import tempfile
import json
import traceback
from typing import List, Optional, Any
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select, func

# Constants and Configuration
from ..config import config_manager
from ..database import get_db, SessionLocal
from ..ingestion.runner import ingest_zip_async
from ..sync_recovery import PROCESSING_STATUSES, recover_stuck_sync_if_needed
from ..models import (
    Sleep, Activity, Readiness, Resilience, SleepSession, Workout, Meditation, 
    RingBattery, HeartRate, Temperature, RingConfiguration, Tag, CardiovascularAge,
    ChatThread, ChatMessage
)
from .schemas import (
    DayDataResponse,
    SleepResponse, ActivityResponse, ReadinessResponse,
    SleepSessionResponse, WorkoutResponse, HeartRateResponse, 
    ResilienceResponse, TemperatureResponse, MeditationResponse
)
from ..ingestion import OuraParser
from ..automation import automator
from ..llm import DataAnalyst

# Logging
logger = logging.getLogger("API")

# Router Initialization
router = APIRouter()

# ─── Shared Model Registry ───
MODEL_MAP = {
    "sleep": Sleep,
    "activity": Activity,
    "readiness": Readiness,
    "resilience": Resilience,
    "cardiovascular_age": CardiovascularAge,
    "sleep_session": SleepSession,
    "workout": Workout,
    "meditation": Meditation,
    "ring_battery": RingBattery,
    "heart_rate": HeartRate,
    "temperature": Temperature,
    "ring_configuration": RingConfiguration,
    "tag": Tag,
}

# -----------------------------------------------------------------------------
# Data Models and request/response schemas
# -----------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    thread_id: Optional[str] = None

class CreateThreadRequest(BaseModel):
    title: Optional[str] = None

class LoginRequest(BaseModel):
    email: str

class SettingsRequest(BaseModel):
    daily_sync_time: str
    email: Optional[str] = None
    llm_model: Optional[str] = None
    llm_host: Optional[str] = None
    llm_api_key: Optional[str] = None

class Dashboard(BaseModel):
    id: str
    name: str
    widgets: List[Any]
    layout: List[Any]

class DashboardConfigRequest(BaseModel):
    dashboards: Optional[List[Dashboard]] = None
    activeDashboardId: Optional[str] = None
    layout: Optional[List[Any]] = None
    widgets: Optional[List[Any]] = None

class IngestRequest(BaseModel):
    file_path: str


def _coerce_downloaded_zip_path(result: Any) -> str:
    if isinstance(result, str) and result:
        return result

    if isinstance(result, dict):
        status = result.get("status")
        if status == "otp_required":
            raise HTTPException(
                status_code=409,
                detail="OTP required before download can continue. Complete login again in Settings.",
            )
        message = result.get("message") or "Download did not return a ZIP file."
        raise HTTPException(status_code=500, detail=f"Download failed: {message}")

    raise HTTPException(
        status_code=500,
        detail="Download failed: no ZIP file was returned from Oura.",
    )

# -----------------------------------------------------------------------------
# Background Tasks
# -----------------------------------------------------------------------------

async def run_full_sync_task(db_session_factory):
    """
    Executes the full synchronization process:
    1. Request export from Oura Cloud (via playwright).
    2. Wait for export generation.
    3. Download the export zip.
    4. Ingest data into the local SQLite database.
    """
    del db_session_factory  # ingest opens its own DB session off the event loop
    config_manager.update_status("Processing", message="Starting full sync...")
    waiting_for_otp = False
    need_fresh_export = False
    try:
        cfg = config_manager.get_config()
        if automator._is_initialized:
            try:
                await automator.cleanup()
            except Exception as exc:
                logger.warning("Full sync: cleanup before start failed: %s", exc)
        await automator.initialize(headless=cfg.get("headless", True))
        automator.email = cfg.get("email", "")

        with tempfile.TemporaryDirectory() as temp_dir:
            # If Oura already emailed that the export is ready, download it first.
            config_manager.update_status(
                "Processing",
                message="Checking for a ready export on Oura...",
            )
            result = await automator.download_existing_export(temp_dir)

            if isinstance(result, str) and result:
                zip_path = result
                config_manager.update_status(
                    "Processing",
                    message=(
                        "Downloaded an existing Oura export from your account "
                        "(not necessarily from a new email). Ingesting…"
                    ),
                )
                logger.info("Full sync: Downloaded existing export to %s", zip_path)
                advanced = await ingest_zip_async(zip_path)
                if advanced:
                    return
                logger.info(
                    "Full sync: existing export did not add new days; "
                    "requesting a fresh export from Oura."
                )
                config_manager.update_status(
                    "Processing",
                    message=(
                        "The export on Oura was outdated (no new days). "
                        "Requesting a fresh export from Oura…"
                    ),
                )
                try:
                    await automator.cleanup()
                except Exception as exc:
                    logger.warning("Full sync: cleanup before fresh export failed: %s", exc)
                await automator.initialize(headless=cfg.get("headless", True))
                automator.email = cfg.get("email", "")
                need_fresh_export = True

            elif isinstance(result, dict):
                if result.get("status") == "otp_required":
                    waiting_for_otp = True
                    from backend.src.otp_state import mark_otp_requested, otp_prompt_message

                    if result.get("code_sent"):
                        mark_otp_requested()
                    cfg = config_manager.get_config()
                    config_manager.update_status(
                        "otp_needed",
                        message=otp_prompt_message(cfg, "Check your email for a verification code."),
                    )
                    logger.warning("Full sync paused: OTP required.")
                    return
                if result.get("status") == "error":
                    logger.warning("Full sync: no ready export yet: %s", result.get("message"))
                    need_fresh_export = True
            else:
                logger.info("Full sync: no existing export file to download.")
                need_fresh_export = True

            if not need_fresh_export:
                return

            config_manager.update_status(
                "Processing",
                message="Requesting and waiting for export (this may take hours)...",
            )
            config_manager.update_config(
                last_export_request_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            )

            result = await automator.request_new_export_and_download(
                temp_dir,
                skip_ready_download=True,
            )

            # Handle OTP requirement — keep session alive so user can submit code
            if isinstance(result, dict) and result.get("status") == "otp_required":
                waiting_for_otp = True
                from backend.src.otp_state import mark_otp_requested, otp_prompt_message

                if result.get("code_sent"):
                    mark_otp_requested()
                cfg = config_manager.get_config()
                config_manager.update_status(
                    "otp_needed",
                    message=otp_prompt_message(cfg, "Check your email for a verification code."),
                )
                logger.warning("Full sync paused: OTP required. Waiting for user to submit code.")
                return

            zip_path = result
            
            # Process successfully downloaded file
            if zip_path and isinstance(zip_path, str):
                config_manager.update_status("Processing", message=f"Downloaded to {zip_path}. Ingesting...")
                logger.info("Full sync: Downloaded to %s. Ingesting...", zip_path)
                config_manager.update_status(
                    "Processing",
                    message=(
                        "Downloaded an existing Oura export from your account "
                        "(not necessarily from a new email). Ingesting…"
                    ),
                )
                await ingest_zip_async(zip_path)
                logger.info("Full sync: Ingestion complete.")
            elif isinstance(result, dict) and result.get("status") == "error":
                logger.error("Full sync failed: %s", result.get("message"))
                config_manager.update_status("Error", message=result.get("message", "Sync failed"))
            else:
                detail = repr(result) if result is not None else "no response from Oura automation"
                logger.error("Full sync failed: No file downloaded (%s).", detail)
                config_manager.update_status(
                    "Error",
                    message=(
                        "No file downloaded from Oura. If you received an export email, "
                        "wait a minute and try Sync now again. Otherwise check that you are "
                        "still logged in under Settings → Connection."
                    ),
                )
                
    except Exception as e:
        logger.error(f"Full sync task error: {e}")
        config_manager.update_status("Error", message=f"Sync failed: {e}")
    finally:
        if not waiting_for_otp:
            await automator.cleanup()

# -----------------------------------------------------------------------------
# Chat / Advisor Endpoints
# -----------------------------------------------------------------------------

# -----------------------------------------------------------------------------
# Chat / Advisor Endpoints
# -----------------------------------------------------------------------------

@router.post("/api/chat/threads")
async def create_thread(req: CreateThreadRequest, db: Session = Depends(get_db)):
    import secrets
    thread_id = secrets.token_urlsafe(12)
    title = req.title or "New conversation"
    db_thread = ChatThread(id=thread_id, title=title)
    db.add(db_thread)
    db.commit()
    db.refresh(db_thread)
    return {
        "id": db_thread.id,
        "title": db_thread.title,
        "created_at": db_thread.created_at.isoformat(),
        "updated_at": db_thread.updated_at.isoformat()
    }

@router.get("/api/chat/threads")
async def list_threads(
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db)
):
    result = db.execute(
        select(ChatThread)
        .order_by(ChatThread.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    threads = result.scalars().all()
    return [{
        "id": t.id,
        "title": t.title,
        "created_at": t.created_at.isoformat(),
        "updated_at": t.updated_at.isoformat()
    } for t in threads]

@router.get("/api/chat/threads/{thread_id}")
async def get_thread(thread_id: str, db: Session = Depends(get_db)):
    thread = db.get(ChatThread, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    messages = []
    for msg in thread.messages:
        messages.append({
            "role": msg.role,
            "content": msg.content,
            "thoughts": msg.thoughts,
            "created_at": msg.created_at.isoformat()
        })
        
    return {
        "id": thread.id,
        "title": thread.title,
        "created_at": thread.created_at.isoformat(),
        "updated_at": thread.updated_at.isoformat(),
        "messages": messages
    }

@router.delete("/api/chat/threads/{thread_id}")
async def delete_thread(thread_id: str, db: Session = Depends(get_db)):
    thread = db.get(ChatThread, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    db.delete(thread)
    db.commit()
    return {"message": "Thread deleted successfully"}

class AppendMessageRequest(BaseModel):
    role: str
    content: str
    thoughts: Optional[Any] = None

@router.post("/api/chat/threads/{thread_id}/messages")
async def append_message(thread_id: str, req: AppendMessageRequest, db: Session = Depends(get_db)):
    thread = db.get(ChatThread, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    db_msg = ChatMessage(
        thread_id=thread_id,
        role=req.role,
        content=req.content,
        thoughts=req.thoughts
    )
    db.add(db_msg)
    db.commit()
    return {"message": "Message appended successfully"}

@router.post("/api/advisor/chat")
async def chat(
    request: Request,
    body: ChatRequest,
    db: Session = Depends(get_db)
):
    """
    Interacts with the AI Advisor with database-backed streaming response.
    """
    try:
        logger.info(f"Incoming Chat Request.")
        
        # 1. Fetch or create thread
        thread_id = body.thread_id
        if not thread_id:
            import secrets
            thread_id = secrets.token_urlsafe(12)
            db_thread = ChatThread(id=thread_id, title="New conversation")
            db.add(db_thread)
            db.commit()
            db.refresh(db_thread)
        else:
            db_thread = db.get(ChatThread, thread_id)
            if not db_thread:
                raise HTTPException(status_code=404, detail="Thread not found")
        
        # 2. Save user message to database
        user_msg = ChatMessage(
            thread_id=thread_id,
            role="user",
            content=body.message
        )
        db.add(user_msg)
        
        # Update thread's updated_at
        db_thread.updated_at = datetime.utcnow()
        
        # If thread title is default "New conversation", rename from first message
        if db_thread.title == "New conversation" or not db_thread.title:
            cleaned = body.message.replace('\n', ' ').strip()
            db_thread.title = cleaned[:37] + "…" if len(cleaned) > 40 else cleaned
            
        db.commit()
        db.refresh(user_msg)
        
        user_msg_id = user_msg.id
        thread_title = db_thread.title

        # 3. Stream generator using separate session to avoid FastAPI dependency closure bugs
        async def event_generator():
            stream_db = SessionLocal()
            try:
                # Re-fetch thread and user message inside new session
                t_thread = stream_db.get(ChatThread, thread_id)
                u_msg = stream_db.get(ChatMessage, user_msg_id)
                if not t_thread or not u_msg:
                    yield json.dumps({"type": "error", "message": "Failed to find session records"}) + "\n"
                    return

                # Send initial thread information
                yield json.dumps({
                    "type": "thread_info",
                    "thread_id": thread_id,
                    "title": t_thread.title
                }) + "\n"

                # Build conversation history
                history_msgs = [
                    {"role": msg.role, "content": msg.content}
                    for msg in t_thread.messages
                    if msg.id != u_msg.id
                ]

                advisor = DataAnalyst()
                full_answer = ""
                all_thoughts = []

                async for chunk in advisor.chat_stream(body.message, history_msgs, request):
                    if chunk["type"] == "thought":
                        all_thoughts.append(chunk["thought"])
                        yield json.dumps(chunk) + "\n"
                    elif chunk["type"] == "token":
                        full_answer += chunk["content"]
                        yield json.dumps(chunk) + "\n"
                    elif chunk["type"] == "done":
                        if "response" in chunk:
                            full_answer = chunk["response"]
                        if "thoughts" in chunk:
                            all_thoughts = chunk["thoughts"]
                    elif chunk["type"] == "error":
                        yield json.dumps(chunk) + "\n"
                        return

                # Save assistant response to DB on successful completion
                if full_answer:
                    assistant_msg = ChatMessage(
                        thread_id=thread_id,
                        role="assistant",
                        content=full_answer,
                        thoughts=all_thoughts
                    )
                    stream_db.add(assistant_msg)
                    t_thread.updated_at = datetime.utcnow()
                    stream_db.commit()

                yield json.dumps({"type": "done", "response": full_answer, "thoughts": all_thoughts}) + "\n"

            except Exception as e:
                logger.error(f"Error in streaming event generator: {e}")
                traceback.print_exc()
                yield json.dumps({"type": "error", "message": str(e)}) + "\n"
            finally:
                stream_db.close()

        return StreamingResponse(
            event_generator(),
            media_type="application/x-ndjson"
        )
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# Automation & Authentication Endpoints
# -----------------------------------------------------------------------------

@router.post("/api/automation/start-login")
async def start_login(request: LoginRequest):
    """Initiates the login process via Playwright."""
    from backend.src.otp_state import mark_otp_requested, otp_prompt_message

    try:
        config_manager.update_config(email=request.email)
        result = await automator.start_login(request.email)
        if isinstance(result, dict) and result.get("status") == "otp_required":
            if result.get("code_sent"):
                mark_otp_requested()
            cfg = config_manager.get_config()
            config_manager.update_status(
                "otp_needed",
                message=otp_prompt_message(cfg, "Check your email for a verification code."),
                logged_in=False,
            )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/automation/resend-otp")
async def resend_otp():
    """Ask Oura to send a fresh verification email."""
    from backend.src.otp_state import otp_prompt_message

    try:
        result = await automator.resend_otp()
        if result.get("status") == "otp_required":
            refreshed = config_manager.get_config()
            config_manager.update_status(
                "otp_needed",
                message=otp_prompt_message(refreshed, result.get("message")),
                logged_in=False,
            )
            return result
        if result.get("status") == "error":
            raise HTTPException(status_code=500, detail=result.get("message", "Resend failed"))
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/automation/request-export")
async def request_export(background_tasks: BackgroundTasks):
    """
    Starts the full export -> wait -> download -> ingest process in the background.
    """
    recover_stuck_sync_if_needed()
    cfg = config_manager.get_config()
    if cfg.get("status") in PROCESSING_STATUSES:
        raise HTTPException(status_code=409, detail="Sync already in progress")
        
    background_tasks.add_task(run_full_sync_task, SessionLocal)
    return {"message": "Full sync started in background."}

@router.post("/api/automation/check-status")
async def check_status():
    """Returns the current automation status from the persistent config."""
    from backend.src.otp_state import enrich_automation_status

    return enrich_automation_status(config_manager.get_config())

@router.post("/api/automation/download")
async def download_export(db: Session = Depends(get_db)):
    """
    Attempts to download an *existing* export from Oura Cloud and ingest it.
    Does not request a new export generation.
    """
    try:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = await automator.download_existing_export(temp_dir)
            
            # Handle OTP requirement — keep session alive and surface to UI
            if isinstance(result, dict) and result.get("status") == "otp_required":
                from backend.src.otp_state import mark_otp_requested, otp_prompt_message

                if result.get("code_sent"):
                    mark_otp_requested()
                cfg = config_manager.get_config()
                config_manager.update_status(
                    "otp_needed",
                    message=otp_prompt_message(cfg, "Check your email for a verification code."),
                )
                raise HTTPException(
                    status_code=409,
                    detail="OTP required. Please enter the code below.",
                )
            
            zip_path = _coerce_downloaded_zip_path(result)

            config_manager.update_status("Processing", message="Ingesting downloaded export…")
            await ingest_zip_async(zip_path)

            return {"message": "Download and ingestion successful!"}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# NOTE: /api/automation/clear-session is defined in main.py (app-level)

# -----------------------------------------------------------------------------
# Settings Endpoints
# -----------------------------------------------------------------------------

@router.post("/api/settings")
async def save_settings(request: SettingsRequest):
    """Updates global application settings."""
    try:
        updates = {"schedule_time": request.daily_sync_time}
        if request.email is not None:
             updates["email"] = request.email
        if request.llm_model is not None:
             updates["llm_model"] = request.llm_model
        if request.llm_host is not None:
             updates["llm_host"] = request.llm_host
        if request.llm_api_key is not None:
             updates["llm_api_key"] = request.llm_api_key
             
        config_manager.update_config(**updates)
        return {"message": "Settings saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/settings")
async def get_settings():
    """Retrieves current application settings."""
    try:
        config = config_manager.get_config()
        return {
            "daily_sync_time": config.get("schedule_time", "09:00"),
            "email": config.get("email", ""),
            "llm_model": config.get("llm_model", "llama3.1:latest"),
            "llm_host": config.get("llm_host", "http://localhost:1234/v1"),
            "llm_api_key": config.get("llm_api_key", "not-needed"),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# Dashboard Configuration Endpoints
# -----------------------------------------------------------------------------

@router.get("/api/dashboard")
async def get_dashboard_config():
    """Retrieves the saved dashboard layout and widgets."""
    try:
        config = config_manager.get_config()
        return config.get("dashboard", {"dashboards": [], "activeDashboardId": None})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/api/dashboard")
async def save_dashboard_config(request: DashboardConfigRequest):
    """Saves the dashboard configuration."""
    try:
        update_data = {}
        if request.dashboards is not None:
            update_data["dashboards"] = [d.dict() for d in request.dashboards]
        if request.activeDashboardId is not None:
            update_data["activeDashboardId"] = request.activeDashboardId

        config_manager.update_config(dashboard=update_data)
        return {"message": "Dashboard saved"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# Data Access Endpoints
# -----------------------------------------------------------------------------

@router.get("/api/days/{date_str}", response_model=DayDataResponse)
async def get_day_data(
    date_str: str, 
    include_details: bool = False,
    db: Session = Depends(get_db)
):
    """
    Retrieves comprehensive data for a specific day (YYYY-MM-DD).
    Includes summary metrics and optional time-series details.
    """
    try:
        target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        
        # Fetch daily summaries
        sleep = db.query(Sleep).filter(Sleep.day == target_date).first()
        activity = db.query(Activity).filter(Activity.day == target_date).first()
        readiness = db.query(Readiness).filter(Readiness.day == target_date).first()
        resilience = db.query(Resilience).filter(Resilience.day == target_date).first()
        cv_age = db.query(CardiovascularAge).filter(CardiovascularAge.day == target_date).first()
        
        # Fetch detailed components
        sleep_sessions = db.query(SleepSession).filter(SleepSession.day == target_date).all()
        workouts = db.query(Workout).filter(Workout.day == target_date).all()
        sessions = db.query(Meditation).filter(Meditation.day == target_date).all()
        
        # Fetch Ring Battery
        start_of_day = datetime.combine(target_date, datetime.min.time())
        end_of_day = datetime.combine(target_date, datetime.max.time())
        battery = db.query(RingBattery).filter(
            RingBattery.timestamp >= start_of_day,
            RingBattery.timestamp <= end_of_day
        ).order_by(RingBattery.timestamp).all()

        response_data = {
            "date": target_date,
            "sleep": sleep,
            "activity": activity,
            "readiness": readiness,
            "resilience": resilience,
            "cardiovascular_age": cv_age,
            "ring_battery": battery,
            "sleep_sessions": sleep_sessions,
            "workouts": workouts,
            "meditation": sessions
        }

        if include_details:
            def fetch_timeseries(model):
                return db.scalars(
                    select(model)
                    .where(model.timestamp >= start_of_day)
                    .where(model.timestamp <= end_of_day)
                    .order_by(model.timestamp)
                ).all()

            response_data["heart_rate"] = fetch_timeseries(HeartRate)
            response_data["temperature"] = fetch_timeseries(Temperature)
            
        # Pydantic will validate and serialize
        return response_data

    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    except Exception as e:
        logger.error(f"Error fetching day data: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/query")
def query_data(
    path: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    db: Session = Depends(get_db)
):
    """
    Dynamic query endpoint for fetching specific metric trends over time.
    
    Path format: 
    - 'domain.field' (e.g., 'sleep.score')
    - 'domain.json_col.key' (e.g., 'sleep.contributors.deep_training')
    
    Returns: List of {date: ..., value: ...}
    """
    try:
        parts = path.split('.')
        if len(parts) < 2:
            raise HTTPException(status_code=400, detail="Invalid path format. Use 'domain.field' or 'domain.field.key'")
        
        domain = parts[0].lower()
        field = parts[1].lower()
        json_key = ".".join(parts[2:]) if len(parts) > 2 else None
        
        model_map = {
            "sleep": Sleep,
            "activity": Activity,
            "readiness": Readiness,
            "resilience": Resilience,
            "cardiovascular_age": CardiovascularAge,
            "sleep_session": SleepSession,
            "workout": Workout,
            "meditation": Meditation,
            "ring_battery": RingBattery,
            "heart_rate": HeartRate,
            "temperature": Temperature,
            "ring_configuration": RingConfiguration,
            "tag": Tag
        }
        
        model = model_map.get(domain)
        if not model:
            raise HTTPException(status_code=400, detail=f"Unknown domain: {domain}")
            
        if not hasattr(model, field):
             raise HTTPException(status_code=400, detail=f"Unknown field: {field} in {domain}")
             
        column = getattr(model, field)
        
        # Construct Value Expression
        if json_key:
            # Extract value from JSON column
            value_expr = func.json_extract(column, f'$.{json_key}')
        else:
            value_expr = column

        # Determine Date Column (Day vs Timestamp)
        if domain in ['heart_rate', 'temperature', 'ring_battery']:
            date_col = model.timestamp
        else:
            date_col = model.day if hasattr(model, 'day') else model.timestamp
        
        query = select(date_col, value_expr).order_by(date_col)
        
        # Special filtering for Sleep Sessions
        if domain == 'sleep_session':
            query = query.where(SleepSession.type.in_(['long_sleep', 'sleep']))
            query = query.order_by(date_col, SleepSession.type.desc())
        
        # Apply Date Filters
        if start_date:
            if hasattr(date_col.type, 'python_type') and date_col.type.python_type == datetime:
                 query = query.where(date_col >= datetime.combine(start_date, datetime.min.time()))
            else:
                 query = query.where(date_col >= start_date)

        if end_date:
            if hasattr(date_col.type, 'python_type') and date_col.type.python_type == datetime:
                 query = query.where(date_col <= datetime.combine(end_date, datetime.max.time()))
            else:
                 query = query.where(date_col <= end_date)
            
        results = db.execute(query).all()
        
        # Format Results
        data = []
        for row in results:
            day_val = row[0]
            val = row[1]
            
            if isinstance(day_val, datetime):
                day_val = day_val.isoformat()
            
            data.append({"date": day_val, "value": val})
            
        return data

    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Query Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/schema")
def get_schema():
    """
    Introspects the database models to return a schema definition.
    Useful for the frontend to build dynamic selectors.
    """
    
    model_map = {
        "sleep": Sleep,
        "activity": Activity,
        "readiness": Readiness,
        "resilience": Resilience,
        "cardiovascular_age": CardiovascularAge,
        "sleep_session": SleepSession,
        "workout": Workout,
        "meditation": Meditation,
        "ring_battery": RingBattery,
        "heart_rate": HeartRate,
        "temperature": Temperature,
        "ring_configuration": RingConfiguration,
        "tag": Tag
    }
    
    schema = {}
    
    try:
        for name, model in model_map.items():
            fields = []
            try:
                for col in model.__table__.columns:
                    if col.name == "id":
                        continue
                    
                    # Naive check for JSON columns
                    is_json = False
                    try:
                        type_str = str(col.type).upper()
                        is_json = 'JSON' in type_str
                    except Exception:
                        pass
                    
                    fields.append({
                        "name": col.name,
                        "type": "json" if is_json else str(col.type),
                        "is_json": is_json
                    })
            except Exception as e:
                logger.error(f"Error inspecting model {name}: {e}")
                continue # Skip model if error
                
            schema[name] = fields
        

        return schema
    except Exception as e:
        logger.error(f"Schema Critical Error: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# -----------------------------------------------------------------------------
# Data Ingestion Endpoints (Uploads)
# -----------------------------------------------------------------------------

@router.post("/api/ingest/zip")
async def ingest_zip(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    Endpoint for uploading and ingesting an Oura export ZIP file manually.
    """
    parser = OuraParser(db)
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp_file:
            shutil.copyfileobj(file.file, tmp_file)
            tmp_path = tmp_file.name
            
        logger.info(f"Received ZIP file, saved to {tmp_path}")

        await ingest_zip_async(tmp_path)
        os.remove(tmp_path)

        return {"message": "Ingestion successful"}
    except Exception as e:
        logger.error(f"Ingestion error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
