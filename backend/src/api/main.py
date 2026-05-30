import os
import asyncio
import logging
from datetime import datetime, timedelta
from contextlib import asynccontextmanager

from fastapi import FastAPI, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.src.api.routes import router
from backend.src.api.mobile import mobile_admin_router, mobile_client_router
from backend.src.api.insights import router as insights_router
from backend.src.api.analysis import router as analysis_router
from backend.src.api.investigations import router as investigations_router
from backend.src.database import init_db, SessionLocal
from backend.src.automation import automator
from backend.src.ingestion import OuraParser
from backend.src.config import config_manager
from backend.src.mobile_server_manager import mobile_server_manager
from backend.src.paths import get_user_data_dir

# ─── Logging ───
log_dir = get_user_data_dir()
log_file = os.path.join(log_dir, "backend_debug.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("API")
logger.info(f"API Starting... Logging to {log_file}")


def _resolve_frontend_dist_dir() -> str | None:
    import sys

    current_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(current_dir, "../../../frontend/dist-ui"),
        os.path.join(current_dir, "../../../frontend/dist"),
        os.path.join(current_dir, "../../../../frontend/dist-ui"),
        os.path.join(current_dir, "../../../../frontend/dist"),
    ]
    if getattr(sys, "frozen", False):
        exe_root = os.path.dirname(sys.executable)
        candidates = [
            os.path.join(exe_root, "frontend", "dist"),
            os.path.join(exe_root, "_internal", "frontend", "dist"),
            *candidates,
        ]
    for path in candidates:
        normalized = os.path.normpath(path)
        if os.path.isdir(normalized):
            return normalized
    return None


def _mount_frontend_static(app: FastAPI) -> None:
    """Serve the Vite build from the desktop backend (required for production Electron)."""
    if getattr(app.state, "frontend_static_mounted", False):
        return
    dist_dir = _resolve_frontend_dist_dir()
    if not dist_dir:
        logger.warning("Frontend dist directory not found; API-only mode.")
        return

    from fastapi.staticfiles import StaticFiles

    index_html = os.path.join(dist_dir, "index.html")
    if not os.path.isfile(index_html):
        logger.warning("Frontend index.html missing at %s", index_html)
        return

    logger.info("Serving frontend from %s", dist_dir)
    # Registered in lifespan after API routers so /api/* keeps priority.
    app.mount("/", StaticFiles(directory=dist_dir, html=True), name="frontend-static")
    app.state.frontend_static_mounted = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    init_db()
    _mount_frontend_static(app)

    # Reset only transient in-progress statuses; keep OTP/waiting states for the UI.
    cfg = config_manager.get_config()
    preserve_statuses = {"otp_needed", "Waiting"}
    stuck_processing = {
        "Processing",
        "Starting...",
        "Initializing...",
        "Running Automation...",
        "Running Automation",
        "Downloading...",
        "Ingesting...",
        "Submitting OTP...",
        "Starting manual run...",
    }
    current = cfg.get("status", "Idle")
    if current in stuck_processing:
        logger.info("Startup: Resetting stuck status %r to Idle.", current)
        config_manager.update_status("Idle", message="")
    elif current not in ("Idle", "Error") and current not in preserve_statuses:
        logger.info("Startup: Resetting unknown status %r to Idle.", current)
        config_manager.update_status("Idle", message="")
        
    # Start background worker
    task = asyncio.create_task(background_worker())
    if os.environ.get("CRACKED_OURA_DISABLE_MOBILE_AUTOSTART") != "1":
        try:
            mobile_server_manager.reconcile()
        except Exception:
            logger.exception("Mobile sync server reconcile failed during startup")
    
    yield
    
    # Shutdown (optional cleanup)
    # task.cancel()
    mobile_server_manager.stop()

