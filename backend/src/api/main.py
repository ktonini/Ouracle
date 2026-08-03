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
from backend.src.config import WAITING_FOR_EXPORT_STATUS, config_manager
from backend.src.mobile_server_manager import mobile_server_manager
from backend.src.paths import get_user_data_dir
from backend.src.activity_log import append_activity
from backend.src.export_wait import mark_waiting_for_export
from backend.src.otp_recovery import MAX_OTP_RECOVERY_ATTEMPTS, resolve_otp_or_pause

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
    preserve_statuses = {"otp_needed", "Waiting", WAITING_FOR_EXPORT_STATUS}
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
        if cfg.get("last_export_request_at"):
            logger.info(
                "Startup: Converting stuck status %r into durable export wait.",
                current,
            )
            from backend.src.export_wait import mark_waiting_for_export

            mark_waiting_for_export(requested_now=False)
        else:
            logger.info("Startup: Resetting stuck status %r to Idle.", current)
            config_manager.update_status("Idle", message="")
    elif current == WAITING_FOR_EXPORT_STATUS:
        logger.info("Startup: Resuming durable export wait.")
        append_activity(
            "App started — still waiting for Oura export; will keep checking.",
            category="export",
        )
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
             if await resolve_otp_or_pause(res, automator_instance=automator):
                 config_manager.update_status("Login Check Complete.")
                 await automator.cleanup()
                 return {"status": "success", "message": "Login verified automatically."}
             return {
                 "status": "otp_required",
                 "message": config_manager.get_config().get("message") or "OTP Required",
             }
        
        config_manager.update_status("Login Check Complete.")
        await automator.cleanup() # Close browser if successful
        return res
    except Exception as e:
        config_manager.update_status(f"Login Error: {str(e)}")
        return {"status": "error", "message": str(e)}

async def run_download_existing_task(_otp_attempt: int = 0):
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
            if not await resolve_otp_or_pause(result, automator_instance=automator):
                waiting_for_otp = True
                logger.info("Download existing task paused: waiting for OTP.")
                return
            if _otp_attempt >= MAX_OTP_RECOVERY_ATTEMPTS:
                logger.warning("Download existing task: OTP kept being required; giving up.")
                config_manager.update_status(
                    "Error",
                    message="Oura kept asking for a verification code. Sign in again in Settings.",
                )
                await automator.cleanup()
                return
            # Automatic recovery authenticated the session; retry the same
            # download operation with the saved session.
            return await run_download_existing_task(_otp_attempt=_otp_attempt + 1)

        if isinstance(result, dict):
            # Error dict returned (not a file path)
            error_msg = result.get("message", "Unknown download error")
            logger.error(f"Download failed: {error_msg}")
            if config_manager.get_config().get("status") == WAITING_FOR_EXPORT_STATUS or (
                "No downloadable export" in error_msg
            ):
                # Keep durable wait instead of flipping to Error when nothing is ready yet.
                prior = config_manager.get_config().get("last_export_request_at")
                if prior:
                    mark_waiting_for_export(requested_now=False)
                    return
            config_manager.update_status("Error", message=error_msg)
            return
        
        file_path = result
        
        if file_path:
            logger.info(f"Export downloaded to {file_path}. Starting ingestion...")
            await process_ingestion(file_path)
        else:
            logger.info("No existing export found.")
            if config_manager.get_config().get("last_export_request_at"):
                mark_waiting_for_export(requested_now=False)
            else:
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


