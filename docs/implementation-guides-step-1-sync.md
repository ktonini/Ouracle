# Step 1: Fix Next Auto-Sync

## Current problem

`frontend/src/components/dashboard/SettingsPanel.tsx` formats `automation.nextRun` with `formatDistanceToNow(..., { addSuffix: true })`, which can produce nonsense like "about 2 hours ago" for a future schedule concept when the backend status is stale.

The backend computes `next_run` in `backend/src/api/main.py` inside `background_worker()`, but `/api/automation/check-status` can return a stale persisted value before the worker refreshes it.

## Decision

The backend must always return a future `next_run`. The frontend must also guard against stale or past values so the UI never shows an "ago" suffix for a future schedule concept.

## Files to touch

- `backend/src/scheduling.py`
- `backend/src/api/main.py`
- `backend/src/api/routes.py`
- `backend/src/insights/sync_freshness.py`
- `backend/tests/test_*` for scheduling and status behavior
- `frontend/src/lib/sync-display.ts`
- `frontend/src/components/dashboard/SettingsPanel.tsx`

## Backend implementation

1. Add `backend/src/scheduling.py` with a pure helper:

   ```python
   from datetime import datetime, timedelta

   def compute_next_daily_run(now: datetime, schedule_time: str) -> datetime:
       try:
           hour, minute = map(int, schedule_time.split(":"))
           if hour < 0 or hour > 23 or minute < 0 or minute > 59:
               raise ValueError
       except Exception:
           hour, minute = 11, 0

       candidate = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
       if candidate <= now:
           candidate += timedelta(days=1)
       return candidate
   ```

2. In `backend/src/api/main.py`, replace the inline next-run calculation in `background_worker()` with `compute_next_daily_run(now, schedule_time_str)`.

3. In `backend/src/api/routes.py`, make `check_status()` compute a fresh future `next_run` from `config_manager.get_config()` before returning. Do not depend on the background worker having run recently.

4. In `backend/src/insights/sync_freshness.py`, use the same computed future next-run value instead of a raw persisted config value.

5. Add backend tests for:

   - later today returns today
   - already passed returns tomorrow
   - exact same minute returns tomorrow
   - invalid schedule falls back to 11:00

## Frontend implementation

1. Add `nextAutoSyncLabel(nextRun, scheduleTime)` to `frontend/src/lib/sync-display.ts`.

2. Behavior:

   - parse `nextRun`
   - if invalid and no `scheduleTime`, return `null`
   - if parsed time is in the past, recompute the next future occurrence from `scheduleTime`
   - if the resulting time is less than 60 seconds away, return `due now`
   - otherwise return `in ...` using `formatDistanceToNowStrict(..., { addSuffix: false })`

3. Replace the existing `formatDistanceToNow(parseLocalDate(automation.nextRun), { addSuffix: true })` in `SettingsPanel.tsx` with the helper above.

4. Render `Next auto-sync: {label}` and never render a label containing `ago`.

## Acceptance checks

- Settings never shows "Next auto-sync: ... ago".
- Changing the daily sync time updates the label to the next occurrence of that time.
- Backend tests for the schedule helper pass.

