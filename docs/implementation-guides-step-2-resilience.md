# Step 2: Populate Stress and Resilience

## Current problem

`frontend/src/components/views/ResilienceView.tsx` only reads `raw.resilience` for the selected day. The local database has resilience rows through `2026-02-16`, while sleep/readiness/activity continue into late May 2026, so the screen is blank on recent dates.

Backend ingestion also assumes the resilience file is exactly `dailyresilience.csv` and that resilience values always live in the `contributors` JSON.

## Decision

The Stress and Resilience screen must populate from the best available local data:

1. selected-day resilience row, if present
2. latest resilience row on or before the selected day, clearly labelled as `latest available`
3. selected-day readiness stress/recovery summary, if present
4. selected-day daytime stress series from `activity.stress`, if present

Only show the empty state when none of those sources exists.

## Files to touch

- `backend/src/ingestion/manager.py`
- `backend/src/ingestion/processors/readiness.py`
- `backend/tests/*` for resilience ingest coverage
- `frontend/src/components/views/ResilienceView.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/day-summary.ts` if you want a shared helper

## Backend ingestion implementation

1. In `backend/src/ingestion/manager.py`, support all of these filenames:

   - `dailyresilience.csv`
   - `daily_resilience.csv`
   - `resilience.csv`

2. Process the first existing non-empty file. If multiple are present, concatenate them, drop duplicate `day` values keeping the last row, then process.

3. In `backend/src/ingestion/processors/readiness.py`, make `process_resilience()` accept both shapes:

   - values inside `contributors`
   - top-level columns

4. Use these field fallbacks:

   - day: `day`, `date`
   - level: `level`, `resilience_level`, `resilience`
   - sleep recovery: `sleep_recovery`, `sleepRecovery`, `contributors.sleep_recovery`
   - daytime recovery: `daytime_recovery`, `daytimeRecovery`, `contributors.daytime_recovery`
   - stress: `stress`, `stress_score`, `contributors.stress`

5. Normalize `level` to a non-empty string or `None`.

6. Add tests for:

   - top-level resilience values are inserted
   - contributor-JSON resilience values are inserted
   - duplicate days keep the last row

## Frontend implementation

1. Replace `ResilienceView.tsx` with a data-driven view that can fetch and merge resilience history.

2. Keep selected-day `raw.resilience`, but normalize both object and array shapes through a helper.

3. Fetch history for the last 365 days up to the selected date using:

   - `api.getQuery("resilience.level", start, end)`
   - `api.getQuery("resilience.sleep_recovery", start, end)`
   - `api.getQuery("resilience.daytime_recovery", start, end)`
   - `api.getQuery("resilience.stress", start, end)`

4. Merge by date and select the latest row with any usable value.

5. Render in this order:

   - header with selected date
   - resilience level hero
   - three metric tiles: Sleep recovery, Daytime recovery, Stress load
   - if using fallback history, show `Latest available: YYYY-MM-DD`
   - selected-day stress/recovery balance from `raw.readiness.stress_high` and `raw.readiness.recovery_high` when present
   - daytime stress strip from `raw.activity.stress` when it is an array of timestamped samples
   - 90-day mini trend lines for the three resilience numeric fields

6. Never pretend fallback data is from the selected day. Always show the source date when you fall back.

## Acceptance checks

- A selected day with resilience data shows the level and three metrics.
- Selecting `2026-05-29` shows the latest available resilience row and its date instead of a blank page.
- If resilience rows are absent but readiness stress/recovery exists, the stress/recovery section still renders.
- Empty state appears only when no resilience, readiness stress/recovery, or daytime stress data exists.

