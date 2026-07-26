import { useMemo } from 'react';
import {
  AlertTriangle,
  AlertCircle,
  ArrowDown,
  ArrowUp,
  ChevronRight,
  CheckCircle2,
  CloudOff,
  Info,
  Minus,
  RefreshCcw,
} from 'lucide-react';

import type {
  ActionCard,
  BaselineBundle,
  ContributorSummary,
  DailyGuidance,
  SyncFreshness,
} from '@/lib/api';
import { useContributorHistory } from '@/hooks/useContributorHistory';

import { Sparkline, deltaIndicator } from './Sparkline';
import {
  STATUS_HERO_CLASS,
  STATUS_ORDER,
  STATUS_RING_CLASS,
  STATUS_TEXT_CLASS,
  StatusBadge,
  StatusDot,
} from './status';

const SEVERITY_ICON = {
  critical: AlertCircle,
  warning: AlertTriangle,
  info: Info,
};

const FRESHNESS_BADGE: Record<
  SyncFreshness['status'],
  { label: string; cls: string; Icon: React.ElementType }
> = {
  fresh: {
    label: 'Fresh',
    cls: 'bg-score-green/10 text-score-green border-score-green/30',
    Icon: CheckCircle2,
  },
  stale: {
    label: 'Stale',
    cls: 'bg-score-yellow/10 text-score-yellow border-score-yellow/30',
    Icon: RefreshCcw,
  },
  very_stale: {
    label: 'Very stale',
    cls: 'bg-score-red/10 text-score-red border-score-red/30',
    Icon: AlertTriangle,
  },
  empty: {
    label: 'No data',
    cls: 'bg-white/5 text-white/50 border-white/10',
    Icon: CloudOff,
  },
  syncing: {
    label: 'Syncing',
    cls: 'bg-enso-blue/10 text-enso-blue border-enso-blue/30',
    Icon: RefreshCcw,
  },
  blocked: {
    label: 'Blocked',
    cls: 'bg-score-red/10 text-score-red border-score-red/30',
    Icon: AlertCircle,
  },
};

