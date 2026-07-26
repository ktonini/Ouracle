import { useEffect, useMemo, useState } from 'react';
import { useDashboard } from '@/contexts/DashboardContext';
import { MetricPill } from '@/components/health/MetricPill';
import { MiniTrendStrip } from '@/components/health/MiniTrendStrip';
import { api } from '@/lib/api';
import {
  hasAnyResilienceContent,
  hasDaytimeStressSeries,
  hasReadinessStressBalance,
  mergeResilienceHistory,
  normalizeResilience,
  resilienceHistoryRange,
  selectResilienceForDay,
  type QueryPoint,
  type ResilienceSelection,
} from '@/lib/resilience';
import { Shield, TrendingUp } from 'lucide-react';
import { format } from 'date-fns';

interface StressSample {
  timestamp: string;
  stress?: number | null;
  recovery?: number | null;
}

function stressBarColor(stress: number | null | undefined): string {
  if (stress == null) return 'rgba(255,255,255,0.15)';
  if (stress <= 25) return '#10B981';
  if (stress <= 50) return '#3B82F6';
  if (stress <= 75) return '#F59E0B';
  return '#EF4444';
}

function stressBarHeight(stress: number | null | undefined): string {
  if (stress == null) return '20%';
  return `${Math.max(12, Math.min(100, stress))}%`;
}

