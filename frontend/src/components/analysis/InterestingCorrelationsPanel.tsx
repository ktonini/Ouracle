import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { directionSummary, lagSummary, strengthLabel } from '@/lib/correlation-copy';
import type { InterestingCorrelation } from '@/lib/api';

interface RangeOption {
  label: string;
  days: number;
}

interface Props {
  results: InterestingCorrelation[];
  loading: boolean;
  error: string | null;
  range: RangeOption;
  ranges: RangeOption[];
  onRangeChange: (r: RangeOption) => void;
  onInspect: (item: InterestingCorrelation) => void;
}

function coefColor(c: number): string {
  const a = Math.abs(c);
  if (a >= 0.5) return c > 0 ? 'text-score-green' : 'text-living-coral';
  if (a >= 0.3) return 'text-enso-blue';
  return 'text-white/60';
}

export function InterestingCorrelationsPanel(p: Props) {
  return (
    <div className="space-y-5">
      <div className="glass-card rounded-2xl p-5 text-sm text-white/55 leading-relaxed space-y-2">
        <p>
          Each card compares two metrics across your history. A <strong className="text-white/75">positive</strong>{' '}
          correlation means they tend to rise and fall together on paired days; a{' '}
          <strong className="text-white/75">negative</strong> correlation means when one runs high, the other tends to
          run low.
        </p>
        <p>
          <strong className="text-white/75">Lag</strong> shifts the second metric forward in time — for example lag +1
          pairs tonight&apos;s sleep with tomorrow&apos;s readiness. Correlation is not causation; use Inspect to
          explore the chart and change metrics.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <span className="text-xs text-white/40 font-medium">Range</span>
        <div className="flex gap-1">
          {p.ranges.map((r) => (
            <Button
              key={r.label}
              variant="ghost"
              size="sm"
              className={cn(
                'rounded-lg text-xs h-7',
                p.range.days === r.days ? 'glass-tab text-white' : 'text-white/40 hover:text-white/70',
              )}
              onClick={() => p.onRangeChange(r)}
            >
              {r.label}
            </Button>
          ))}
        </div>
      </div>

      {p.loading ? (
        <div className="text-white/40 text-sm">Scanning correlations…</div>
      ) : p.error ? (
        <div className="text-living-coral text-sm">{p.error}</div>
      ) : p.results.length === 0 ? (
        <div className="glass-card rounded-2xl p-6 text-white/50 text-sm">
          No strong correlations found over this range. Try 180d.
        </div>
      ) : (
        <div className="space-y-3">
          {p.results.map((item) => {
            const headline = directionSummary(item.x_label, item.y_label, item.coefficient);
            const lagText = lagSummary(item.lag_days, item.x_label, item.y_label);
            return (
              <div
                key={`${item.x_metric}-${item.y_metric}-${item.lag_days}`}
                className="glass-card rounded-2xl p-5 space-y-3"
              >
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <h3 className="text-white font-medium text-sm">{item.reason}</h3>
                    <p className="text-white/40 text-xs mt-1">
                      {item.x_label} → {item.y_label}
                    </p>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="rounded-lg text-xs h-7 glass-tab text-white shrink-0"
                    onClick={() => p.onInspect(item)}
                  >
                    Inspect
                  </Button>
                </div>

                {headline && (
                  <p className="text-white/85 text-sm leading-relaxed font-medium">{headline}</p>
                )}

                <div className="flex flex-wrap items-baseline gap-3">
                  <span className={cn('font-serif text-4xl tabular-nums', coefColor(item.coefficient))}>
                    {item.coefficient.toFixed(2)}
                  </span>
                  <span className="text-white/50 text-xs">
                    {strengthLabel(item.coefficient)} · n = {item.sample_count} · lag{' '}
                    {item.lag_days > 0 ? `+${item.lag_days}` : item.lag_days}d
                  </span>
                </div>

                <p className="text-white/60 text-xs leading-relaxed border-l-2 border-white/10 pl-3">{lagText}</p>

                <p className="text-white/65 text-sm leading-relaxed">{item.interpretation}</p>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
