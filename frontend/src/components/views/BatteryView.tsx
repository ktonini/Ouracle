import { useEffect, useMemo, useState, type PointerEvent } from 'react';
import { format } from 'date-fns';
import { BatteryMedium, PlugZap } from 'lucide-react';
import { useDashboard } from '@/contexts/DashboardContext';
import { api } from '@/lib/api';
import {
  batteryLevelTone,
  buildDaySummary,
  type BatterySample,
} from '@/lib/day-summary';
import { cn } from '@/lib/utils';

const TREND_DAYS = 30;
const CHART_WIDTH = 600;
const CHART_HEIGHT = 160;

function formatSampleTimestamp(timestamp: string, pattern: string): string {
  const normalized = timestamp.replace(' ', 'T');
  const parsed = new Date(normalized);
  if (Number.isNaN(parsed.getTime())) return timestamp;
  return format(parsed, pattern);
}

function toneTextClass(tone: ReturnType<typeof batteryLevelTone>): string {
  if (tone === 'green') return 'text-score-green';
  if (tone === 'yellow') return 'text-score-yellow';
  if (tone === 'coral') return 'text-living-coral';
  return 'text-white/40';
}

function chargingLabel(sample: BatterySample): string | null {
  if (sample.in_charger) return 'In charger';
  if (sample.charging) return 'Charging';
  return null;
}

function dayStats(samples: BatterySample[]) {
  if (samples.length === 0) {
    return { min: null, max: null, first: null, last: null };
  }
  const levels = samples.map((s) => s.level);
  return {
    min: Math.min(...levels),
    max: Math.max(...levels),
    first: samples[0],
    last: samples[samples.length - 1],
  };
}

