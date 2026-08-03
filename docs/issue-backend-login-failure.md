# Issue: Backend Login & Download Failures — Postmortem

**Date:** 2026-05-18 → 2026-05-19
**Severity:** High
**Component:** Backend (`backend/src/automation.py`, `backend/src/api/main.py`, `backend/src/api/routes.py`)
**Final Status:** ✅ Resolved — all login, download, and ingestion paths verified

---

## Summary

The Oura login and data-sync flow broke across two phases:

1. **Phase 1 — Login HTTP 500**: Clicking "Log in" returned HTTP 500 with empty `detail`. The Playwright Chromium browser was missing from the custom install path, and the install check was fooled by stale marker files.

2. **Phase 2 — Download timeout + crash**: After login succeeded, the data export download failed with "No file downloaded (timeout?)" because a cookie-consent banner obscured the download button. The backend then crashed because a non-critical parser error in `sleepmodel.csv` propagated unhandled.

---

## Root Causes (in order discovered)

### #1 — Browser install check fooled by stale marker files
`_ensure_browser_installed()` checked `os.listdir(self.browser_dir)`. The custom browser directory (`AppData\Roaming\CrackedOura\browsers`) contained versioned subdirs (`chromium_headless_shell-1208/`) with **only marker files** (`INSTALLATION_COMPLETE`, `DEPENDENCIES_VALIDATED`) from an interrupted previous install. The check passed, `chromium.launch()` failed, and the error propagated with `str(e) == ""`.

### #2 — Stale `_login_in_progress` blocked email dispatch
When the first `start_login()` call crashed (500), `_login_in_progress` stayed `True`. The second call returned `{"status":"otp_required","message":"already in progress..."}` **without clicking "Send Code"** — no OTP email was ever sent. The frontend showed the OTP input and the user waited for a phantom email.

### #3 — Page closed during Oura navigation redirects
Oura's login flow triggers multi-step navigation redirects. After clicking "Continue" or "Send Code", the Playwright page object was invalidated. Subsequent calls to `self.page.wait_for_timeout()` / `wait_for_load_state()` raised `Target page, context or browser has been closed`.

### #4 — `_is_logged_in()` rejected the Oura OAuth redirect chain
After successful OTP submission, Oura redirects through:
```
moi.ouraring.com/authn/.../enter-otp
  → oauth-authorize (code exchange)
  → membership.ouraring.com/login?code=...   ← contains "login"!
  → membership.ouraring.com/  (dashboard)
```
The check `"login" not in url` falsely rejected the transient redirect URL, so the backend kept retrying login even though the user was authenticated.

### #5 — Cookie consent banner blocked download button
Oura's export page at `membership.ouraring.com/data-export` shows a cookie consent overlay on first visit. The download button (`button[aria-label='Download data']`) exists but is **not visible** until the banner is dismissed. The old code had no cookie dismissal logic.

