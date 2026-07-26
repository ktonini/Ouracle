import { useId, useState, type PointerEvent } from 'react';
import { format } from 'date-fns';
import { STATUS_HEX, type Status } from './status';

interface SparklineProps {
  data: (number | null)[];
  status: Status;
  height?: number;
  showAxis?: boolean;
  className?: string;
  /** Same length as `data`; enables hover tooltips (YYYY-MM-DD). */
  dates?: string[];
  valueFormatter?: (value: number) => string;
}

function formatSparkDate(dateStr: string): string {
  const daily = /^\d{4}-\d{2}-\d{2}$/.test(dateStr.slice(0, 10)) && !dateStr.includes('T');
  const parsed = new Date(daily ? `${dateStr.slice(0, 10)}T12:00:00` : dateStr);
  if (Number.isNaN(parsed.getTime())) return dateStr;
  return daily ? format(parsed, 'MMM d') : format(parsed, 'MMM d, HH:mm');
}

function defaultValueFormat(value: number): string {
  if (Number.isInteger(value) || Math.abs(value - Math.round(value)) < 1e-9) {
    return String(Math.round(value));
  }
  return value.toFixed(1);
}

/**
 * Compact area+line sparkline. Renders gaps for null entries (sparse days).
 * Optional hover-seek: hairline, point marker, and tooltip when `dates` is set.
 */
export function Sparkline({
  data,
  status,
  height = 36,
  showAxis = false,
  className = '',
  dates,
  valueFormatter = defaultValueFormat,
}: SparklineProps) {
  const id = useId();
  const gradId = `spark-${id}`;
  const [hoverIndex, setHoverIndex] = useState<number | null>(null);
  const w = 200;
  const h = height;
  const pad = 3;
  const n = data.length;

  const values = data.filter((v): v is number => v != null);
  if (values.length < 2) {
    return (
      <div
        className={`rounded-md bg-white/[0.03] ${className}`}
        style={{ height: h }}
        aria-hidden
      />
    );
  }

  const min = Math.min(...values) - 4;
  const max = Math.max(...values) + 4;
  const range = Math.max(1, max - min);
  const xAt = (i: number) => pad + (i * (w - pad * 2)) / Math.max(1, n - 1);
  const yAt = (v: number) => pad + (1 - (v - min) / range) * (h - pad * 2);

  const segments: string[][] = [];
  let current: string[] = [];
  data.forEach((v, i) => {
    if (v == null) {
      if (current.length) {
        segments.push(current);
        current = [];
      }
    } else {
      current.push(`${xAt(i).toFixed(1)},${yAt(v).toFixed(1)}`);
    }
  });
  if (current.length) segments.push(current);

  let lastIdx = -1;
  for (let i = data.length - 1; i >= 0; i--) {
    if (data[i] != null) {
      lastIdx = i;
      break;
    }
  }

  const color = STATUS_HEX[status];
  const seekEnabled = dates != null && dates.length === n;
  const hovered =
    seekEnabled && hoverIndex != null && data[hoverIndex] != null ? hoverIndex : null;
  const tooltipLeftPercent = hovered != null && n > 1 ? (hovered / (n - 1)) * 100 : 50;

  const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
    if (!seekEnabled) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0 || n === 0) return;
    const px = event.clientX - rect.left;
    const rawIndex = n <= 1 ? 0 : Math.round((px / rect.width) * (n - 1));
    const index = Math.max(0, Math.min(n - 1, rawIndex));
    if (data[index] == null) {
      setHoverIndex(null);
      return;
    }
    setHoverIndex(index);
  };

  const displayIndex = hovered ?? (hoverIndex == null ? lastIdx : null);

  return (
    <div className={`relative min-h-0 ${className}`} style={{ height: h }}>
      {hovered != null && dates?.[hovered] != null && data[hovered] != null && (
        <div
          className="pointer-events-none absolute bottom-full z-10 mb-1 -translate-x-1/2 whitespace-nowrap rounded-md border border-white/10 bg-[#1a1f2e]/95 px-2 py-1 text-[10px] leading-tight shadow-lg"
          style={{ left: `${tooltipLeftPercent}%` }}
        >
          <div className="text-white/50">{formatSparkDate(dates[hovered])}</div>
          <div className="font-semibold text-white/90">{valueFormatter(data[hovered] as number)}</div>
        </div>
      )}
      <svg
        viewBox={`0 0 ${w} ${h}`}
        width="100%"
        height={h}
        preserveAspectRatio="none"
        className={`block touch-none ${seekEnabled ? 'cursor-crosshair' : ''}`}
        role="img"
        aria-label="7-day trend"
        onPointerMove={handlePointerMove}
        onPointerLeave={() => setHoverIndex(null)}
      >
        <defs>
          <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.34} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        {showAxis && (
          <line
            x1={pad}
            y1={h - pad - 0.5}
            x2={w - pad}
            y2={h - pad - 0.5}
            stroke="rgba(255,255,255,0.06)"
            strokeWidth={1}
          />
        )}
        {segments.map((seg, idx) => {
          if (seg.length === 0) return null;
          const firstX = seg[0].split(',')[0];
          const lastX = seg[seg.length - 1].split(',')[0];
          const areaPath = `M ${firstX},${h - pad} L ${seg.join(' L ')} L ${lastX},${h - pad} Z`;
          const linePath = `M ${seg.join(' L ')}`;
          return (
            <g key={idx}>
              <path d={areaPath} fill={`url(#${gradId})`} />
              <path
                d={linePath}
                fill="none"
                stroke={color}
                strokeWidth={1.6}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            </g>
          );
        })}
        {seekEnabled && hovered != null && (
          <line
            x1={xAt(hovered)}
            y1={pad}
            x2={xAt(hovered)}
            y2={h - pad}
            stroke="rgba(255,255,255,0.25)"
            strokeWidth={1}
            vectorEffect="non-scaling-stroke"
          />
        )}
        {displayIndex != null && displayIndex >= 0 && data[displayIndex] != null && (
          <circle
            cx={xAt(displayIndex)}
            cy={yAt(data[displayIndex] as number)}
            r={3}
            fill={color}
            stroke="#151619"
            strokeWidth={1.5}
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>
    </div>
  );
}

/**
 * Returns the small "↑ +6 7d" / "↓ -23 7d" / "→ flat 7d" hint that sits beside
 * the status badge. Returns null when there isn't enough data to be meaningful.
 */
export function deltaIndicator(
  data: (number | null)[],
): { arrow: string; tone: string; label: string } | null {
  const values = data.filter((v): v is number => v != null);
  if (values.length < 2) return null;
  const first = values[0];
  const last = values[values.length - 1];
  const delta = last - first;
  if (Math.abs(delta) < 2) {
    return { arrow: '→', tone: 'text-white/40', label: 'flat 7d' };
  }
  if (delta > 0) {
    return { arrow: '↑', tone: 'text-score-green', label: `+${Math.round(delta)} 7d` };
  }
  return { arrow: '↓', tone: 'text-score-red', label: `${Math.round(delta)} 7d` };
}
