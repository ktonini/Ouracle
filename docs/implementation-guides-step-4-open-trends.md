# Step 4: Open Trend Tiles Into Full Trend View

## Current problem

The Today trend strips do not open `TrendsView`, and `TrendsView` has local metric state that cannot be seeded from another screen.

## Decision

Clicking a compact trend tile opens `TrendsView` with that exact metric selected and a matching 30-day range. This is app state, not URL routing.

## Files to touch

- `frontend/src/contexts/DashboardContext.tsx`
- `frontend/src/components/layout/AppShell.tsx`
- `frontend/src/components/views/TodayView.tsx`
- `frontend/src/components/health/MiniTrendStrip.tsx`
- `frontend/src/components/views/TrendsView.tsx`

## State contract

Add this to dashboard context:

```ts
export interface TrendFocus {
  metricId: string;
  label?: string;
  color?: string;
  rangeDays?: number;
  endDate?: string;
}
```

Expose:

```ts
trendFocus: TrendFocus | null;
setTrendFocus: (focus: TrendFocus | null) => void;
```

## Implementation steps

1. Add `trendFocus` state to `DashboardContext`.

2. In `TodayView.tsx`, keep the existing `onNavigate` prop, read `setTrendFocus` from `useDashboard()`, and pass an `onOpen` callback to each `MiniTrendStrip` that sets the focus and then navigates to `trends`.

3. Use these focus values:

   - Sleep: `sleep.score`, `Sleep`, `#A2D3E8`
   - Readiness: `readiness.score`, `Readiness`, `#4ECDC4`
   - Activity: `activity.score`, `Activity`, `#FFD166`

4. Update `MiniTrendStripProps` with `onOpen?: () => void`, render the root as a `<button type="button">` when provided, and let button semantics handle Enter/Space.

5. In `TrendsView.tsx`, read `trendFocus` from `useDashboard()`, select the matching preset when it changes, and set the range to `trendFocus.rangeDays ?? 30`.

6. Do not clear `trendFocus` immediately. Leave it in state until the user intentionally changes the metric.

## Acceptance checks

- Clicking Sleep trend on Today opens Trends with Sleep Score selected.
- Clicking Activity trend opens Trends with Activity Score selected.
- Keyboard focus and Enter activate the same behavior.
- Manually changing the metric inside Trends still works.