app = FastAPI(
    title="Cracked Oura API",
    description="API for accessing Oura Ring data stored in local SQLite database.",
    version="0.1.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(router)
app.include_router(mobile_client_router)
app.include_router(mobile_admin_router)
app.include_router(insights_router)
app.include_router(analysis_router)
app.include_router(investigations_router)

# --- API Models for Automation ---
class AutomationConfig(BaseModel):
    email: str
    schedule_time: str
    is_active: bool
    headless: bool = True

# --- Endpoints ---

@app.get("/api/automation/status")
async def get_automation_status():
    """Returns the current automation configuration and status."""
    from backend.src.otp_state import enrich_automation_status

    return enrich_automation_status(config_manager.get_config())

@app.post("/api/automation/config")
async def update_automation_config(config: AutomationConfig):
    """Updates automation settings."""
    config_manager.update_config(
        email=config.email, 
        schedule_time=config.schedule_time,
        is_active=config.is_active,
        headless=config.headless
    )
    # Configure automator with new email settings immediately
    automator.email = config.email
        
    return {"status": "success", "message": "Configuration updated."}

class OTPRequest(BaseModel):
    otp: str
    action: str = "test" # test = verify login only; run = resume full sync; download = resume download

@app.post("/api/automation/submit-otp")
async def submit_otp(request: OTPRequest, background_tasks: BackgroundTasks):
    """
    Submits OTP code to the running automation session.
    """
    logger.info(f"Received OTP: {request.otp}, Action: {request.action}")
    config_manager.update_status("Submitting OTP...")
    
    try:
        result = await automator.submit_otp(request.otp)
        if result["status"] == "success":
            from backend.src.otp_state import clear_otp_request

            clear_otp_request()
            if request.action == "run":
                config_manager.update_status("Login Successful! Resuming Full Run...")
                background_tasks.add_task(run_ingestion_task, force=True)
                return {"status": "success", "message": "OTP Accepted. Resuming full automation."}
            
            elif request.action == "download":
                config_manager.update_status("Login Successful! Resuming Download...")
                background_tasks.add_task(run_download_existing_task)
                return {"status": "success", "message": "OTP Accepted. Resuming download."}
            
            elif request.action == "test":
                config_manager.update_status("Login Successful! Session saved.")
                await automator.cleanup()
                return {"status": "success", "message": "OTP Accepted. Login verified."}
            
            else:
                # Default fallback
                config_manager.update_status("Login Successful!")
                return {"status": "success", "message": "OTP Accepted."}

        else:
            config_manager.update_status(f"OTP Error: {result['message']}")
            return {"status": "error", "message": result['message']}
    except Exception as e:
        config_manager.update_status(f"OTP Error: {str(e)}")
        return {"status": "error", "message": str(e)}

@app.post("/api/automation/run-now")
async def run_automation(background_tasks: BackgroundTasks):
    """
    Manually triggers the full "Request New + Download" flow.
    """
    logger.info("Manual automation trigger received.")
    config_manager.update_status("Starting manual run...")
    
    try:
        # Initialize if needed
        cfg = config_manager.get_config()
        await automator.initialize(headless=cfg.get("headless", False))
        automator.email = cfg.get("email", "")

        background_tasks.add_task(run_ingestion_task, force=True)
        return {"status": "started", "message": "Automation started."}

    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/automation/clear-session")
async def clear_session():
    """Clears the current automation session."""
    try:
        if await automator.clear_session():
            from backend.src.otp_state import clear_otp_request

            clear_otp_request()
            config_manager.update_status("Session cleared.")
            return {"status": "success", "message": "Session cleared. Please login again."}
        return {"status": "info", "message": "No session found to clear."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/api/automation/test-login")
async def test_login():
    """Tests the login functionality with current credentials."""
    try:
        config_manager.update_status("Testing Login...")
        cfg = config_manager.get_config()
        await automator.initialize(headless=cfg.get("headless", False))
        automator.email = cfg.get("email", "")
        res = await automator.login()
        if res and res.get("status") == "otp_required":
             config_manager.update_status("Waiting for OTP...")
             return {"status": "otp_required", "message": "OTP Required"}
        
        config_manager.update_status("Login Check Complete.")
        await automator.cleanup() # Close browser if successful
        return res
    except Exception as e:
        config_manager.update_status(f"Login Error: {str(e)}")
        return {"status": "error", "message": str(e)}

async def run_download_existing_task():
    """
    Standalone task for downloading existing export.
    """
    logger.info("Starting download existing task...")
    waiting_for_otp = False
    try:
        cfg = config_manager.get_config()
        # Always reinitialize to get a fresh browser session with saved cookies
        if automator._is_initialized:
            try:
                await automator.cleanup()
            except Exception as e:
                logger.warning(f"Cleanup before download task had errors: {e}")
        
        await automator.initialize(headless=cfg.get("headless", True))
        automator.email = cfg.get("email", "")
        
        # Use user data dir for downloads
        from backend.src.paths import get_user_data_dir
        save_dir = str(get_user_data_dir())
        
        # Try navigating directly to export page (session loaded from storage_state)
        result = await automator.download_existing_export(save_dir=save_dir)
        
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
            logger.info("Download existing task paused: waiting for OTP.")
            return

        if isinstance(result, dict):
            # Error dict returned (not a file path)
            error_msg = result.get("message", "Unknown download error")
            logger.error(f"Download failed: {error_msg}")
            config_manager.update_status("Error", message=error_msg)
            return
        
        file_path = result
        
        if file_path:
            logger.info(f"Export downloaded to {file_path}. Starting ingestion...")
            await process_ingestion(file_path)
        else:
            logger.info("No existing export found.")
            config_manager.update_status("Error", message="No export available to download. Try requesting a new sync.")
        
        # Cleanup on success (if not waiting for OTP)
        await automator.cleanup()

    except Exception as e:
        logger.error(f"Download task failed: {e}")
        config_manager.update_status("Error", message=f"Download failed: {e}")
        if not waiting_for_otp:
            try:
                await automator.cleanup()
            except Exception:
                pass


@app.post("/api/automation/download-latest")
async def download_latest_existing(background_tasks: BackgroundTasks):
    """Downloads the latest EXISTING export (if any). Does NOT request new."""
    background_tasks.add_task(run_download_existing_task)
    return {"status": "started", "message": "Checking for existing downloads..."}


# --- Background Logic ---

async def run_ingestion_task(force=False):
    """
    The core logic for checking, requesting, and downloading data.
    """
    cfg = config_manager.get_config()
    if not force and not cfg.get("is_active", True):
        return

    logger.info("Background worker: Starting ingestion task...")
    config_manager.update_status("Starting...")
    waiting_for_otp = False
    
    try:
        # 1. Always reinitialize for a fresh browser session
        if automator._is_initialized:
            try:
                await automator.cleanup()
            except Exception as e:
                logger.warning(f"Cleanup before ingestion task had errors: {e}")
        
        config_manager.update_status("Initializing...")
        headless_mode = cfg.get("headless", True)
        await automator.initialize(headless=headless_mode)
        
        # Configure credentials
        automator.email = cfg.get("email", "")
        
        # Check login first
        login_res = await automator.login()
        if login_res and login_res.get("status") == "otp_required":
             waiting_for_otp = True
             logger.info("Background worker: OTP Required.")
             from backend.src.otp_state import mark_otp_requested, otp_prompt_message

             if login_res.get("code_sent"):
                 mark_otp_requested()
             cfg = config_manager.get_config()
             config_manager.update_status(
                 "otp_needed",
                 message=otp_prompt_message(cfg, "Check your email for a verification code."),
             )
             return
        
        from backend.src.paths import get_user_data_dir

        save_dir = str(get_user_data_dir())

        config_manager.update_status("Running Automation...", message="Checking for a ready export...")
        result = await automator.download_existing_export(save_dir=save_dir)

        if isinstance(result, str) and result:
            file_path = result
            logger.info("Background worker: Downloaded existing export to %s", file_path)
            config_manager.update_status("Downloading...")
            await process_ingestion(file_path)
            await automator.cleanup()
            return

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
            return

        config_manager.update_status("Running Automation...", message="Requesting new export...")
        config_manager.update_config(
            last_export_request_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
        result = await automator.request_new_export_and_download(save_dir=save_dir)
        
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
             logger.info("Background worker: paused waiting for OTP.")
             return

        file_path = result
        
        if isinstance(result, dict) and result.get("status") == "error":
            logger.error("Background worker: %s", result.get("message"))
            config_manager.update_status("Error", message=result.get("message", "Sync failed"))
        elif file_path:
            logger.info(f"Background worker status: Downloaded to {file_path}")
            config_manager.update_status("Downloading...")
            await process_ingestion(file_path)
        else:
            logger.info("Background worker: No file downloaded (Timeout or Error).")
            config_manager.update_status(
                "Error",
                message="No file downloaded. If Oura emailed you, try Sync now again in a minute.",
            )
        
        # Cleanup on success
        await automator.cleanup()

    except Exception as e:
        logger.error(f"Background worker error: {e}")
        config_manager.update_status("Error", message=f"Sync failed: {e}")
        if not waiting_for_otp:
            try:
                await automator.cleanup()
            except Exception:
                pass

async def process_ingestion(zip_path):
    from backend.src.ingestion.runner import ingest_zip_async

    logger.info(f"Background worker: Downloaded to {zip_path}")
    config_manager.update_status("Ingesting...", message="Ingesting downloaded export…")
    try:
        await ingest_zip_async(
            zip_path,
            success_message="Sync completed successfully.",
        )
        logger.info("Background worker: Ingestion successful.")
    except Exception as e:
        logger.error(f"Background worker: Ingestion failed: {e}")


async def background_worker():
    logger.info("Background worker started.")
    while True:
        try:
            # Check every minute if it's time to run
            now = datetime.now()
            cfg = config_manager.get_config()
            if os.environ.get("CRACKED_OURA_DISABLE_MOBILE_AUTOSTART") != "1":
                try:
                    mobile_server_manager.reconcile()
                except Exception:
                    logger.exception("Mobile sync server reconcile failed in background worker")
            
            # Calculate next run time for display
            schedule_time_str = cfg.get("schedule_time", "11:00")
            try:
                sh, sm = map(int, schedule_time_str.split(":"))
                run_today = now.replace(hour=sh, minute=sm, second=0, microsecond=0)
                if now > run_today:
                    next_run = run_today + timedelta(days=1)
                else:
                    next_run = run_today
                
                config_manager.update_status(cfg.get("status", "Idle"), next_run=next_run.strftime("%Y-%m-%d %H:%M:%S"))

                if now.hour == sh and now.minute == sm:
                     await run_ingestion_task()
                
                # If in "Waiting" state, poll every 5 minutes            
                elif "Waiting" in cfg.get("status", ""):
                    if now.minute % 5 == 0:
                        logger.info("Background worker: Polling for export status...")
                        await run_ingestion_task()
                     
            except Exception as e:
                logger.error(f"Scheduler error: {e}")

            # Sleep 60 seconds
            await asyncio.sleep(60)
                    
        except Exception as e:
            logger.error(f"Background worker loop error: {e}")
            await asyncio.sleep(60)

if __name__ == "__main__":
    import uvicorn
    import sys
    import traceback

    if os.environ.get("CRACKED_OURA_MOBILE_API_ONLY") == "1":
        from backend.src.mobile_server import main as mobile_server_main
        mobile_server_main()
        raise SystemExit(0)

    if getattr(sys, 'frozen', False):
        try:
            uvicorn.run(app, host="127.0.0.1", port=8000, reload=False)
        except Exception as e:
            try:
                log_path = os.path.join(get_user_data_dir(), "startup_crash.log")
                with open(log_path, "w", encoding="utf-8") as f:
                    f.write(f"Startup Crash: {e}\n")
                    f.write(traceback.format_exc())
            except Exception:
                pass
            raise
    else:
        uvicorn.run("backend.src.api.main:app", host="0.0.0.0", port=8000, reload=True, reload_dirs=["backend"])
