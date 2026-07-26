# Step 6: Move Timeline Battery Data and Ring Status

## Current problem

`buildDaySummary()` adds every ring battery sample to `summary.timeline`, and `ContextRail` renders them in the right rail. That consumes too much space for a data type that should be shown in its own view.

`ContextRail` also contains the Ring Status card, so once the timeline is removed the rail becomes sparse.

## Decision

Move Ring Status into the top bar. Move battery history into a dedicated Battery screen opened by clicking the battery percentage. Remove battery samples from `Today` timeline data.

## Files to touch

- `frontend/src/lib/day-summary.ts`
- `frontend/src/types/app-view.ts`
- `frontend/src/components/layout/AppShell.tsx`
- `frontend/src/components/layout/TopDateBar.tsx`
- `frontend/src/components/layout/HealthSidebar.tsx`
- `frontend/src/components/layout/ContextRail.tsx`
- `frontend/src/components/views/BatteryView.tsx`

## Data model steps

1. Add `batterySamples` to `DaySummary`.

2. Keep `battery` and `batteryTimestamp` as latest-sample helpers.

3. Remove battery samples from `timeline`.

4. Ensure `batterySamples` are sorted by timestamp before deriving latest battery.

## Navigation steps

1. Add `battery` to `AppView`.

2. Add a `BatteryView` screen.

3. In `AppShell.tsx`, render `BatteryView` for `activeView === "battery"`.

4. Remove the right `ContextRail` from the active health views once battery timeline content is gone.

5. Stop passing battery props to `HealthSidebar`.

## Top bar steps

1. Extend `TopDateBarProps` with a ring-status payload that includes battery, timestamp, and click handler.

2. Render a compact Ring Status button near the backend/sync indicators:

   - `BatteryMedium` icon or equivalent
   - `--%` when no sample exists
   - latest sample time when present
   - green above 30%, yellow at 21-30%, coral at 20% or less
   - click opens the Battery screen

3. Preserve the existing date navigation and sync indicators.

## Battery screen steps

`BatteryView` must show:

- current selected date
- latest battery percentage and timestamp
- charging/in-charger state when present
- selected-day sample list
- selected-day min, max, first, last
- 30-day battery trend from `api.getQuery("ring_battery.level", start, end)`
- hover tooltip on the 30-day trend with date/time and percentage

## Acceptance checks

- "Today's Timeline" no longer appears in the right rail.
- Battery samples no longer appear in `summary.timeline`.
- There is no empty right rail on the main health views.
- Ring Status appears in the top bar.
- Clicking battery opens the Battery screen.
- Battery screen shows selected-day samples and a 30-day trend.

