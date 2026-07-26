import { useState, useEffect } from 'react';
import { TrendingUp, ArrowUpDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { api } from '@/lib/api';
import { useDashboard } from '@/contexts/DashboardContext';

const METRIC_PRESETS = [
  { id: 'sleep.score', label: 'Sleep Score', color: '#A2D3E8' },
  { id: 'readiness.score', label: 'Readiness Score', color: '#4ECDC4' },
  { id: 'activity.score', label: 'Activity Score', color: '#FFD166' },
  { id: 'sleep_session.total_sleep_duration', label: 'Sleep Duration', color: '#60a5fa' },
  { id: 'activity.steps', label: 'Steps', color: '#38bdf8' },
  { id: 'activity.total_calories', label: 'Calories', color: '#f87171' },
];

const RANGES = [
  { label: '7d', days: 7 },
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
  { label: '1y', days: 365 },
];

type MetricPreset = (typeof METRIC_PRESETS)[number];
type RangePreset = (typeof RANGES)[number];

function rangeForDays(days: number): RangePreset {
  return RANGES.find((r) => r.days === days) ?? { label: `${days}d`, days };
}

export function TrendsView() {
  const { trendFocus } = useDashboard();
  const [selectedMetric, setSelectedMetric] = useState<MetricPreset>(METRIC_PRESETS[0]);
  const [range, setRange] = useState<RangePreset>(RANGES[1]);
  const [data, setData] = useState<{ date: string; value: number }[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!trendFocus) return;
    const preset = METRIC_PRESETS.find((m) => m.id === trendFocus.metricId);
    if (preset) {
      setSelectedMetric(preset);
    } else {
      setSelectedMetric({
        id: trendFocus.metricId,
        label: trendFocus.label ?? trendFocus.metricId,
        color: trendFocus.color ?? '#A2D3E8',
      });
    }
    setRange(rangeForDays(trendFocus.rangeDays ?? 30));
  }, [trendFocus]);

  useEffect(() => {
    setLoading(true);
    const end = trendFocus?.endDate ?? new Date().toISOString().split('T')[0];
    const endDate = new Date(end);
    const start = new Date(endDate);
    start.setDate(start.getDate() - range.days);
    const startStr = start.toISOString().split('T')[0];

    api.getQuery(selectedMetric.id, startStr, end)
      .then((res) => {
        if (Array.isArray(res)) {
          setData(res.map((d: any) => ({ date: d.day || d.date, value: d.value ?? d.score })));
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [selectedMetric, range, trendFocus?.endDate]);

  const values = data.map(d => d.value).filter(v => v != null);
  const min = values.length ? Math.min(...values) : 0;
  const max = values.length ? Math.max(...values) : 100;
  const rangeVal = max - min || 1;

  const chartHeight = 200;
  const chartWidth = 600;

  const points = data.length > 1
    ? data.map((d, i) => {
        const x = (i / (data.length - 1)) * chartWidth;
        const y = chartHeight - ((d.value - min) / rangeVal) * (chartHeight - 20) - 10;
        return `${x},${y}`;
      }).join(' ')
    : '';

  return (
    <div className="p-6 md:p-8 space-y-6 max-w-5xl mx-auto animate-fadeIn">
      <div>
        <h1 className="font-serif text-3xl text-white tracking-wide">Trends</h1>
        <p className="text-sm text-white/40 mt-1">Historical data explorer</p>
      </div>

      {/* Metric Presets */}
      <div className="flex flex-wrap gap-2">
        {METRIC_PRESETS.map((m) => (
          <Button
            key={m.id}
            variant="ghost"
            size="sm"
            className={cn(
              'rounded-lg text-xs',
              selectedMetric.id === m.id
                ? 'glass-tab text-white'
                : 'text-white/40 hover:text-white/70'
            )}
            onClick={() => setSelectedMetric(m)}
          >
            <TrendingUp className="h-3 w-3 mr-1.5" style={{ color: m.color }} />
            {m.label}
          </Button>
        ))}
      </div>

      {/* Range Selector */}
      <div className="flex gap-1">
        {RANGES.map((r) => (
          <Button
            key={r.label}
            variant="ghost"
            size="sm"
            className={cn(
              'rounded-lg text-xs h-7',
              range.days === r.days
                ? 'glass-tab text-white'
                : 'text-white/40 hover:text-white/70'
            )}
            onClick={() => setRange(r)}
          >
            {r.label}
          </Button>
        ))}
      </div>

      {/* Chart Area */}
      <div className="glass-card rounded-2xl p-5 min-h-[240px]">
        {loading ? (
          <div className="flex items-center justify-center h-[200px] text-white/30 text-sm">Loading...</div>
        ) : data.length > 0 ? (
          <div className="flex flex-col items-center">
            <div className="flex items-center gap-2 mb-3">
              <span className="text-xs text-white/40">{data[0].date}</span>
              <ArrowUpDown className="h-3 w-3 text-white/20" />
              <span className="text-xs text-white/40">{data[data.length - 1].date}</span>
            </div>
            <svg viewBox={`-10 -10 ${chartWidth + 20} ${chartHeight + 30}`} className="w-full max-w-2xl">
              <polyline
                fill="none"
                stroke={selectedMetric.color}
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                points={points}
                opacity="0.85"
              />
              {values.length > 0 && (
                <>
                  <text x="5" y="10" fontSize="10" fill="rgba(255,255,255,0.3)">{Math.round(max)}</text>
                  <text x="5" y={chartHeight} fontSize="10" fill="rgba(255,255,255,0.3)">{Math.round(min)}</text>
                  <text
                    x={chartWidth - 5}
                    y={chartHeight - ((values[values.length - 1] - min) / rangeVal) * (chartHeight - 20) - 5}
                    fontSize="12"
                    fontWeight="600"
                    fill={selectedMetric.color}
                    textAnchor="end"
                  >
                    {Math.round(values[values.length - 1])}
                  </text>
                </>
              )}
            </svg>
          </div>
        ) : (
          <div className="flex items-center justify-center h-[200px] text-white/30 text-sm">No data for this range</div>
        )}
      </div>
    </div>
  );
}