export function ResilienceView() {
  const { data, isDataLoading, selectedDate } = useDashboard();
  const selectedDay = format(selectedDate, 'yyyy-MM-dd');

  const [historyLoading, setHistoryLoading] = useState(true);
  const [historySelection, setHistorySelection] = useState<ResilienceSelection | null>(null);

  const raw = data;
  const readiness = raw?.readiness;
  const activity = raw?.activity;
  const selectedDayResilience = useMemo(
    () => normalizeResilience(raw?.resilience?.[0] ?? raw?.resilience),
    [raw?.resilience],
  );

  const dayOnlySelection = useMemo(
    () => selectResilienceForDay(selectedDay, selectedDayResilience, []),
    [selectedDay, selectedDayResilience],
  );

  const selection = historySelection ?? dayOnlySelection;

  useEffect(() => {
    setHistorySelection(null);
  }, [selectedDay]);

  useEffect(() => {
    let cancelled = false;
    const { start, end } = resilienceHistoryRange(selectedDay);

    setHistoryLoading(true);
    Promise.all([
      api.getQuery('resilience.level', start, end),
      api.getQuery('resilience.sleep_recovery', start, end),
      api.getQuery('resilience.daytime_recovery', start, end),
      api.getQuery('resilience.stress', start, end),
    ])
      .then(([level, sleepRecovery, daytimeRecovery, stress]) => {
        if (cancelled) return;
        const merged = mergeResilienceHistory(
          level as QueryPoint[],
          sleepRecovery as QueryPoint[],
          daytimeRecovery as QueryPoint[],
          stress as QueryPoint[],
        );
        setHistorySelection(
          selectResilienceForDay(selectedDay, selectedDayResilience, merged),
        );
      })
      .catch(() => {
        if (!cancelled) {
          setHistorySelection(dayOnlySelection);
        }
      })
      .finally(() => {
        if (!cancelled) setHistoryLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedDay, selectedDayResilience, dayOnlySelection]);

  const loading = isDataLoading || (historyLoading && !dayOnlySelection);
  const showContent = hasAnyResilienceContent(selection, readiness, activity);
  const stressSamples: StressSample[] = hasDaytimeStressSeries(activity)
    ? (activity.stress as StressSample[])
    : [];

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-white/30 text-sm">
        Loading...
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 space-y-6 max-w-5xl mx-auto animate-fadeIn">
      <div>
        <h1 className="font-serif text-3xl text-white tracking-wide">Stress & Resilience</h1>
        <p className="text-sm text-white/40 mt-1">{format(selectedDate, 'EEEE, MMMM d, yyyy')}</p>
      </div>

      {!showContent && (
        <div className="glass-card rounded-2xl p-6 text-center">
          <Shield className="h-12 w-12 text-white/20 mx-auto mb-3" />
          <p className="text-sm text-white/40">No stress or resilience data for this date</p>
          <p className="text-xs text-white/25 mt-1">
            Sync a newer Oura export to populate resilience, readiness stress, or daytime stress
          </p>
        </div>
      )}

      {selection && (
        <>
          <div className="flex items-center justify-center py-4">
            <div className="flex flex-col items-center gap-2">
              <Shield
                className={`h-16 w-16 ${selection.level ? 'text-score-green' : 'text-white/25'}`}
              />
              {selection.level ? (
                <>
                  <span className="text-xl font-serif font-semibold text-white/90">
                    {selection.level}
                  </span>
                  <span className="text-xs text-white/40">Resilience Level</span>
                </>
              ) : (
                <span className="text-sm text-white/35">Level not recorded</span>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            <MetricPill
              label="Sleep recovery"
              value={
                selection.sleep_recovery != null
                  ? `${Math.round(selection.sleep_recovery)}%`
                  : null
              }
            />
            <MetricPill
              label="Daytime recovery"
              value={
                selection.daytime_recovery != null
                  ? `${Math.round(selection.daytime_recovery)}%`
                  : null
              }
            />
            <MetricPill
              label="Stress load"
              value={
                selection.stress != null ? `${Math.round(selection.stress)}%` : null
              }
            />
          </div>

          {!selection.isExactDay && (
            <p className="text-center text-xs text-amber-200/70">
              Latest available: {selection.sourceDay}
            </p>
          )}
        </>
      )}

      {hasReadinessStressBalance(readiness) && (
        <div className="glass-card rounded-2xl p-5 space-y-3">
          <h2 className="font-serif text-lg text-white">Stress / recovery balance</h2>
          <p className="text-xs text-white/35">From readiness for {selectedDay}</p>
          <div className="grid grid-cols-2 gap-3">
            <MetricPill
              label="Stress (high)"
              value={
                readiness.stress_high != null ? `${readiness.stress_high} min` : null
              }
            />
            <MetricPill
              label="Recovery (high)"
              value={
                readiness.recovery_high != null
                  ? `${readiness.recovery_high} min`
                  : null
              }
            />
          </div>
        </div>
      )}

      {stressSamples.length > 0 && (
        <div className="glass-card rounded-2xl p-5 space-y-4">
          <div className="flex items-center gap-2">
            <TrendingUp className="h-4 w-4 text-white/50" />
            <h2 className="font-serif text-lg text-white">Daytime stress</h2>
          </div>
          <p className="text-xs text-white/35">Physiological samples for {selectedDay}</p>
          <div className="h-36 w-full bg-white/[0.02] rounded-xl border border-white/[0.05] p-3 flex items-end gap-0.5">
            {stressSamples.map((sample, idx) => (
              <div
                key={`${sample.timestamp}-${idx}`}
                className="flex-1 rounded-t min-w-[2px] transition-opacity hover:opacity-80"
                style={{
                  height: stressBarHeight(sample.stress),
                  backgroundColor: stressBarColor(sample.stress),
                }}
                title={
                  sample.timestamp
                    ? `${sample.timestamp}: stress ${sample.stress ?? '—'}`
                    : undefined
                }
              />
            ))}
          </div>
        </div>
      )}

      {selection && (
        <div className="glass-card rounded-2xl p-5 space-y-4">
          <h2 className="font-serif text-lg text-white">90-day trends</h2>
          <MiniTrendStrip
            metric="resilience.sleep_recovery"
            label="Sleep recovery"
            color="#10B981"
            days={90}
            endDate={selectedDay}
          />
          <MiniTrendStrip
            metric="resilience.daytime_recovery"
            label="Daytime recovery"
            color="#3B82F6"
            days={90}
            endDate={selectedDay}
          />
          <MiniTrendStrip
            metric="resilience.stress"
            label="Stress load"
            color="#F59E0B"
            days={90}
            endDate={selectedDay}
          />
        </div>
      )}
    </div>
  );
}