export function SyncFreshnessChip({ freshness }: { freshness: SyncFreshness | null }) {
  if (!freshness) return null;
  const { label, cls, Icon } = FRESHNESS_BADGE[freshness.status];
  const title = freshness.message ?? '';
  return (
    <div
      title={title}
      className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-medium border ${cls}`}
    >
      <Icon className="w-3 h-3" />
      <span>{label}</span>
      {freshness.latest_day && (
        <span className="text-white/40 hidden sm:inline">· {freshness.latest_day}</span>
      )}
    </div>
  );
}

export function GuidanceBlock({ guidance }: { guidance: DailyGuidance | null }) {
  if (!guidance) return null;
  return (
    <div className="space-y-2">
      <h2 className="font-serif text-2xl md:text-3xl text-white leading-tight tracking-wide">
        {guidance.headline}
      </h2>
      {guidance.body.map((line, i) => (
        <p key={i} className="text-sm text-white/55 leading-relaxed">
          {line}
        </p>
      ))}
    </div>
  );
}

export function ActionCardsList({ cards }: { cards: ActionCard[] }) {
  if (!cards || cards.length === 0) return null;
  return (
    <div className="space-y-2">
      <p className="text-[10px] uppercase tracking-widest text-white/30">Today&apos;s actions</p>
      <div className="space-y-2">
        {cards.map((card) => {
          const Icon = SEVERITY_ICON[card.severity] ?? Info;
          const tone =
            card.severity === 'critical'
              ? 'border-score-red/40 bg-score-red/[0.06]'
              : card.severity === 'warning'
                ? 'border-score-yellow/30 bg-score-yellow/[0.06]'
                : 'border-enso-blue/30 bg-enso-blue/[0.06]';
          return (
            <div key={card.id} className={`rounded-xl border ${tone} p-3 flex gap-3 min-w-0`}>
              <Icon className="w-4 h-4 mt-0.5 text-white/70 flex-shrink-0" />
              <div className="space-y-1 min-w-0 flex-1">
                <p className="text-sm font-medium text-white">{card.title}</p>
                <p className="text-xs text-white/60 leading-relaxed break-words">{card.reason}</p>
                <p className="text-xs text-white/50 leading-relaxed break-words">
                  {card.recommendation}
                </p>
                {card.evidence.length > 0 && (
                  <p className="text-[11px] text-white/35 leading-relaxed break-words">
                    Source: {card.evidence.map((e) => e.source_path).join(', ')}
                  </p>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────
 * ContributorGrid (reimagined hero + baby tiles)
 * ──────────────────────────────────────────────────────────────────────── */

function formatValue(c: ContributorSummary): string {
  if (c.value == null) return '—';
  const n = c.value;
  const formatted = Number.isInteger(n) ? String(n) : n.toFixed(1);
  return c.unit && c.unit !== 'score' ? `${formatted} ${c.unit}` : formatted;
}

function contributorValueFormat(c: ContributorSummary): (value: number) => string {
  return (value: number) => {
    const formatted = Number.isInteger(value) ? String(value) : value.toFixed(1);
    return c.unit && c.unit !== 'score' ? `${formatted} ${c.unit}` : formatted;
  };
}

function ContributorTile({
  contributor: c,
  history,
  dates,
  feature = false,
}: {
  contributor: ContributorSummary;
  history: (number | null)[];
  dates?: string[];
  feature?: boolean;
}) {
  const delta = deltaIndicator(history);
  const hasHistory = history.some((v) => v != null);
  return (
    <div
      title={c.explanation}
      className={`rounded-xl ${STATUS_RING_CLASS[c.status]} ${
        feature ? 'p-5 sm:col-span-2' : 'p-4'
      } flex flex-col gap-3 min-w-0`}
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-[11px] uppercase tracking-wider text-white/55 font-medium min-w-0 flex-1 break-words">
          {c.label}
        </p>
        <div className="flex items-center gap-2 shrink-0">
          {delta && (
            <span
              className={`text-[11px] tabular-nums whitespace-nowrap ${delta.tone}`}
              aria-label={`Last 7 days: ${delta.label}`}
            >
              {delta.arrow} {delta.label}
            </span>
          )}
          <StatusBadge status={c.status} />
        </div>
      </div>

      <p
        className={`font-serif ${feature ? 'text-5xl' : 'text-3xl'} leading-none tabular-nums text-white`}
      >
        {formatValue(c)}
      </p>

      <p className="text-xs text-white/60 leading-relaxed break-words">{c.explanation}</p>

      {hasHistory && (
        <div className="-mx-1 mt-auto">
          <Sparkline
            data={history}
            dates={dates}
            status={c.status}
            height={feature ? 56 : 36}
            valueFormatter={contributorValueFormat(c)}
          />
        </div>
      )}
    </div>
  );
}

function HeroCard({
  contributor: c,
  history,
  dates,
}: {
  contributor: ContributorSummary;
  history: (number | null)[];
  dates?: string[];
}) {
  const delta = deltaIndicator(history);
  const hasHistory = history.some((v) => v != null);
  return (
    <div
      title={c.explanation}
      className={`rounded-2xl ${STATUS_HERO_CLASS[c.status]} p-5 space-y-4 relative overflow-hidden`}
    >
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2 min-w-0">
          <StatusDot status={c.status} />
          <p
            className={`text-[11px] uppercase tracking-widest font-semibold truncate ${STATUS_TEXT_CLASS[c.status]}`}
          >
            Most actionable
          </p>
        </div>
        {delta && (
          <span className={`text-[11px] tabular-nums whitespace-nowrap ${delta.tone}`}>
            {delta.arrow} {delta.label}
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="text-sm text-white/55 mb-1 break-words">{c.label}</p>
          <p className="font-serif text-6xl leading-none tabular-nums text-white">
            {formatValue(c)}
          </p>
        </div>
        {hasHistory && (
          <div className="flex-1 min-w-[180px] max-w-[280px]">
            <Sparkline
              data={history}
              dates={dates}
              status={c.status}
              height={72}
              showAxis
              valueFormatter={contributorValueFormat(c)}
            />
            <p className="text-[10px] uppercase tracking-wider text-white/35 mt-1 text-right">
              Last 7 days
            </p>
          </div>
        )}
      </div>

      <p className="text-sm text-white/70 leading-relaxed break-words">{c.explanation}</p>
    </div>
  );
}

/**
 * Compact "summary chip cluster" mode used on the Today view, so we get a
 * glanceable summary of contributors without three full hero panels stacked
 * on top of each other. Clicking opens the full breakdown view.
 */
function ContributorChipCluster({
  items,
  onOpen,
}: {
  items: ContributorSummary[];
  onOpen?: () => void;
}) {
  const sorted = [...items].sort(
    (a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status),
  );
  return (
    <div className="flex flex-wrap gap-1.5">
      {sorted.map((c) => (
        <span
          key={c.key}
          title={c.explanation}
          className={`inline-flex items-center gap-2 rounded-full pl-2 pr-2.5 py-1 text-xs ${STATUS_RING_CLASS[c.status]}`}
        >
          <StatusDot status={c.status} />
          <span className="text-white/85 font-medium">{c.label}</span>
          <span className="tabular-nums text-white/65 font-semibold">{formatValue(c)}</span>
        </span>
      ))}
      {onOpen && (
        <button
          type="button"
          onClick={onOpen}
          className="inline-flex items-center gap-1 rounded-full pl-2 pr-2.5 py-1 text-xs border border-white/10 text-white/55 hover:text-white hover:border-white/20 transition-colors"
        >
          See full
          <ChevronRight className="w-3 h-3" />
        </button>
      )}
    </div>
  );
}

export interface ContributorGridProps {
  title: string;
  items: ContributorSummary[];
  day: string;
  variant?: 'full' | 'compact';
  onOpen?: () => void;
}

export function ContributorGrid({
  title,
  items,
  day,
  variant = 'full',
  onOpen,
}: ContributorGridProps) {
  const sorted = useMemo(
    () =>
      [...items].sort((a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status)),
    [items],
  );

  const present = useMemo(() => sorted.filter((c) => c.status !== 'missing'), [sorted]);
  const missing = useMemo(() => sorted.filter((c) => c.status === 'missing'), [sorted]);

  const paths = useMemo(
    () => (variant === 'full' ? present.map((c) => c.source_path) : []),
    [present, variant],
  );
  const { history, axis } = useContributorHistory(variant === 'full' ? day : null, paths);

  if (!items || items.length === 0) return null;

  if (variant === 'compact') {
    return (
      <div className="rounded-2xl glass-card p-5 space-y-3">
        <div className="flex items-baseline justify-between gap-2">
          <p className="text-[10px] uppercase tracking-widest text-white/30">{title}</p>
          {onOpen && (
            <button
              type="button"
              onClick={onOpen}
              className="text-[10px] uppercase tracking-widest text-white/45 hover:text-white inline-flex items-center gap-1 transition-colors"
            >
              Open
              <ChevronRight className="w-3 h-3" />
            </button>
          )}
        </div>
        <ContributorChipCluster items={items} />
      </div>
    );
  }

  // Hero treatment kicks in only when the most urgent contributor is genuinely
  // worth surfacing. Otherwise we render an even grid of baby tiles.
  const heroEligible = present[0]?.status === 'pay_attention';
  const heroItem = heroEligible ? present[0] : null;
  const tileItems = heroEligible ? present.slice(1) : present;

  return (
    <div className="rounded-2xl glass-card p-5 space-y-4">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-[10px] uppercase tracking-widest text-white/30">{title}</p>
        {onOpen && (
          <button
            type="button"
            onClick={onOpen}
            className="text-[10px] uppercase tracking-widest text-white/45 hover:text-white inline-flex items-center gap-1 transition-colors"
          >
            Open
            <ChevronRight className="w-3 h-3" />
          </button>
        )}
      </div>

      {heroItem && (
        <HeroCard
          contributor={heroItem}
          history={history.get(heroItem.source_path) ?? []}
          dates={axis}
        />
      )}

      {tileItems.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 auto-rows-fr">
          {tileItems.map((c) => (
            <ContributorTile
              key={c.key}
              contributor={c}
              history={history.get(c.source_path) ?? []}
              dates={axis}
            />
          ))}
        </div>
      )}

      {missing.length > 0 && (
        <div className="pt-3 border-t border-white/[0.05] flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="text-[10px] uppercase tracking-widest text-white/30">
            Not exported
          </span>
          {missing.map((c, i) => (
            <span key={c.key} className="text-xs text-white/45">
              {c.label}
              {i < missing.length - 1 ? ',' : ''}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export function BaselineTable({ bundle }: { bundle: BaselineBundle | null }) {
  if (!bundle || bundle.deltas.length === 0) return null;
  return (
    <div className="rounded-2xl glass-card p-5 space-y-2">
      <p className="text-[10px] uppercase tracking-widest text-white/30">
        Baselines vs your usual
      </p>
      <div className="divide-y divide-white/[0.05]">
        {bundle.deltas.map((d) => {
          const ArrowIcon = d.direction === 'up' ? ArrowUp : d.direction === 'down' ? ArrowDown : Minus;
          const tone =
            d.preferred === 'higher' && d.direction === 'down'
              ? 'text-score-red'
              : d.preferred === 'lower' && d.direction === 'up'
                ? 'text-score-red'
                : d.direction === 'flat'
                  ? 'text-white/40'
                  : 'text-score-green';
          const fmt = (v: number | null) =>
            v == null ? '—' : `${v}${d.unit && d.unit !== 'score' ? ' ' + d.unit : ''}`;
          return (
            <div
              key={d.metric}
              className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 py-2 text-xs"
            >
              <span className="text-white/70">{d.label}</span>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-white/60">
                <span className="tabular-nums">{fmt(d.current)}</span>
                <span className="text-white/40">
                  7d {fmt(d.baseline_7d)} · 14d {fmt(d.baseline_14d)} · 30d {fmt(d.baseline_30d)}
                </span>
                {d.delta_14d != null && (
                  <span className={`inline-flex items-center gap-0.5 tabular-nums ${tone}`}>
                    <ArrowIcon className="w-3 h-3" />
                    {d.delta_14d > 0 ? '+' : ''}
                    {d.delta_14d}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