async def run_check_export_ready_task(force: bool = False, _otp_attempt: int = 0) -> None:
    """Download-existing only — used while Waiting for export so we never re-request."""
    cfg = config_manager.get_config()
    if not force and not cfg.get("is_active", True):
        return

    logger.info("Checking whether a requested Oura export is ready…")
    waiting_for_otp = False
    try:
        if automator._is_initialized:
            try:
                await automator.cleanup()
            except Exception as e:
                logger.warning("Cleanup before export-ready check failed: %s", e)

        await automator.initialize(headless=cfg.get("headless", True))
        automator.email = cfg.get("email", "")

        from backend.src.paths import get_user_data_dir

        save_dir = str(get_user_data_dir())
        config_manager.update_status(
            WAITING_FOR_EXPORT_STATUS,
            message="Checking Oura for a ready export…",
            logged_in=True,
        )
        result = await automator.download_existing_export(save_dir=save_dir)

        if isinstance(result, str) and result:
            append_activity("Export ready — downloading…", level="success", category="export")
            config_manager.update_status("Downloading...", message="Downloading ready export…")
            await process_ingestion(result)
            await automator.cleanup()
            return

        if isinstance(result, dict) and result.get("status") == "otp_required":
            waiting_for_otp = not await resolve_otp_or_pause(
                result,
                automator_instance=automator,
            )
            if waiting_for_otp:
                return
            if _otp_attempt >= MAX_OTP_RECOVERY_ATTEMPTS:
                logger.warning("Export-ready check: OTP kept being required; giving up.")
                await automator.cleanup()
                return
            return await run_check_export_ready_task(
                force=True,
                _otp_attempt=_otp_attempt + 1,
            )

        mark_waiting_for_export(requested_now=False)
        await automator.cleanup()
    except Exception as e:
        logger.error("Export-ready check failed: %s", e)
        config_manager.update_status(
            WAITING_FOR_EXPORT_STATUS,
            message=(
                f"Could not check export status ({e}). "
                "Will retry automatically; Sync now also retries the download check."
            ),
            logged_in=True,
        )
        if not waiting_for_otp:
            try:
                await automator.cleanup()
            except Exception:
                pass


async def run_ingestion_task(force=False, _otp_attempt: int = 0):
    """
    The core logic for checking, requesting, and downloading data.

    If we are already Waiting for export, only poll for a ready download
    (never request another export).
    """
    cfg = config_manager.get_config()
    if not force and not cfg.get("is_active", True):
        return

    if cfg.get("status") == WAITING_FOR_EXPORT_STATUS:
        return await run_check_export_ready_task(force=force)

    def otp_retries_exhausted() -> bool:
        """True when automatic recovery keeps landing back on the OTP screen."""
        if _otp_attempt < MAX_OTP_RECOVERY_ATTEMPTS:
            return False
        logger.warning("Background worker: OTP kept being required; giving up.")
        config_manager.update_status(
            "Error",
            message="Oura kept asking for a verification code. Sign in again in Settings.",
        )
        return True

    logger.info("Background worker: Starting ingestion task...")
    config_manager.update_status("Starting...")
    waiting_for_otp = False

    try:
        if automator._is_initialized:
            try:
                await automator.cleanup()
            except Exception as e:
                logger.warning(f"Cleanup before ingestion task had errors: {e}")

        config_manager.update_status("Initializing...")
        headless_mode = cfg.get("headless", True)
        await automator.initialize(headless=headless_mode)

        automator.email = cfg.get("email", "")

        login_res = await automator.login()
        if login_res and login_res.get("status") == "otp_required":
            waiting_for_otp = not await resolve_otp_or_pause(
                login_res,
                automator_instance=automator,
            )
            if waiting_for_otp:
                logger.info("Background worker paused: OTP required.")
                return

        from backend.src.paths import get_user_data_dir

        save_dir = str(get_user_data_dir())

        config_manager.update_status("Running Automation...", message="Checking for a ready export...")
        result = await automator.download_existing_export(save_dir=save_dir)

        # A ready export on Oura is often the same one we already ingested.
        # Only stop here when it actually moved our newest day forward;
        # otherwise ask Oura for a freshly generated export.
        skip_ready_download = False
        if isinstance(result, str) and result:
            file_path = result
            logger.info("Background worker: Downloaded existing export to %s", file_path)
            append_activity("Downloaded an existing ready export.", level="success", category="export")
            config_manager.update_status("Downloading...")
            advanced = await process_ingestion(file_path)
            if advanced is not False:
                # Advanced, or the ingest failed and already reported why.
                await automator.cleanup()
                return
            logger.info(
                "Background worker: existing export added no new days; "
                "requesting a fresh export from Oura."
            )
            skip_ready_download = True

        elif isinstance(result, dict) and result.get("status") == "otp_required":
            waiting_for_otp = not await resolve_otp_or_pause(
                result,
                automator_instance=automator,
            )
            if waiting_for_otp:
                return
            if otp_retries_exhausted():
                return
            return await run_ingestion_task(force=True, _otp_attempt=_otp_attempt + 1)

        config_manager.update_status(
            "Running Automation...",
            message=(
                "The export on Oura had no new days. Requesting a fresh export…"
                if skip_ready_download
                else "Requesting new export..."
            ),
        )
        result = await automator.request_new_export_and_download(
            save_dir=save_dir,
            skip_ready_download=skip_ready_download,
            wait_for_ready=False,
        )

        if isinstance(result, dict) and result.get("status") == "otp_required":
            waiting_for_otp = not await resolve_otp_or_pause(
                result,
                automator_instance=automator,
            )
            if waiting_for_otp:
                logger.info("Background worker paused: OTP required.")
                return
            if otp_retries_exhausted():
                return
            return await run_ingestion_task(force=True, _otp_attempt=_otp_attempt + 1)

        if isinstance(result, str) and result:
            append_activity("Downloaded an existing ready export.", level="success", category="export")
            config_manager.update_status("Downloading...")
            await process_ingestion(result)
            await automator.cleanup()
            return

        if isinstance(result, dict) and result.get("status") in ("export_requested", "export_processing"):
            mark_waiting_for_export(requested_now=True)
            await automator.cleanup()
            return

        if isinstance(result, dict) and result.get("status") == "error":
            logger.error("Background worker: %s", result.get("message"))
            config_manager.update_status("Error", message=result.get("message", "Sync failed"))
        else:
            logger.info("Background worker: No file downloaded (Timeout or Error).")
            config_manager.update_status(
                "Error",
                message="No file downloaded. If Oura emailed you, try Sync now again in a minute.",
            )

        await automator.cleanup()

    except Exception as e:
        logger.error(f"Background worker error: {e}")
        config_manager.update_status("Error", message=f"Sync failed: {e}")
        if not waiting_for_otp:
            try:
                await automator.cleanup()
            except Exception:
                pass


