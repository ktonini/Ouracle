import asyncio
import os
import logging
from playwright.async_api import async_playwright, expect, Page, BrowserContext, Browser
from typing import Optional, Dict, Any, Union

from .config import config_manager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("OuraAutomator")

class OuraAutomator:
    """
    Automates Oura Web Dashboard interactions using Playwright.
    Handles Login, OTP verification, Data Export request, and File Download.
    """
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self._is_initialized = False
        # Use a stable path regardless of CWD (Electron app changes CWD per invocation)
        from .paths import get_user_data_dir
        self.storage_state_path = os.path.join(str(get_user_data_dir()), "oura_session.json")
        self.email: Optional[str] = None
        self.password: Optional[str] = None
        self.base_url = "https://membership.ouraring.com"
        self.export_url = f"{self.base_url}/data-export"
        self._login_in_progress = False

        # Configure Playwright Browser Path
        from .paths import get_user_data_dir
        
        # Use a writable directory for browsers
        self.browser_dir = os.path.join(get_user_data_dir(), "browsers")
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = self.browser_dir

    async def initialize(self, headless: Optional[bool] = None):
        """Initializes the Playwright browser session."""
        if self._is_initialized:
            return

        # Ensure browser is installed
        try:
            await self._ensure_browser_installed()
        except Exception as e:
            logger.error(f"Browser installation check failed: {e}", exc_info=True)
            raise Exception(f"Failed to ensure Playwright browser is installed: {e}")

        # If headless not provided, read from config
        if headless is None:
            config = config_manager.get_config()
            headless = config.get("headless", True)
        
        # Load credentials from config if not already set
        if not self.email:
            config = config_manager.get_config()
            self.email = config.get("email")
            self.password = config.get("password")

        logger.info(f"Initializing Playwright (Headless: {headless})")
        self.playwright = await async_playwright().start()
        
        try:
            self.browser = await self.playwright.chromium.launch(headless=headless, args=["--start-maximized"])
        except Exception as e:
            logger.error(f"Failed to launch browser: {e}")
            logger.info("Retrying installation...")
            await self._ensure_browser_installed(force=True)
            try:
                self.browser = await self.playwright.chromium.launch(headless=headless, args=["--start-maximized"])
            except Exception as e2:
                logger.error(f"Browser launch still failed after reinstall: {e2}", exc_info=True)
                raise Exception(f"Browser launch failed after reinstall: {e2}") from e2
        
        # Load session if exists
        state = self.storage_state_path if os.path.exists(self.storage_state_path) else None
        if state:
            logger.info(f"Loading session from {state}")
            
        self.context = await self.browser.new_context(
            viewport={"width": 1920, "height": 1080},
            storage_state=state
        )
            
        self.page = await self.context.new_page()
        self._is_initialized = True

    async def _ensure_browser_installed(self, force=False):
        """Checks if Chromium is installed and installs it if missing."""
        import sys
        import glob
        
        # Check if the actual browser executable exists (not just marker files).
        # Playwright creates versioned directories (e.g. chromium_headless_shell-1208)
        # that may contain only marker files if a previous install was interrupted.
        if not force and os.path.exists(self.browser_dir):
            # Look for any actual browser executable in versioned subdirs
            headless_exes = glob.glob(
                os.path.join(self.browser_dir, "chromium_headless_shell-*",
                             "chrome-headless-shell-win64", "chrome-headless-shell.exe")
            )
            chrome_exes = glob.glob(
                os.path.join(self.browser_dir, "chromium-*",
                             "chrome-win64", "chrome.exe")
            )
            if headless_exes or chrome_exes:
                return

        logger.info("Installing Playwright Chromium browser...")
        config_manager.update_status("Installing dependency (Chromium)...")
        
        try:
            # Import internal driver helpers to find the bundled Node.js
            from playwright._impl._driver import compute_driver_executable, get_driver_env
            
            driver_executable, driver_cli = compute_driver_executable()
            env = get_driver_env()
            
            # Use the bundled Node.js to run the install command directly
            # This avoids recursive app launching
            
            logger.info(f"Using driver: {driver_executable} {driver_cli}")
            
            process = await asyncio.create_subprocess_exec(
                driver_executable, driver_cli, "install", "chromium",
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                logger.error(f"Browser install failed: {stderr.decode()}")
                raise Exception(f"Failed to install browser: {stderr.decode()}")
            
            logger.info("Browser installed successfully.")
            
        except Exception as e:
            logger.error(f"Browser installation error: {e}")
            raise

    async def start_login(self, email: str):
        """Initiates the login process with the provided email."""
        if self._login_in_progress:
            logger.warning("Login already in progress — cleaning up and restarting.")
            # If a previous attempt is in progress (e.g., it failed partway through),
            # clean up the browser session and restart fresh so the "Send code" button
            # is actually clicked again and a new email is dispatched.
            await self.cleanup()
            self._login_in_progress = False
        self._login_in_progress = True
        if not self._is_initialized:
            await self.initialize()
        self.email = email
        try:
            return await self.login()
        except Exception:
            self._login_in_progress = False
            raise

    async def cleanup(self):
        """Closes browser resources and stops Playwright."""
        errors = []
        if self.context:
            try:
                await self.context.close()
            except Exception as e:
                errors.append(f"context.close: {e}")
            self.context = None
        if self.browser:
            try:
                await self.browser.close()
            except Exception as e:
                errors.append(f"browser.close: {e}")
            self.browser = None
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception as e:
                errors.append(f"playwright.stop: {e}")
            self.playwright = None
        self.page = None
        self._is_initialized = False
        if errors:
            logger.warning(f"OuraAutomator cleanup had errors: {errors}")
        else:
            logger.info("OuraAutomator cleaned up.")

    async def clear_session(self) -> bool:
        """Clears stored session file and closes browser resources."""
        self._login_in_progress = False
        await self.cleanup()
        from .otp_state import clear_otp_request

        config_manager.update_config(logged_in=False)
        clear_otp_request()
        if os.path.exists(self.storage_state_path):
            os.remove(self.storage_state_path)
            logger.info("Session file removed.")
            return True
        return False

    async def _ensure_page_alive(self):
        """Ensures self.page is a valid, non-closed page. Updates reference after navigations."""
        if self.page and not self.page.is_closed():
            return
        # Page was closed — grab the latest page from the context
        if self.context:
            pages = self.context.pages
            if pages:
                self.page = pages[-1]
                logger.info(f"Page was closed, switched to new page: {self.page.url}")
                return
        # If context is also gone, raise
        raise Exception("Browser context closed; re-initialization required.")

    async def save_context(self):
        """Saves current browser context (cookies/local storage) to disk."""
        if self.context:
            await self.context.storage_state(path=self.storage_state_path)
            logger.info(f"Session saved to {self.storage_state_path}")

    # --- Login Logic ---

    async def login(self) -> Union[None, Dict[str, str]]:
        """
        Executes the login flow.
        Returns None if already logged in, or a status dictionary if further action (like OTP) is needed.
        """
        if not self.page:
            raise Exception("Page not initialized")

        logger.info("Checking login status...")
        try:
            # Check if already on the correct domain or redirect to it
            if self.base_url in self.page.url:
                 pass
            else:
                 await self.page.goto(self.base_url, timeout=60000)
            
            await self.page.wait_for_load_state("networkidle", timeout=10000)
            
            if self._is_logged_in():
                logger.info("Already logged in.")
                await self.save_context()
                return

            logger.info("Not logged in. Attempting login...")
            if not self.email:
                raise Exception("Login required but no email configured.")

            return await self._perform_login_actions()

        except Exception as e:
            logger.error(f"Login error: {e}")
            raise

    def _is_logged_in(self) -> bool:
        """Determines if user appears logged in based on URL state."""
        if not self.page:
            return False
        url = (self.page.url or "").lower().rstrip('/')
        # After successful OTP, Oura redirects through a chain:
        #   moi.ouraring.com/authn/.../enter-otp
        #   -> membership.ouraring.com/login?code=... (intermediate code exchange)
        #   -> membership.ouraring.com/ (dashboard/home)
        # The intermediate 'login' URL is transient; check for final dashboard state.
        if "membership.ouraring.com" in url and "login" not in url and "authn" not in url:
            return True
        # Also accept moi.ouraring.com dashboard pages (sometimes used instead)
        if "ouraring.com" in url and "login" not in url and "authn" not in url and "enter-otp" not in url:
            return True
        return False

    async def _perform_login_actions(self) -> Dict[str, str]:
        """Interacts with the login form, handling email submission and checking for OTP requirements."""
        if "login" not in self.page.url and "authn" not in self.page.url:
             await self.page.goto(f"{self.base_url}/login", timeout=30000)

        # Fill Email
        logger.info(f"Filling email: {self.email}")
        email_input = self.page.locator("input[name='username']")
        if not await email_input.is_visible():
             email_input = self.page.locator("input[type='email']")
        
        if not await email_input.is_visible():
            raise Exception("Could not find email input.")

        await email_input.fill(self.email)
        await self.page.dispatch_event("input[name='username']", 'input') 
        
        await self._click_submit()
        
        # Check for OTP or Password requirements
        otp_status = await self._check_otp_screen()
        if otp_status:
            return otp_status

        # Password fallback (unlikely for Oura's current flow but retained for robustness)
        password_input = self.page.locator("input[type='password']")
        if await password_input.is_visible():
             if not self.password:
                 raise Exception("Password required but not configured.")
             await password_input.fill(self.password)
             await self.page.keyboard.press("Enter")
        
        # Final Verification
        try:
            await self._ensure_page_alive()
            await self.page.wait_for_load_state("networkidle")
        except Exception:
            pass
        if not self._is_logged_in():
             # Re-check OTP in case of network lag
             if await self._check_otp_screen():
                 return {"status": "otp_required", "message": "OTP required"}
             raise Exception("Login failed or incomplete.")
        
        logger.info("Login process completed successfully.")
        await self.save_context()
        self._login_in_progress = False
        config_manager.update_config(logged_in=True)
        return {"status": "success", "message": "Login successful"}

    async def _click_submit(self):
        """Clicks the submit button, handling various potential selectors."""
        submit_btn = self.page.locator("button[type='submit']")
        if not await submit_btn.is_visible():
            submit_btn = self.page.locator("#submit-button")
        
        if await submit_btn.is_visible():
            await submit_btn.click()
        else:
            await self.page.keyboard.press("Enter")
        
        try:
            await self._ensure_page_alive()
            await self.page.wait_for_timeout(3000)
        except Exception:
            pass

    async def _check_otp_screen(self):
        """Checks if OTP screen is active and handles the 'Send Code' intermediate step if present."""
        # Check for "Send code" intermediate page
        intermediate_btn = self.page.locator("button[name='selectedId']")
        otp_selectors = [
            "input[name='otp']",
            "#otp-code",
            "input[name='verification_code']",
            "input[autocomplete='one-time-code']",
            "input[inputmode='numeric']",
        ]

        code_sent = False
        if await intermediate_btn.is_visible():
            # Always click Send Code to ensure Oura actually emails a code
            logger.info("Found intermediate 'Send Code' button. Clicking...")
            await intermediate_btn.click()
            code_sent = True
            from .otp_state import mark_otp_requested

            mark_otp_requested()
            # Oura's redirect after Send Code navigates to a new page.
            try:
                await self._ensure_page_alive()
                await self.page.wait_for_timeout(3000)
            except Exception:
                try:
                    await self._ensure_page_alive()
                    await self.page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass

        # Check for OTP input visibility
        for selector in otp_selectors:
            if await self.page.locator(selector).first.is_visible():
                logger.info(f"OTP Login required (selector: {selector}).")
                return {
                    "status": "otp_required",
                    "message": "OTP required",
                    "code_sent": code_sent,
                }

        return None

    async def _trigger_send_code(self) -> bool:
        """Clicks Oura's send-code control when present. Returns True if clicked."""
        if not self.page:
            return False
        intermediate_btn = self.page.locator("button[name='selectedId']")
        if await intermediate_btn.is_visible():
            logger.info("Clicking Oura 'Send code' button.")
            await intermediate_btn.click()
            try:
                await self._ensure_page_alive()
                await self.page.wait_for_timeout(3000)
            except Exception:
                pass
            return True
        return False

    async def resend_otp(self) -> Dict[str, str]:
        """Request a fresh verification email from Oura."""
        cfg = config_manager.get_config()
        email = (cfg.get("email") or self.email or "").strip()
        if not email:
            return {"status": "error", "message": "No email configured."}

        self.email = email
        self._login_in_progress = True
        try:
            if not self._is_initialized:
                await self.initialize(headless=cfg.get("headless", True))
            await self._ensure_page_alive()

            if await self._trigger_send_code():
                from .otp_state import mark_otp_requested

                mark_otp_requested()
                return {
                    "status": "otp_required",
                    "message": "A new verification code was sent to your email.",
                    "code_sent": True,
                }

            login_res = await self.login()
            if login_res and login_res.get("status") == "otp_required":
                return {
                    "status": "otp_required",
                    "message": "A new verification code was sent to your email.",
                    "code_sent": bool(login_res.get("code_sent")),
                }
            return {
                "status": "error",
                "message": "Could not reach Oura's verification screen. Try logging in again.",
            }
        except Exception as e:
            logger.error(f"resend_otp failed: {e}")
            return {"status": "error", "message": str(e)}
        finally:
            self._login_in_progress = False

    async def submit_otp(self, otp: str):
        """Submits the provided OTP code to the active session."""
        if not self.page:
            return {"status": "error", "message": "Page not initialized"}

        logger.info(f"Submitting OTP: {otp}")
        try:
            otp_selectors = [
                "input[name='otp']",
                "#otp-code",
                "input[name='verification_code']",
                "input[autocomplete='one-time-code']",
                "input[inputmode='numeric']",
            ]

            target_frame = None
            otp_selector = None

            for frame in self.page.frames:
                for selector in otp_selectors:
                    locator = frame.locator(selector).first
                    try:
                        if await locator.is_visible(timeout=800):
                            target_frame = frame
                            otp_selector = selector
                            break
                    except Exception:
                        continue
                if otp_selector:
                    break

            if not target_frame or not otp_selector:
                raise Exception("Could not find OTP input field")

            await target_frame.fill(otp_selector, otp)
            # Let the page's auto-submit JS settle (Oura auto-submits on 6 digits)
            await self.page.wait_for_timeout(1500)

            # Try common submit controls first; fallback to Enter
            submitted = False
            submit_selectors = [
                "button[type='submit']",
                "#submit-button",
                "button:has-text('Verify')",
                "button:has-text('Continue')",
                "button:has-text('Submit')",
            ]
            for selector in submit_selectors:
                btn = target_frame.locator(selector).first
                try:
                    if await btn.is_visible(timeout=500):
                        await btn.click()
                        submitted = True
                        break
                except Exception:
                    continue

            if not submitted:
                await self.page.keyboard.press("Enter")

            # Wait for the multi-step Oura redirect chain to complete.
            # After a correct OTP, Oura goes: enter-otp -> oauth-authorize -> login (code exchange) -> dashboard.
            await self.page.wait_for_timeout(3000)
            try:
                await self.page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                logger.warning("Network idle timeout after OTP — continuing with current state")

            # Allow extra time for final redirect to dashboard
            for _ in range(5):
                if self._is_logged_in():
                    break
                await self.page.wait_for_timeout(1000)
                try:
                    await self.page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass

            # Verify success
            if self._is_logged_in():
                logger.info("OTP Accepted. Login successful.")
                await self.save_context()
                self._login_in_progress = False
                from .otp_state import clear_otp_request

                clear_otp_request()
                config_manager.update_config(logged_in=True)
                return {"status": "success", "message": "Login successful!"}

            invalid_code = False
            for err_text in ["Virheellinen koodi", "Invalid code", "incorrect code", "wrong code",
                             "Incorrect or expired code", "try again"]:
                try:
                    if await self.page.get_by_text(err_text).first.is_visible(timeout=500):
                        invalid_code = True
                        break
                except Exception:
                    continue

            if invalid_code:
                return {
                    "status": "error",
                    "message": "Invalid or expired OTP code. Request a new code and try again.",
                }

            return {"status": "error", "message": f"Login failed (Unknown state). Current URL: {self.page.url}"}

        except Exception as e:
            logger.error(f"OTP submission error: {e}")
            return {"status": "error", "message": str(e)}

    # --- Data Export Logic ---

    async def _is_export_processing(self) -> bool:
        """True when Oura shows an export is being generated (not ready to download yet)."""
        if not self.page:
            return False
        for snippet in (
            "Processing",
            "Preparing",
            "being prepared",
            "export is on its way",
            "requested your data",
        ):
            try:
                if await self.page.get_by_text(snippet, exact=False).first.is_visible(timeout=800):
                    return True
            except Exception:
                continue
        return False

    async def _is_export_download_ready(self) -> bool:
        """True when Oura's export page shows a download control."""
        if not self.page:
            return False
        download_indicators = [
            "button[aria-label='Download data']",
            "button[aria-label='Download your data']",
            "button:has-text('Download your data')",
            "button:has-text('Download data')",
            "button:has-text('Download')",
            "a[download]",
            "a:has-text('Download')",
        ]
        for sel in download_indicators:
            try:
                if await self.page.locator(sel).first.is_visible(timeout=1500):
                    return True
            except Exception:
                continue
        return False

    async def request_new_export_and_download(
        self,
        save_dir: str,
        *,
        skip_ready_download: bool = False,
        wait_for_ready: bool = True,
    ) -> Union[str, Dict[str, Any], None]:
        """
        Orchestrates the data export flow:
        1. Navigate to export page.
        2. Request a new export (if not already processing).
        3. Optionally wait for Oura to generate the export (polling).
        4. Download the file when waiting is enabled.

        When ``wait_for_ready`` is False, request (or detect in-progress generation)
        and return immediately so the app can resume checks across restarts.
        When ``skip_ready_download`` is True, do not download an export that is
        already on the page — used after a stale ingest so we wait for a newly
        generated file instead of re-downloading the same ZIP.
        """
        logger.info("Starting Data Request Flow...")
        if not self._is_initialized:
            await self.initialize()

        if not self.page:
            self.page = await self.context.new_page()

        requested = False
        already_processing = False

        try:
            # 1. Navigate
            if not await self._navigate_to_export_page():
                # Check if stuck on Login/OTP — submit email so Oura sends the code
                if "login" in self.page.url or "authn" in self.page.url:
                    login_res = await self.login()
                    if login_res and login_res.get("status") == "otp_required":
                        return {"status": "otp_required"}
                    # Login succeeded, retry navigation
                    if not await self._navigate_to_export_page():
                        return {
                            "status": "error",
                            "message": (
                                "Could not open Oura data export after sign-in. "
                                "Try logging out in Settings and signing in again."
                            ),
                        }
                else:
                    return {"status": "error", "message": "Could not open Oura data export page."}

            # 2. Fast path: download when a ready file exists and we are not forcing a new export.
            if not skip_ready_download and await self._is_export_download_ready():
                logger.info("Export already ready on Oura — downloading without a new request.")
                return await self._download_file(save_dir)

            if skip_ready_download:
                # Do not treat an old on-page download as a new export.
                if await self._is_export_download_ready() and not await self._is_export_processing():
                    if await self._click_request_export_button():
                        logger.info("Requested a new export (replacing stale ready file).")
                        requested = True
                    else:
                        return {
                            "status": "error",
                            "message": (
                                "Oura still shows an old export ready to download and will not "
                                "start a new one. Open membership.ouraring.com/data-export, "
                                "request a new export, wait for the email, then try Sync now again."
                            ),
                        }
                elif await self._is_export_processing():
                    logger.info("Oura is already generating an export — will keep checking later.")
                    already_processing = True
                elif await self._click_request_export_button():
                    logger.info("Export requested.")
                    requested = True
                else:
                    logger.info("Could not click request; Oura may already be generating an export.")
                    already_processing = True
            else:
                if await self._click_request_export_button():
                    logger.info("Export requested.")
                    requested = True
                else:
                    logger.info("Export might already be requested or button not found.")
                    already_processing = True

            if not wait_for_ready:
                if requested:
                    return {"status": "export_requested"}
                if already_processing:
                    return {"status": "export_processing"}
                return {
                    "status": "error",
                    "message": "Could not confirm an export request on Oura.",
                }

            is_ready = await self._wait_for_processing(
                require_processing_first=skip_ready_download,
            )
            if not is_ready:
                logger.warning("Timed out waiting for export processing.")
                return {
                    "status": "error",
                    "message": (
                        "Oura has not finished generating a new export yet. "
                        "If you received the ready email, try Sync now again in a minute."
                    ),
                }

            return await self._download_file(save_dir)

        except Exception as e:
            logger.error(f"Request automation failed: {e}", exc_info=True)
            return {
                "status": "error",
                "message": f"Oura export automation failed: {e}",
            }

    async def download_existing_export(self, save_dir: str) -> Optional[str]:
        """
        Attempts to download an existing export without requesting a new one.
        Useful for quick checks or retrying a download.
        """
        logger.info("Starting Download Only Flow...")
        if not self._is_initialized:
            await self.initialize()

        if not self.page:
            self.page = await self.context.new_page()

        try:
            if not await self._navigate_to_export_page():
                # Check if stuck on Login/OTP — submit email so Oura sends the code
                if "login" in self.page.url or "authn" in self.page.url:
                    login_res = await self.login()
                    if login_res and login_res.get("status") == "otp_required":
                        return {"status": "otp_required"}
                    # Login succeeded, retry navigation
                    if not await self._navigate_to_export_page():
                        return {"status": "error", "message": "Could not open Oura data export page."}
                else:
                    return {"status": "error", "message": "Could not open Oura data export page."}

            if not await self._is_export_download_ready():
                return {
                    "status": "error",
                    "message": "No downloadable export on Oura right now. Request a new export first.",
                }

            return await self._download_file(save_dir)

        except Exception as e:
            logger.error(f"Download automation failed: {e}")
            return {"status": "error", "message": str(e)}

    async def _navigate_to_export_page(self) -> bool:
        """Navigates to the export page, handling potential login redirects and re-tries."""
        logger.info(f"Navigating to {self.export_url}")
        await self.page.goto(self.export_url, timeout=60000)
        
        # Poll for URL correctness (handling redirects)
        for _ in range(10): # 10s timeout
            try:
                await self.page.wait_for_load_state("networkidle", timeout=2000)
            except: 
                await self._ensure_page_alive()
                
            current_url = self.page.url
            if "/data-export" in current_url:
                logger.info("Successfully arrived at data-export page.")
                await self._dismiss_cookie_banners()
                return True
            
            # Handle Login Redirect — don't auto-login, surface to user
            if "login" in current_url or "authn" in current_url:
                logger.warning("Redirected to login — session expired.")
                return False
            
            # Handle Home Page redirect (sometimes happens on first load)
            elif current_url.rstrip('/') == self.base_url:
                logger.info("Landed on Home Page. Retrying navigation to Export...")
                await self.page.goto(self.export_url, timeout=30000)
                
            await self.page.wait_for_timeout(1000)

        # Final check
        if "/data-export" not in self.page.url:
             logger.warning(f"Failed to reach export page. Current URL: {self.page.url}")
             return False
             
        return True

    async def _click_request_export_button(self) -> bool:
        """Finds and clicks the 'Request data export' button, handling various states (disabled, aria attributes)."""
        await self._dismiss_cookie_banners()
        await self.page.wait_for_timeout(1000)
        
        # Find Request Button (Try likely selectors)
        target_btn = self.page.locator('[data-testid="pageSubtitle"] + button').first
        try:
             await target_btn.wait_for(state="visible", timeout=5000)
        except:
             pass

        if not await target_btn.is_visible():
            target_btn = self.page.locator('main button').first
            try:
                 await target_btn.wait_for(state="visible", timeout=5000)
            except:
                 pass

        if not await target_btn.is_visible():
            return False

        # Wait briefly for hydration
        await self.page.wait_for_timeout(5000)

        # Check if explicitly disabled in DOM
        is_disabled = await target_btn.get_attribute("disabled") is not None
        aria_disabled = await target_btn.get_attribute("aria-disabled") == "true"

        if is_disabled or aria_disabled:
             return False

        # Attempt Click 
        try:
            # We try to wait for enabled state, but don't strictly block on it in case of UI quirks
            try:
                 await target_btn.wait_for(state="enabled", timeout=3000)
            except:
                 pass 
            
            logger.info("Found Request button. Clicking...")
            await target_btn.click(timeout=5000)
            
            # Wait for state change confirmation
            await self.page.wait_for_timeout(2000)
            return True
        except Exception as e:
            logger.error(f"Click failed: {e}")
            return False

    async def _wait_for_processing(self, *, require_processing_first: bool = False) -> bool:
        """Polls until the export is ready (download button appears)."""

        saw_processing = not require_processing_first
        # Fast polls first — email often arrives within a few minutes.
        for i in range(24):  # ~12 minutes at 30s
            if await self._is_export_processing():
                saw_processing = True
            if await self._is_export_download_ready() and saw_processing:
                logger.info("Export ready during fast polling.")
                return True
            logger.info(f"Processing... fast check {i + 1}/24")
            await self.page.wait_for_timeout(30_000)
            try:
                await self.page.reload(timeout=30_000)
                await self.page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception as e:
                logger.warning(f"Page reload failed: {e}")

        # Slow polls for long Oura generation queues.
        max_retries = 24  # ~2 hours at 5 minutes
        poll_interval = 300
        for i in range(max_retries):
            if await self._is_export_processing():
                saw_processing = True
            if await self._is_export_download_ready() and saw_processing:
                logger.info("Export ready during slow polling.")
                return True
            logger.info(f"Processing... slow check {i + 1}/{max_retries}")
            await self.page.wait_for_timeout(poll_interval * 1000)
            try:
                await self.page.reload(timeout=30_000)
                await self.page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception as e:
                logger.warning(f"Page reload failed: {e}")

        return False

    async def _dismiss_cookie_banners(self):
        """Dismisses cookie consent banners that may block UI elements."""
        try:
            # Common cookie consent button patterns
            dismiss_btns = [
                "button:has-text('Accept All Cookies')",
                "button:has-text('Accept All')",
                "button:has-text('Accept Necessary')",
                "button:has-text('Accept')",
                "button:has-text('Allow All')",
                "button:has-text('OK')",
                "button:has-text('Got it')",
                "button:has-text('Agree')",
                "[aria-label='Accept cookies']",
                "[aria-label='Accept all cookies']",
            ]
            for sel in dismiss_btns:
                try:
                    btn = self.page.locator(sel).first
                    if await btn.is_visible(timeout=1000):
                        await btn.click()
                        logger.info(f"Dismissed cookie banner via: {sel}")
                        await self.page.wait_for_timeout(1000)
                        return True
                except Exception:
                    continue
            return False
        except Exception as e:
            logger.debug(f"Cookie banner dismissal skipped: {e}")
            return False

    async def _download_file(self, save_dir: str) -> Optional[str]:
        """Finds the download button and handles the file save dialog."""
        # Dismiss any cookie banners that might obscure the download button
        await self._dismiss_cookie_banners()
        await self.page.wait_for_timeout(1000)
        
        # Try multiple selectors for the download button (Oura's UI varies)
        download_selectors = [
            "button[aria-label='Download data']",
            "button[aria-label='Download your data']",
            "button:has-text('Download your data')",
            "button:has-text('Download data')",
            "button:has-text('Download')",
            "a[download]",
            "a:has-text('Download')",
            "main button:has-text('Download')",
        ]
        download_btn = None
        for sel in download_selectors:
            btn = self.page.locator(sel).first
            try:
                if await btn.is_visible(timeout=3000):
                    download_btn = btn
                    logger.info(f"Download button found via selector: {sel}")
                    break
            except Exception:
                continue
        
        if not download_btn:
            # Dump page state for debugging
            buttons = await self.page.locator('button').all()
            btn_texts = []
            for b in buttons:
                try:
                    if await b.is_visible():
                        text = (await b.inner_text()).strip()
                        aria = await b.get_attribute('aria-label') or ''
                        btn_texts.append(f"'{text}' aria={aria}")
                except Exception:
                    pass
            logger.warning(f"Download button not found. Visible buttons: {btn_texts}")
            return {
                "status": "error",
                "message": "Could not find Oura's download button on the export page.",
            }

        logger.info("Download button found. Clicking...")
        async with self.page.expect_download(timeout=30000) as download_info:
            await download_btn.click()
        
        download = await download_info.value
        filename = download.suggested_filename
        save_path = os.path.join(save_dir, filename)
        await download.save_as(save_path)
        logger.info(f"Downloaded to {save_path}")
        return save_path

automator = OuraAutomator()
