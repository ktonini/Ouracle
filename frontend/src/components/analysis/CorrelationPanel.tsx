import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { lagSummary } from '@/lib/correlation-copy';
import type { CorrelationResult, MetricSpec } from '@/lib/api';

interface RangeOption { label: string; days: number; }

interface Props {
  catalog: MetricSpec[];
  xMetric: string;
  yMetric: string;
  lag: number;
  range: RangeOption;
  ranges: RangeOption[];
  onXChange: (v: string) => void;
  onYChange: (v: string) => void;
  onLagChange: (n: number) => void;
  onRangeChange: (r: RangeOption) => void;
  result: CorrelationResult | null;
  loading: boolean;
  error: string | null;
  onSave: () => void;
}

function MetricSelect({ value, onChange, options, label }: {
  value: string; onChange: (v: string) => void; options: MetricSpec[]; label: string;
}) {
  return (
    <label className="flex-1 min-w-[180px] text-xs text-white/40 font-medium space-y-1">
      <span>{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full bg-white/[0.04] border border-white/10 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-white/30"
      >
        {options.map((o) => (
          <option key={o.path} value={o.path} className="bg-oura-black">
            {o.label} ({o.unit})
          </option>
        ))}
      </select>
    </label>
  );
}

function coefColor(c: number | null): string {
  if (c == null) return 'text-white/40';
  const a = Math.abs(c);
  if (a >= 0.5) return c > 0 ? 'text-score-green' : 'text-living-coral';
  if (a >= 0.3) return 'text-enso-blue';
  return 'text-white/60';
}

export function CorrelationPanel(p: Props) {
  return (
    <div className="space-y-5">
      <div className="glass-card rounded-2xl p-5 space-y-4">
        <div className="flex flex-wrap gap-3">
          <MetricSelect value={p.xMetric} onChange={p.onXChange} options={p.catalog} label="X metric (cause)" />
          <MetricSelect value={p.yMetric} onChange={p.onYChange} options={p.catalog} label="Y metric (effect)" />
        </div>

        <div className="flex flex-wrap items-end gap-4">
          <label className="text-xs text-white/40 font-medium space-y-1 min-w-[200px] flex-1">
            <span>Lag (days)</span>
            <div className="flex items-center gap-2">
              <input type="range" min={-7} max={7} value={p.lag}
                onChange={(e) => p.onLagChange(parseInt(e.target.value, 10))}
                className="accent-enso-blue flex-1" />
              <span className="text-white text-sm w-10 text-right tabular-nums">
                {p.lag > 0 ? `+${p.lag}` : p.lag}
              </span>
            </div>
            <p className="text-[11px] text-white/35 leading-snug pt-1 max-w-md">
              {lagSummary(
                p.lag,
                p.catalog.find((m) => m.path === p.xMetric)?.label ?? p.xMetric,
                p.catalog.find((m) => m.path === p.yMetric)?.label ?? p.yMetric,
              )}
            </p>
          </label>

          <div className="flex gap-1">
            {p.ranges.map((r) => (
              <Button key={r.label} variant="ghost" size="sm"
                className={cn('rounded-lg text-xs h-7',
                  p.range.days === r.days ? 'glass-tab text-white' : 'text-white/40 hover:text-white/70')}
                onClick={() => p.onRangeChange(r)}>
                {r.label}
              </Button>
            ))}
          </div>

          <Button size="sm" variant="ghost" disabled={!p.result || p.result.coefficient == null}
            onClick={p.onSave}
            className="ml-auto rounded-lg text-xs h-7 glass-tab text-white hover:text-white">
            Save investigation
          </Button>
        </div>
      </div>

      <div className="glass-card rounded-2xl p-5 min-h-[200px]">
        {p.loading ? (
          <div className="text-white/40 text-sm">Computing…</div>
        ) : p.error ? (
          <div className="text-living-coral text-sm">{p.error}</div>
        ) : !p.result ? (
          <div className="text-white/40 text-sm">No correlation yet.</div>
        ) : (
          <div className="space-y-4">
            <div className="flex items-baseline gap-3">
              <span className={cn('font-serif text-5xl tabular-nums', coefColor(p.result.coefficient))}>
                {p.result.coefficient == null ? '—' : p.result.coefficient.toFixed(2)}
              </span>
              <span className="text-white/50 text-sm">
                Pearson r · n = {p.result.sample_count} paired days · lag {p.result.lag_days > 0 ? `+${p.result.lag_days}` : p.result.lag_days}d
              </span>
            </div>
            <p className="text-white/70 text-sm leading-relaxed">{p.result.interpretation}</p>
            {p.result.warning && (
              <p className="text-xs text-living-coral/90">
                {p.result.warning === 'fewer_than_14_paired_samples'
                  ? 'Fewer than 14 paired days — coefficient is volatile, treat as exploratory.'
                  : p.result.warning === 'low_samples'
                  ? 'Not enough paired samples to interpret reliably.'
                  : p.result.warning}
              </p>
            )}
            <details className="text-xs text-white/40">
              <summary className="cursor-pointer hover:text-white/60">Paired days ({p.result.paired_dates.length})</summary>
              <div className="mt-2 max-h-32 overflow-auto font-mono space-y-0.5">
                {p.result.paired_dates.map(([a, b]) => (
                  <div key={`${a}-${b}`}>{a} → {b}</div>
                ))}
              </div>
            </details>
          </div>
        )}
      </div>
    </div>
  );
}
