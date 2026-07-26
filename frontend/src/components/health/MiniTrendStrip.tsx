import { useEffect, useState, type PointerEvent } from 'react';
import { format } from 'date-fns';
import { api } from '@/lib/api';

const VIEWBOX_WIDTH = 120;
const VIEWBOX_HEIGHT = 32;

interface MiniTrendStripProps {
  metric: string;
  label: string;
  color: string;
  days?: number;
  endDate?: string;
  onOpen?: () => void;
}

function formatTrendDate(dateStr: string): string {
  const daily = /^\d{4}-\d{2}-\d{2}$/.test(dateStr.slice(0, 10)) && !dateStr.includes('T');
  const parsed = new Date(daily ? `${dateStr.slice(0, 10)}T12:00:00` : dateStr);
  if (Number.isNaN(parsed.getTime())) return dateStr;
  return daily ? format(parsed, 'MMM d, yyyy') : format(parsed, 'MMM d, HH:mm');
}

function formatTrendValue(value: number): string {
  if (Number.isInteger(value) || Math.abs(value - Math.round(value)) < 1e-9) {
    return String(Math.round(value));
  }
  return value.toFixed(1);
}

function sampleX(index: number, count: number, width: number): number {
  if (count <= 1) return width / 2;
  return (index / (count - 1)) * width;
}

function sampleY(value: number, min: number, range: number, height: number): number {
  return height - ((value - min) / range) * (height - 4) - 2;
}

export function MiniTrendStrip({ metric, label, color, days = 30, endDate, onOpen }: MiniTrendStripProps) {
  const [data, setData] = useState<{ date: string; value: number }[]>([]);
  const [loading, setLoading] = useState(true);
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);

  useEffect(() => {
    const end = endDate || new Date().toISOString().split('T')[0];
    const start = new Date(new Date(end).setDate(new Date(end).getDate() - days)).toISOString().split('T')[0];

    api.getQuery(metric, start, end)
      .then((res) => {
        if (Array.isArray(res)) {
          setData(res.map((d: { day?: string; date?: string; value?: number; score?: number }) => ({
            date: d.day || d.date || '',
            value: d.value ?? d.score ?? 0,
          })));
        }
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, [metric, days, endDate]);

  if (loading || data.length === 0) {
    return (
      <div className="flex items-center gap-3">
        <span className="text-[10px] uppercase tracking-wider text-white/30">{label}</span>
        <div className="h-8 flex-1 rounded-lg bg-white/[0.03]" />
      </div>
    );
  }

  const values = data.map((d) => d.value).filter((v) => v != null);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const points = data
    .map((d, i) => {
      const x = sampleX(i, data.length, VIEWBOX_WIDTH);
      const y = sampleY(d.value, min, range, VIEWBOX_HEIGHT);
      return `${x},${y}`;
    })
    .join(' ');

  const latest = values[values.length - 1];
  const hovered = hoverIndex != null ? data[hoverIndex] : null;
  const hoverX = hovered != null ? sampleX(hoverIndex!, data.length, VIEWBOX_WIDTH) : 0;
  const hoverY = hovered != null ? sampleY(hovered.value, min, range, VIEWBOX_HEIGHT) : 0;
  const tooltipLeftPercent =
    data.length <= 1 ? 50 : (hoverIndex! / (data.length - 1)) * 100;

  const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;
    const x = event.clientX - rect.left;
    const rawIndex =
      data.length <= 1 ? 0 : Math.round((x / rect.width) * (data.length - 1));
    const index = Math.max(0, Math.min(data.length - 1, rawIndex));
    setHoverIndex(index);
  };

  const content = (
    <>
      <div className="flex shrink-0 flex-col">
        <span className="text-[10px] uppercase tracking-wider text-white/30">{label}</span>
        <span className="text-sm font-semibold text-white/90">{latest}</span>
      </div>
      <div className="relative h-8 min-h-8 flex-1">
        {hovered != null && (
          <div
            className="pointer-events-none absolute bottom-full z-10 mb-1 -translate-x-1/2 whitespace-nowrap rounded-md border border-white/10 bg-[#1a1f2e]/95 px-2 py-1 text-[10px] leading-tight shadow-lg"
            style={{ left: `${tooltipLeftPercent}%` }}
          >
            <div className="text-white/50">{formatTrendDate(hovered.date)}</div>
            <div className="font-semibold text-white/90">{formatTrendValue(hovered.value)}</div>
          </div>
        )}
        <svg
          viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
          preserveAspectRatio="none"
          className="h-8 w-full touch-none"
          onPointerMove={handlePointerMove}
          onPointerLeave={() => setHoverIndex(null)}
        >
          <polyline
            fill="none"
            stroke={color}
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
            points={points}
            opacity="0.8"
          />
          {hovered != null && (
            <>
              <line
                x1={hoverX}
                y1={0}
                x2={hoverX}
                y2={VIEWBOX_HEIGHT}
                stroke="rgba(255,255,255,0.25)"
                strokeWidth="1"
                vectorEffect="non-scaling-stroke"
              />
              <circle
                cx={hoverX}
                cy={hoverY}
                r="3"
                fill={color}
                stroke="rgba(255,255,255,0.9)"
                strokeWidth="1"
                vectorEffect="non-scaling-stroke"
              />
            </>
          )}
        </svg>
      </div>
    </>
  );

  const rootClassName =
    'flex w-full items-center gap-3 text-left rounded-lg transition-colors' +
    (onOpen ? ' cursor-pointer hover:bg-white/[0.04] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-enso-blue/60' : '');

  if (onOpen) {
    return (
      <button type="button" onClick={onOpen} className={rootClassName}>
        {content}
      </button>
    );
  }

  return <div className={rootClassName}>{content}</div>;
}
