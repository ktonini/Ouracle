# Step 7: Explorer Auto-Correlations

## Current problem

`ExplorerView.tsx` defaults to the manual Correlate tab and only computes one user-selected pair. The backend already has pairwise correlation support, but the UI does not surface interesting relationships automatically.

## Decision

Explorer should open on a new `Discover` tab that automatically computes and presents curated interesting correlations. Manual correlation remains available as the second tab.

## Files to touch

- `backend/src/analysis/interesting_correlations.py`
- `backend/src/api/analysis.py`
- `backend/tests/*` for correlation coverage
- `frontend/src/lib/api.ts`
- `frontend/src/components/views/ExplorerView.tsx`
- `frontend/src/components/analysis/InterestingCorrelationsPanel.tsx`

## Backend implementation

1. Add `backend/src/analysis/interesting_correlations.py`.

2. Define curated candidate relationships:

   ```python
   CANDIDATES = [
       ("sleep_session.bedtime_start_minutes", "readiness.score", 1, "Later bedtime vs next-day readiness"),
       ("sleep_session.total_sleep_duration", "readiness.score", 1, "Sleep duration vs next-day readiness"),
       ("sleep_session.efficiency", "readiness.score", 1, "Sleep efficiency vs next-day readiness"),
       ("sleep_session.average_hrv", "readiness.score", 0, "HRV vs same-day readiness"),
       ("sleep_session.average_heart_rate", "readiness.score", 0, "Resting HR vs same-day readiness"),
       ("activity.steps", "sleep.score", 0, "Steps vs same-night sleep"),
       ("activity.steps", "readiness.score", 1, "Steps vs next-day readiness"),
       ("activity.sedentary_time", "sleep.score", 0, "Sedentary time vs sleep"),
       ("activity.active_calories", "sleep.score", 0, "Active calories vs sleep"),
       ("readiness.temperature_deviation", "sleep.score", 0, "Temperature deviation vs sleep"),
   ]
   ```

3. Implement `find_interesting_correlations(db, start, end, limit=6, min_abs=0.25, min_samples=21)`.

4. For each candidate:

   - build X and Y series over the requested range
   - call `compute_correlation(...)`
   - skip null coefficients
   - skip sample counts below `min_samples`
   - skip absolute coefficients below `min_abs`
   - skip `warning == "low_samples"`
   - score as `abs(coefficient) * min(sample_count / 60, 1.0)`
   - include metric labels from `METRIC_CATALOG`
   - sort by score descending
   - return the top `limit`

5. Add an endpoint in `backend/src/api/analysis.py`:

   ```python
   @router.get("/interesting-correlations")
   ```

   with `start_date`, `end_date`, `limit`, `min_abs`, and `min_samples` query params.

6. Add tests for:

   - seeded bedtime/readiness data returns the bedtime candidate
   - weak correlations are filtered out
   - low sample counts are filtered out
   - response includes labels, reason, lag, coefficient, and sample count

## Frontend implementation

1. Add an `InterestingCorrelation` interface and `api.getInterestingCorrelations(...)` in `frontend/src/lib/api.ts`.

2. Update `ExplorerView.tsx`:

   - change tab type to `discover | correlate | anomalies | saved`
   - default tab is `discover`
   - use the selected range to compute `startDate` and `endDate`
   - load interesting correlations when tab or range changes

3. Add `InterestingCorrelationsPanel` under `frontend/src/components/analysis/`.

4. Panel UI:

   - card per result
   - show title/reason
   - show coefficient, sample count, lag
   - show interpretation
   - use color by coefficient sign and strength
   - include an `Inspect` button

5. `Inspect` behavior:

   - set `xMetric`, `yMetric`, and `lag` to the selected result
   - switch tab to `correlate`
   - let the existing `CorrelationPanel` recompute and show full details

6. Empty state:

   - `No strong correlations found over this range. Try 180d.`

## Acceptance checks

- Opening Explorer shows Discover first.
- With seeded correlated data, Discover shows at least one card.
- Clicking Inspect opens the manual Correlate tab with the selected metrics and lag.
- Existing Correlate, Anomalies, and Saved behavior still works.

