import { useMemo, useState } from 'react';
import { useDashboard } from '@/contexts/DashboardContext';
import { buildDaySummary } from '@/lib/day-summary';
import {
  SLEEP_STAGE_DETAIL_STORAGE_KEY,
  SLEEP_STAGE_LEGEND_ORDER,
  buildMovementMarkers,
  buildSleepStageSegments,
  formatSegmentRange,
  formatStageMinutes,
  readSleepStageDetailPreference,
  sleepStageDetailLabel,
  type SleepStageDetailPreference,
  type SleepStageSegment,
} from '@/lib/sleep-stages';
import { ScoreRing } from '@/components/health/ScoreRing';
import { MetricPill } from '@/components/health/MetricPill';
import { TimelineList } from '@/components/health/TimelineList';
import { Moon, Heart, Clock, Sun, Sunset, Zap } from 'lucide-react';
import { format } from 'date-fns';
import { useInsights } from '@/hooks/useInsights';
import { BaselineTable, ContributorGrid } from '@/components/health/InsightsPanels';

const SLEEP_BASELINE_METRICS = new Set([
  'sleep_score',
  'total_sleep_minutes',
  'hrv',
  'resting_hr',
]);

function primarySleepSessionFromRaw(raw: unknown) {
  if (!raw || typeof raw !== 'object') return null;
  const rec = raw as Record<string, unknown>;
  const sessions = rec.sleep_sessions;
  if (Array.isArray(sessions) && sessions.length > 0) return sessions[0];
  return rec.sleep_session ?? null;
}

const DETAIL_OPTIONS: { value: SleepStageDetailPreference; label: string; hint: string }[] = [
  { value: 'auto', label: 'Auto', hint: 'Finest export available' },
  { value: '30_sec', label: '30s', hint: 'Maximum detail' },
  { value: '5_min', label: '5m', hint: 'Smoother bar' },
  { value: 'summary', label: 'Summary', hint: 'Deep / REM / light / awake totals' },
];