### #6 — Session path lost between process restarts
`storage_state_path` used `os.getcwd()` which varies by launch context:
- When launched from the Electron app: `C:\Users\...\AppData\Local\Programs\Cracked Oura\resources\backend\`
- When launched from CLI: `C:\Users\...\VSCodeProjects\Cracked-Oura\backend\`

This meant a login session saved by the Electron app was invisible to the CLI test, and vice versa.

### #7 — Parser crash killed the backend process
The Oura export zip contains a `sleepmodel.csv` file that triggered an unhandled exception in `process_sleep_session()`. Since `process_ingestion()` didn't wrap the parser call in try/except, the exception crashed the entire backend process — even though all the main data (sleep, activity, readiness, heart rate, temperature) had already been successfully ingested.

### #8 — `cleanup()` crashed on already-closed resources
`automator.cleanup()` called `context.close()`, `browser.close()`, and `playwright.stop()` unconditionally. If any of these were already closed (common after a page-navigation crash), the next call in the chain threw, propagating a fresh crash during cleanup.

---

## Fixes Applied (14 total across 3 files)

### `backend/src/automation.py` (11 fixes)

| # | Method | Fix |
|---|--------|-----|
| 1 | `_ensure_browser_installed()` | Use `glob.glob()` to check for actual `.exe` files, not just dir contents |
| 2 | `initialize()` retry | Inner retry has its own try/except with descriptive error message |
| 3 | `initialize()` | Wrap `_ensure_browser_installed()` call in try/except |
| 4 | `start_login()` | On duplicate call, cleanup and **restart** the flow (clicks "Send Code" again) |
| 5 | `_is_logged_in()` | Accept `ouraring.com` URLs without `authn`/`login`/`enter-otp` |
| 6 | `submit_otp()` | Wait up to 20s with polling for Oura's redirect chain to complete |
| 7 | `submit_otp()` | Expand error text to include `"Incorrect or expired code"`, `"try again"` |
| 8 | `submit_otp()` | Remove `dispatch_event('input')` that raced with Oura's auto-submit JS |
| 9 | `_check_otp_screen()` + `_click_submit()` | Use `_ensure_page_alive()` before every wait to recover from page closures |
| 10 | `_download_file()` + `_navigate_to_export_page()` | Add `_dismiss_cookie_banners()` to accept cookie consent overlays |
| 11 | `cleanup()` | Each resource close in its own try/except; null references after close |

### `backend/src/api/main.py` (2 fixes)

| # | Method | Fix |
|---|--------|-----|
| 12 | `run_download_existing_task()` + `run_ingestion_task()` | Always reinitialize browser for a fresh session; handle error dicts properly |
| 13 | `process_ingestion()` | Wrap parser call in try/except — partial failures don't crash the process |

### `backend/src/api/routes.py` (1 fix)

| # | Method | Fix |
|---|--------|-----|
| 14 | `run_full_sync_task()` | Wrap parser call in try/except for resilience |

### New infrastructure

| Addition | Purpose |
|----------|---------|
| `_ensure_page_alive()` | Recovers from page closure by grabbing latest page from context. Called before any `page.wait_*()` |
| `_dismiss_cookie_banners()` | Clicks "Accept All Cookies" / "Accept Necessary" / etc. on known consent button patterns |
| Session path fix | `storage_state_path` now uses `get_user_data_dir()` → `AppData\Roaming\CrackedOura\oura_session.json` |

---

## Oura Login Flow (current, verified)

```
1. POST /api/automation/start-login  {"email":"user@example.com"}
   └─ Playwright browser launches
   └─ Navigates to membership.ouraring.com/login
   └─ Fills input[name='username'], clicks button[type='submit']
   └─ Clicks button[name='selectedId'] ("Send code") on intermediate page
   └─ Returns {"status":"otp_required","message":"OTP required"}
   └─ Oura sends 6-digit code to user's email

2. User enters code → POST /api/automation/submit-otp  {"otp":"123456","action":"run"}
   └─ Fills input[name='otp'], clicks #submit-button
   └─ Waits for Oura redirect chain (up to 20s)
   └─ On success: saves session, spawns run_ingestion_task or run_download_existing_task
   └─ Returns {"status":"success","message":"OTP Accepted. Resuming..."}

3. Background task navigates to membership.ouraring.com/data-export
   └─ Dismisses cookie banner
   └─ Finds download button, clicks, saves zip to AppData\Roaming\CrackedOura\
   └─ Parses zip into SQLite database
   └─ Updates status to "Idle"
```

---

## Data Verification (2026-05-19)

```
Database: C:\Users\<user>\AppData\Roaming\CrackedOura\oura_database.db

  sleep              1,152 records
  activity           1,188 records
  readiness          1,156 records
  resilience           730 records
  sleep_session      1,248 records
  heart_rate     1,019,288 records
  temperature    1,502,334 records
  cardiovascular_age   725 records
```

---

## Deployment

All fixes compiled via PyInstaller into `backend.exe` and deployed to:
```
C:\Users\<user>\AppData\Local\Programs\Cracked Oura\resources\backend\backend.exe
```

## Lessons Learned

1. **Never trust directory existence as proof of installation.** Stale marker files from interrupted installs produce false positives. Always check for the actual binary.

2. **CWD-dependent paths break in desktop apps.** Electron spawns child processes with unpredictable CWD. Use `%APPDATA%`-based paths for any persistent state.

3. **Cookie consent overlays are automation kryptonite.** Any headless browser automation of a GDPR-compliant site must handle consent banners before interacting with page elements. Logging visible buttons when a selector fails is invaluable for diagnosing this.

4. **Page closures are normal during SPA navigation.** Playwright's page object can become invalid during redirects. A safe `_ensure_page_alive()` helper avoids cascading failures.

5. **Ingestion should be defensive.** A malformed CSV file in an Oura export zip shouldn't crash the entire backend. Wrap ingestion in try/except and report partial success.

6. **Cleanup must be idempotent.** Calling `close()` on already-closed browser resources is a common failure mode. Each resource should be in its own try/except.