export function BatteryView() {
  const { data, isDataLoading, selectedDate } = useDashboard();
  const dayKey = format(selectedDate, 'yyyy-MM-dd');
  const summary = useMemo(
    () => (data ? buildDaySummary(data, dayKey) : null),
    [data, dayKey],
  );

  const [trendData, setTrendData] = useState<{ date: string; value: number }[]>([]);
  const [trendLoading, setTrendLoading] = useState(true);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  useEffect(() => {
    setTrendLoading(true);
    const end = dayKey;
    const startDate = new Date(selectedDate);
    startDate.setDate(startDate.getDate() - TREND_DAYS);
    const start = format(startDate, 'yyyy-MM-dd');

    api
      .getQuery('ring_battery.level', start, end)
      .then((res) => {
        if (Array.isArray(res)) {
          setTrendData(
            res.map((d: { day?: string; date?: string; value?: number; score?: number }) => ({
              date: d.day || d.date || '',
              value: d.value ?? d.score ?? 0,
            })),
          );
        } else {
          setTrendData([]);
        }
      })
      .catch(() => setTrendData([]))
      .finally(() => setTrendLoading(false));
  }, [dayKey, selectedDate]);

  if (isDataLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-sm text-white/30">Loading battery data...</div>
      </div>
    );
  }

  const samples = summary?.batterySamples ?? [];
  const latest = samples.length > 0 ? samples[samples.length - 1] : null;
  const stats = dayStats(samples);
  const latestTone = batteryLevelTone(summary?.battery ?? null);
  const latestCharging = latest ? chargingLabel(latest) : null;

  const trendValues = trendData.map((d) => d.value).filter((v) => v != null);
  const trendMin = trendValues.length ? Math.min(...trendValues) : 0;
  const trendMax = trendValues.length ? Math.max(...trendValues) : 100;
  const trendRange = trendMax - trendMin || 1;

  const trendPoints =
    trendData.length > 1
      ? trendData
          .map((d, i) => {
            const x = (i / (trendData.length - 1)) * CHART_WIDTH;
            const y = CHART_HEIGHT - ((d.value - trendMin) / trendRange) * (CHART_HEIGHT - 24) - 12;
            return `${x},${y}`;
          })
          .join(' ')
      : '';

  const hoveredTrend = hoverIndex != null ? trendData[hoverIndex] : null;
  const hoverX =
    hoveredTrend != null && trendData.length > 1
      ? (hoverIndex! / (trendData.length - 1)) * CHART_WIDTH
      : CHART_WIDTH / 2;
  const hoverY =
    hoveredTrend != null
      ? CHART_HEIGHT - ((hoveredTrend.value - trendMin) / trendRange) * (CHART_HEIGHT - 24) - 12
      : 0;
  const tooltipLeftPercent =
    trendData.length <= 1 ? 50 : (hoverIndex! / (trendData.length - 1)) * 100;

  const handleTrendPointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0 || trendData.length === 0) return;
    const x = event.clientX - rect.left;
    const rawIndex =
      trendData.length <= 1 ? 0 : Math.round((x / rect.width) * (trendData.length - 1));
    const index = Math.max(0, Math.min(trendData.length - 1, rawIndex));
    setHoverIndex(index);
  };

  return (
    <div className="mx-auto max-w-3xl animate-fadeIn space-y-6 p-6 md:p-8">
      <div>
        <h1 className="font-serif text-3xl tracking-wide text-white">Ring Battery</h1>
        <p className="mt-1 text-sm text-white/40">{format(selectedDate, 'EEEE, MMM d, yyyy')}</p>
      </div>

      <div className="glass-card rounded-2xl p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-center gap-4">
            <div
              className={cn(
                'flex h-14 w-14 items-center justify-center rounded-2xl border border-white/[0.08] bg-white/[0.04]',
                toneTextClass(latestTone),
              )}
            >
              <BatteryMedium className="h-7 w-7" />
            </div>
            <div>
              <p className="text-xs uppercase tracking-widest text-white/45">Latest sample</p>
              <p className={cn('text-3xl font-semibold', toneTextClass(latestTone))}>
                {summary?.battery != null ? `${Math.round(summary.battery)}%` : '--%'}
              </p>
              <p className="mt-1 text-xs text-white/35">
                {summary?.batteryTimestamp
                  ? formatSampleTimestamp(summary.batteryTimestamp, 'MMM d, HH:mm')
                  : 'No sample for this day'}
              </p>
              {latestCharging && (
                <p className="mt-2 flex items-center gap-1.5 text-xs text-enso-blue">
                  <PlugZap className="h-3.5 w-3.5" />
                  {latestCharging}
                </p>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <Stat label="Min" value={stats.min != null ? `${stats.min}%` : '--'} />
            <Stat label="Max" value={stats.max != null ? `${stats.max}%` : '--'} />
            <Stat
              label="First"
              value={stats.first ? `${stats.first.level}%` : '--'}
              detail={stats.first ? formatSampleTimestamp(stats.first.timestamp, 'HH:mm') : undefined}
            />
            <Stat
              label="Last"
              value={stats.last ? `${stats.last.level}%` : '--'}
              detail={stats.last ? formatSampleTimestamp(stats.last.timestamp, 'HH:mm') : undefined}
            />
          </div>
        </div>
      </div>

      <div className="glass-card rounded-2xl p-5">
        <h2 className="mb-3 text-xs font-medium uppercase tracking-widest text-white/50">
          Samples on selected day
        </h2>
        {samples.length > 0 ? (
          <div className="divide-y divide-white/[0.06]">
            {samples.map((sample) => {
              const charge = chargingLabel(sample);
              const tone = batteryLevelTone(sample.level);
              return (
                <div
                  key={sample.timestamp}
                  className="flex items-center justify-between gap-3 py-2.5 first:pt-0 last:pb-0"
                >
                  <div>
                    <p className="text-sm text-white/80">
                      {formatSampleTimestamp(sample.timestamp, 'HH:mm:ss')}
                    </p>
                    {charge && (
                      <p className="text-[11px] text-enso-blue">{charge}</p>
                    )}
                  </div>
                  <span className={cn('text-sm font-semibold', toneTextClass(tone))}>
                    {sample.level}%
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <p className="text-sm text-white/30">No battery samples recorded for this day.</p>
        )}
      </div>

      <div className="glass-card rounded-2xl p-5">
        <h2 className="mb-1 text-xs font-medium uppercase tracking-widest text-white/50">
          30-day trend
        </h2>
        <p className="mb-4 text-[11px] text-white/30">Hover for date, time, and level</p>
        {trendLoading ? (
          <div className="h-40 rounded-xl bg-white/[0.03]" />
        ) : trendData.length === 0 ? (
          <p className="text-sm text-white/30">No trend data in the last 30 days.</p>
        ) : (
          <div className="relative h-40 w-full">
            {hoveredTrend != null && (
              <div
                className="pointer-events-none absolute bottom-full z-10 mb-2 -translate-x-1/2 whitespace-nowrap rounded-md border border-white/10 bg-[#1a1f2e]/95 px-2.5 py-1.5 text-[11px] leading-tight shadow-lg"
                style={{ left: `${tooltipLeftPercent}%` }}
              >
                <div className="text-white/50">
                  {/^\d{4}-\d{2}-\d{2}$/.test(hoveredTrend.date.slice(0, 10)) &&
                  !hoveredTrend.date.includes('T')
                    ? format(new Date(`${hoveredTrend.date.slice(0, 10)}T12:00:00`), 'MMM d, yyyy')
                    : formatTrendPointDate(hoveredTrend.date)}
                </div>
                <div className={cn('font-semibold', toneTextClass(batteryLevelTone(hoveredTrend.value)))}>
                  {Math.round(hoveredTrend.value)}%
                </div>
              </div>
            )}
            <svg
              viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
              preserveAspectRatio="none"
              className="h-40 w-full touch-none"
              onPointerMove={handleTrendPointerMove}
              onPointerLeave={() => setHoverIndex(null)}
            >
              <polyline
                fill="none"
                stroke="#4ECDC4"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                points={trendPoints}
                opacity="0.85"
              />
              {hoveredTrend != null && (
                <>
                  <line
                    x1={hoverX}
                    y1={0}
                    x2={hoverX}
                    y2={CHART_HEIGHT}
                    stroke="rgba(255,255,255,0.2)"
                    strokeWidth="1"
                    vectorEffect="non-scaling-stroke"
                  />
                  <circle
                    cx={hoverX}
                    cy={hoverY}
                    r="4"
                    fill="#4ECDC4"
                    stroke="rgba(255,255,255,0.9)"
                    strokeWidth="1.5"
                    vectorEffect="non-scaling-stroke"
                  />
                </>
              )}
            </svg>
          </div>
        )}
      </div>
    </div>
  );
}

function formatTrendPointDate(dateStr: string): string {
  const daily = /^\d{4}-\d{2}-\d{2}$/.test(dateStr.slice(0, 10)) && !dateStr.includes('T');
  const parsed = new Date(daily ? `${dateStr.slice(0, 10)}T12:00:00` : dateStr);
  if (Number.isNaN(parsed.getTime())) return dateStr;
  return daily ? format(parsed, 'MMM d, yyyy') : format(parsed, 'MMM d, HH:mm');
}

function Stat({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail?: string;
}) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-white/[0.03] px-3 py-2">
      <p className="text-[10px] uppercase tracking-wider text-white/35">{label}</p>
      <p className="text-sm font-semibold text-white/85">{value}</p>
      {detail && <p className="text-[10px] text-white/30">{detail}</p>}
    </div>
  );
}