async def process_ingestion(zip_path) -> bool | None:
    """Ingest a downloaded ZIP.

    Returns ``True`` when the newest local Oura day moved forward, ``False``
    when the export contained nothing newer, and ``None`` when the ingest
    itself failed (already reported to the user).
    """
    from backend.src.ingestion.runner import ingest_zip_async

    logger.info(f"Background worker: Downloaded to {zip_path}")
    config_manager.update_status("Ingesting...", message="Ingesting downloaded export…")
    append_activity("Ingesting downloaded export…", category="ingest")
    try:
        advanced = await ingest_zip_async(
            zip_path,
            success_message="Sync completed successfully.",
        )
        logger.info("Background worker: Ingestion successful.")
        append_activity("Ingest completed successfully.", level="success", category="ingest")
        return advanced
    except Exception as e:
        logger.error(f"Background worker: Ingestion failed: {e}")
        append_activity(f"Ingest failed: {e}", level="error", category="ingest")
        return None


async def background_worker():
    logger.info("Background worker started.")
    while True:
        try:
            now = datetime.now()
            cfg = config_manager.get_config()
            if os.environ.get("CRACKED_OURA_DISABLE_MOBILE_AUTOSTART") != "1":
                try:
                    mobile_server_manager.reconcile()
                except Exception:
                    logger.exception("Mobile sync server reconcile failed in background worker")

            from backend.src.scheduling import compute_next_daily_run

            schedule_time_str = cfg.get("schedule_time", "11:00")
            try:
                sh, sm = map(int, schedule_time_str.split(":"))
                next_run = compute_next_daily_run(now, schedule_time_str)
                config_manager.update_status(
                    cfg.get("status", "Idle"),
                    next_run=next_run.strftime("%Y-%m-%d %H:%M:%S"),
                )

                if now.hour == sh and now.minute == sm:
                    await run_ingestion_task()

                elif cfg.get("status") == WAITING_FOR_EXPORT_STATUS:
                    if now.minute % 5 == 0:
                        logger.info("Background worker: Checking for ready export…")
                        await run_check_export_ready_task()

            except Exception as e:
                logger.error(f"Scheduler error: {e}")

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
