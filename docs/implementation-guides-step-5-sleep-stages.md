# Step 5: Add Detail to the Sleep Stage Bar

## Current problem

`SleepView.tsx` shows only aggregate stage totals. The backend already parses detailed sleep-stage arrays and exposes them through `SleepSessionResponse`.

## Decision

Use epoch-level sleep phase data when available. Prefer `sleep_phase_30_sec`, fall back to `sleep_phase_5_min`, then fall back to the current aggregate bar.

Stage code mapping:

- `1` = Deep
- `2` = Light
- `3` = REM
- `4` = Awake

## Files to touch

- `frontend/src/lib/sleep-stages.ts`
- `frontend/src/components/views/SleepView.tsx`
- `frontend/src/lib/api.ts` if you need a typed helper

## Implementation steps

1. Add a helper module that can build sleep stage segments from a session object.

2. Implement:

   ```ts
   export interface SleepStageSegment {
     stage: "deep" | "light" | "rem" | "awake";
     label: string;
     start: Date;
     end: Date;
     minutes: number;
     colorClass: string;
   }

   export function buildSleepStageSegments(session: any): {
     source: "30_sec" | "5_min" | "aggregate";
     segments: SleepStageSegment[];
     totals: Record<string, number>;
   }
   ```

3. Segment algorithm:

   - pick `sleep_phase_30_sec` if it is non-empty, with a 30-second interval
   - else pick `sleep_phase_5_min`, with a 300-second interval
   - normalize each item from `{ timestamp, value }`
   - drop null or unknown values
   - sort by timestamp
   - merge adjacent epochs with the same stage
   - segment end is the next epoch timestamp, or start plus interval for the last epoch
   - minutes are `(end - start) / 60000`

4. If detailed totals differ from aggregate durations by more than 20 minutes, still render the detailed view and show a subtle note that export detail differs from summary totals.

5. Update `SleepView.tsx` to render the detailed bar, legend, hover state, start/end labels, and a disturbance rail from `movement_30_sec` when present.

6. Keep the old aggregate fallback so older exports still render.

## Acceptance checks

- A session with `sleep_phase_30_sec` shows many stage transitions, not four aggregate blocks.
- Hovering a stage segment shows time range and duration.
- Sessions with only `sleep_phase_5_min` still render detailed transitions.
- Sessions without phase arrays still render the old aggregate summary.

