# Step 3: Add Hover-Seek to Trend Tiles

## Current problem

The compact trend tiles are `MiniTrendStrip` instances in `frontend/src/components/views/TodayView.tsx`. They render a static SVG line and do not respond to cursor position.

## Decision

Implement hover-seek on `MiniTrendStrip` itself so every compact trend strip gets the behavior. Hover must show:

- nearest sample date
- nearest sample value
- vertical hairline
- point marker

The layout must not resize while hovering.

## Files to touch

- `frontend/src/components/health/MiniTrendStrip.tsx`
- `frontend/src/components/views/TodayView.tsx`

## Implementation steps

1. Add `hoverIndex` state to `MiniTrendStrip`.

2. Change the SVG to use a fixed `viewBox` and `preserveAspectRatio="none"`, keeping a stable display height.

3. Add pointer handlers:

   - `onPointerMove`: compute pointer X relative to bounds, convert to an index with `Math.round((x / bounds.width) * (data.length - 1))`, and clamp to valid range
   - `onPointerLeave`: clear `hoverIndex`

4. When hovering, render:

   - a vertical `<line>` at the hovered sample X
   - a small `<circle>` at the hovered sample Y
   - an absolutely positioned tooltip above the strip

5. Format tooltip date:

   - daily `YYYY-MM-DD` -> `MMM d, yyyy`
   - timestamp -> `MMM d, HH:mm`

6. Format value:

   - integer values as whole numbers
   - decimals with one decimal place

7. Keep the root ready to become a button in the next step.

## Acceptance checks

- Moving across a Today trend strip updates the date/value continuously.
- Hovering first and last samples works.
- Leaving the strip hides the overlay.
- No row height changes during hover.