function SleepStagesCard({ session }: { session: unknown }) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [detailPref, setDetailPref] = useState<SleepStageDetailPreference>(() =>
    readSleepStageDetailPreference(),
  );

  const stageBuild = useMemo(
    () => buildSleepStageSegments(session, detailPref),
    [session, detailPref],
  );
  const movementMarkers = useMemo(() => buildMovementMarkers(session), [session]);

  const { segments, totals, source, totalsMismatchNote } = stageBuild;
  const totalMinutes = segments.reduce((sum, s) => sum + s.minutes, 0);

  if (segments.length === 0 || totalMinutes <= 0) return null;

  const rangeStart = segments[0].start;
  const rangeEnd = segments[segments.length - 1].end;
  const rangeMs = Math.max(rangeEnd.getTime() - rangeStart.getTime(), 1);
  const hasRealTimeline = rangeStart.getTime() > 0;

  const hovered: SleepStageSegment | null =
    hoveredIndex != null ? segments[hoveredIndex] ?? null : null;

  const legendItems = SLEEP_STAGE_LEGEND_ORDER.map((key) => ({
    key,
    minutes: totals[key],
  })).filter((item) => item.minutes > 0);

  const disturbanceThreshold = 2;

  return (
    <div className="glass-card rounded-2xl p-5">
      <div className="flex items-start justify-between gap-3 mb-3">
        <p className="text-[10px] uppercase tracking-widest text-white/30">Sleep Stages</p>
        <div className="flex flex-col items-end gap-1.5">
          <span className="text-[10px] text-white/25 uppercase tracking-wider">
            {sleepStageDetailLabel(detailPref, source)}
          </span>
          <div className="flex gap-0.5 rounded-lg border border-white/[0.08] bg-white/[0.03] p-0.5">
            {DETAIL_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                title={opt.hint}
                onClick={() => {
                  setDetailPref(opt.value);
                  localStorage.setItem(SLEEP_STAGE_DETAIL_STORAGE_KEY, opt.value);
                }}
                className={`rounded-md px-2 py-0.5 text-[10px] font-medium transition-colors ${
                  detailPref === opt.value
                    ? 'bg-white/10 text-white'
                    : 'text-white/35 hover:text-white/60'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {hasRealTimeline && (
        <div className="flex justify-between text-[10px] text-white/35 mb-1.5 tabular-nums">
          <span>{format(rangeStart, 'HH:mm')}</span>
          <span>{format(rangeEnd, 'HH:mm')}</span>
        </div>
      )}

      <div
        className="relative flex h-6 rounded-full overflow-hidden gap-px mb-1"
        onMouseLeave={() => setHoveredIndex(null)}
      >
        {segments.map((seg, i) => (
          <div
            key={`${seg.stage}-${seg.start.getTime()}-${i}`}
            className={`${seg.colorClass} transition-opacity min-w-[1px] ${
              hoveredIndex != null && hoveredIndex !== i ? 'opacity-60' : ''
            }`}
            style={{ width: `${(seg.minutes / totalMinutes) * 100}%` }}
            onMouseEnter={() => setHoveredIndex(i)}
            title={
              hasRealTimeline
                ? `${seg.label}: ${formatSegmentRange(seg)} (${formatStageMinutes(seg.minutes)})`
                : `${seg.label}: ${formatStageMinutes(seg.minutes)}`
            }
          />
        ))}
      </div>

      {movementMarkers.length > 0 && hasRealTimeline && (
        <div className="relative h-2 mb-3 rounded-full bg-white/[0.04] overflow-hidden">
          {movementMarkers.map((m, i) => {
            const left =
              ((m.timestamp.getTime() - rangeStart.getTime()) / rangeMs) * 100;
            if (left < 0 || left > 100) return null;
            const active = m.value >= disturbanceThreshold;
            return (
              <div
                key={`${m.timestamp.getTime()}-${i}`}
                className={`absolute top-1/2 -translate-y-1/2 w-0.5 h-2 rounded-full ${
                  active ? 'bg-amber-400/80' : 'bg-white/10'
                }`}
                style={{ left: `${left}%` }}
                title={active ? `Movement at ${format(m.timestamp, 'HH:mm')}` : undefined}
              />
            );
          })}
        </div>
      )}

      {hovered && hasRealTimeline && (
        <p className="text-xs text-white/60 mb-2 tabular-nums">
          <span className="text-white/80 font-medium">{hovered.label}</span>
          {' · '}
          {formatSegmentRange(hovered)}
          {' · '}
          {formatStageMinutes(hovered.minutes)}
        </p>
      )}

      {totalsMismatchNote && (
        <p className="text-[11px] text-white/35 mb-2">
          Export stage detail totals differ from summary durations by more than 20 minutes.
        </p>
      )}

      <div className="flex flex-wrap gap-3">
        {legendItems.map((item) => {
          const meta =
            item.key === 'deep'
              ? 'bg-indigo-500'
              : item.key === 'rem'
                ? 'bg-violet-500'
                : item.key === 'light'
                  ? 'bg-blue-400'
                  : 'bg-white/20';
          const label =
            item.key === 'deep'
              ? 'Deep'
              : item.key === 'rem'
                ? 'REM'
                : item.key === 'light'
                  ? 'Light'
                  : 'Awake';
          return (
            <div key={item.key} className="flex items-center gap-1.5">
              <div className={`w-2 h-2 rounded-full ${meta}`} />
              <span className="text-xs text-white/50">{label}</span>
              <span className="text-xs text-white/70 font-medium tabular-nums">
                {formatStageMinutes(item.minutes)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function SleepView() {
  const { data, isDataLoading, selectedDate } = useDashboard();
  const dayKey = format(selectedDate, 'yyyy-MM-dd');
  const insights = useInsights(dayKey);

  if (isDataLoading) {
    return <div className="flex items-center justify-center h-full text-white/30 text-sm">Loading...</div>;
  }

  const summary = buildDaySummary(data, format(selectedDate, 'yyyy-MM-dd'));
  const session = summary.primarySleepSession;
  const raw = data;
  const primarySession = primarySleepSessionFromRaw(raw);

  return (
    <div className="p-6 md:p-8 space-y-6 max-w-5xl mx-auto animate-fadeIn">
      <div>
        <h1 className="font-serif text-3xl text-white tracking-wide">Sleep</h1>
        <p className="text-sm text-white/40 mt-1">{format(selectedDate, 'EEEE, MMMM d, yyyy')}</p>
      </div>

      <div className="flex items-center justify-center py-4">
        <ScoreRing score={summary.scores.sleep} label="Sleep Score" color="#A2D3E8" size={140} strokeWidth={10} />
      </div>

      <SleepStagesCard session={primarySession} />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <MetricPill label="Total Sleep" value={session.durationFormatted} icon={<Clock className="h-3.5 w-3.5" />} />
        <MetricPill label="Deep Sleep" value={session.deepMinutes != null ? `${session.deepMinutes}m` : null} icon={<Moon className="h-3.5 w-3.5" />} />
        <MetricPill label="REM Sleep" value={session.remMinutes != null ? `${session.remMinutes}m` : null} icon={<Sun className="h-3.5 w-3.5" />} />
        <MetricPill label="Light Sleep" value={session.lightMinutes != null ? `${session.lightMinutes}m` : null} icon={<Sunset className="h-3.5 w-3.5" />} />
      </div>

      {session.avgHr && (
        <MetricPill label="Avg Heart Rate" value={session.avgHr} unit="bpm" icon={<Heart className="h-3.5 w-3.5" />} />
      )}
      {session.avgHrv && (
        <MetricPill label="Avg HRV" value={session.avgHrv} icon={<Zap className="h-3.5 w-3.5" />} />
      )}

      {raw?.sleep?.breathing_disturbance_index && (
        <MetricPill
          label="Breathing Disturbance"
          value={raw.sleep.breathing_disturbance_index}
          icon={<Zap className="h-3.5 w-3.5" />}
        />
      )}

      {insights.contributors && (
        <ContributorGrid
          title="Sleep contributors"
          items={insights.contributors.sleep}
          day={dayKey}
        />
      )}

      {insights.baselines && (
        <BaselineTable
          bundle={{
            day: insights.baselines.day,
            deltas: insights.baselines.deltas.filter((d) => SLEEP_BASELINE_METRICS.has(d.metric)),
          }}
        />
      )}

      <div className="glass-card rounded-2xl p-5">
        <p className="text-[10px] uppercase tracking-widest text-white/30 mb-3">Sleep Timeline</p>
        <TimelineList items={summary.timeline.filter(t => t.type === 'sleep')} />
      </div>

      {!session.durationMinutes && (
        <div className="glass-card rounded-2xl p-6 text-center">
          <p className="text-sm text-white/40">No sleep data for this date</p>
        </div>
      )}
    </div>
  );
}
