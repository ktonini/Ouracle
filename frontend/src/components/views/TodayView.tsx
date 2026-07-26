import { useEffect, useState } from 'react';
import { useDashboard } from '@/contexts/DashboardContext';
import { buildDaySummary } from '@/lib/day-summary';
import { MetricPill } from '@/components/health/MetricPill';
import { HeartPulse, Moon, Flame, Sparkles, ArrowUpRight, ChevronRight, Footprints, Heart, Zap, Tag } from 'lucide-react';
import { format } from 'date-fns';
import type { AppView } from '@/types/app-view';
import { useInsights, useSyncFreshness } from '@/hooks/useInsights';
import {
  ActionCardsList,
  ContributorGrid,
  GuidanceBlock,
  SyncFreshnessChip,
} from '@/components/health/InsightsPanels';

interface TodayViewProps {
  onNavigate: (view: AppView) => void;
  timeOfDay: 'morning' | 'afternoon' | 'evening';
}

function getScoreColor(score: number, type: 'readiness' | 'sleep' | 'activity'): string {
  if (score >= 85) return type === 'readiness' ? '#4ECDC4' : type === 'sleep' ? '#A2D3E8' : '#FFD166';
  if (score >= 70) return '#FFD166';
  return '#FC6558';
}

function getScoreLabel(score: number): string {
  if (score >= 85) return 'Optimal';
  if (score >= 70) return 'Good';
  if (score >= 55) return 'Fair';
  return 'Attention';
}

export function TodayView({ onNavigate, timeOfDay }: TodayViewProps) {
  const { data, isDataLoading, selectedDate } = useDashboard();

  const [animateIn, setAnimateIn] = useState(false);
  const dayKey = format(selectedDate, 'yyyy-MM-dd');
  const insights = useInsights(dayKey);
  const { freshness } = useSyncFreshness();

  useEffect(() => {
    setAnimateIn(false);
    const timer = setTimeout(() => setAnimateIn(true), 50);
    return () => clearTimeout(timer);
  }, [selectedDate]);

  if (isDataLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-white/30 text-sm">Loading today&apos;s data...</div>
      </div>
    );
  }

  const summary = buildDaySummary(data, dayKey);
  const greeting = timeOfDay === 'morning' ? 'Good morning' : timeOfDay === 'afternoon' ? 'Good afternoon' : 'Good evening';

  const scores = [
    {
      id: 'readiness' as const,
      title: 'Readiness',
      score: summary.scores.readiness,
      icon: HeartPulse,
      desc: summary.metrics.restingHr ? `${summary.metrics.restingHr} bpm resting HR` : 'Resting HR & HRV balance',
      metric: summary.metrics.hrv ? `HRV: ${summary.metrics.hrv}` : '',
    },
    {
      id: 'sleep' as const,
      title: 'Sleep',
      score: summary.scores.sleep,
      icon: Moon,
      desc: summary.metrics.totalSleepFormatted ? `${summary.metrics.totalSleepFormatted} total sleep time` : 'Sleep duration',
      metric: '',
    },
    {
      id: 'activity' as const,
      title: 'Activity',
      score: summary.scores.activity,
      icon: Flame,
      desc: summary.metrics.calories ? `${summary.metrics.calories.toLocaleString()} kcal total` : 'Daily activity',
      metric: summary.metrics.steps ? `${summary.metrics.steps.toLocaleString()} steps` : '',
    },
  ];

  return (
    <div className={`p-6 md:p-8 space-y-6 max-w-7xl mx-auto ${animateIn ? 'animate-fadeIn' : 'opacity-0'}`}>
      {/* Atmospheric Greeting Banner */}
      <div className="relative overflow-hidden rounded-3xl glass-card p-8 shadow-2xl">
        <div className="relative z-10 space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="inline-flex items-center gap-2 bg-white/[0.06] border border-white/[0.08] px-3 py-1 rounded-full text-xs text-enso-blue font-medium backdrop-blur-sm">
              <Sparkles className="w-3.5 h-3.5" />
              <span>Daily Health Summary</span>
            </div>
            <SyncFreshnessChip freshness={freshness} />
          </div>
          {insights.guidance ? (
            <GuidanceBlock guidance={insights.guidance} />
          ) : (
            <>
              <h2 className="font-serif text-3xl md:text-4xl lg:text-5xl text-white leading-tight tracking-wide">
                {greeting}
              </h2>
              <p className="text-sm text-white/50 leading-relaxed max-w-2xl">
                Loading deterministic guidance for {dayKey}…
              </p>
            </>
          )}
          <div className="flex flex-wrap items-center gap-4 pt-2 text-sm text-white/40">
            {summary.metrics.resilience && (
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-score-green" />
                <span>Resilience: <strong className="text-white/70">{summary.metrics.resilience}</strong></span>
              </div>
            )}
            {summary.scores.sleep != null && (
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-enso-blue" />
                <span>Sleep: <strong className="text-white/70">{summary.scores.sleep}</strong></span>
              </div>
            )}
            {summary.metrics.steps != null && (
              <div className="flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-score-yellow" />
                <span>Steps: <strong className="text-white/70">{summary.metrics.steps.toLocaleString()}</strong></span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Today's action cards (above scores) */}
      <ActionCardsList cards={insights.actionCards} />

      {/* Three Core Score Cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        {scores.map((s) => {
          const Icon = s.icon;
          const strokeColor = getScoreColor(s.score ?? 0, s.id);
          const radius = 44;
          const circumference = 2 * Math.PI * radius;

          return (
            <ScoreRingCard
              key={s.id}
              icon={Icon}
              title={s.title}
              score={s.score}
              strokeColor={strokeColor}
              label={s.score != null ? getScoreLabel(s.score) : '--'}
              desc={s.desc}
              metric={s.metric}
              onClick={() => onNavigate(s.id === 'readiness' ? 'readiness' : s.id === 'sleep' ? 'sleep' : 'activity')}
              circumference={circumference}
              radius={radius}
            />
          );
        })}
      </div>

      {/* Quick Metrics Row */}
      <div className="flex flex-wrap gap-2">
        <MetricPill
          label="Steps"
          value={summary.metrics.steps?.toLocaleString() ?? null}
          icon={<Footprints className="h-3.5 w-3.5" />}
        />
        <MetricPill
          label="Sleep"
          value={summary.metrics.totalSleepFormatted}
          icon={<Moon className="h-3.5 w-3.5" />}
        />
        <MetricPill
          label="Resting HR"
          value={summary.metrics.restingHr}
          unit="bpm"
          icon={<Heart className="h-3.5 w-3.5" />}
        />
        <MetricPill
          label="HRV"
          value={summary.metrics.hrv}
          icon={<Zap className="h-3.5 w-3.5" />}
        />
        <MetricPill
          label="Calories"
          value={summary.metrics.calories?.toLocaleString() ?? null}
          icon={<Flame className="h-3.5 w-3.5" />}
        />
      </div>

      {/* Tags */}
      <div className="rounded-xl glass-card p-4">
        <div className="flex items-center gap-2 mb-2">
          <Tag className="h-4 w-4 text-white/40" />
          <p className="text-[10px] uppercase tracking-widest text-white/30">Tags</p>
        </div>
        {summary.tags.length > 0 ? (
          <div className="flex flex-wrap gap-2">
            {summary.tags.map((tag: string, i: number) => (
              <span
                key={i}
                className="text-xs bg-white/[0.06] text-white/60 px-2.5 py-1 rounded-md border border-white/[0.08]"
              >
                #{tag}
              </span>
            ))}
          </div>
        ) : (
          <p className="text-xs text-white/30">No tags logged</p>
        )}
      </div>

      {/* Contributors (sleep / readiness / activity) — compact summaries on Today,
          full hero + tile breakdown lives on the dedicated views */}
      {insights.contributors && (
        <div className="space-y-3 min-w-0">
          <ContributorGrid
            variant="compact"
            title="Sleep contributors"
            items={insights.contributors.sleep}
            day={dayKey}
            onOpen={() => onNavigate('sleep')}
          />
          <ContributorGrid
            variant="compact"
            title="Readiness contributors"
            items={insights.contributors.readiness}
            day={dayKey}
            onOpen={() => onNavigate('readiness')}
          />
          <ContributorGrid
            variant="compact"
            title="Activity contributors"
            items={insights.contributors.activity}
            day={dayKey}
            onOpen={() => onNavigate('activity')}
          />
        </div>
      )}
    </div>
  );
}

// Score Ring Card (concept's signature component)
function ScoreRingCard({
  icon: Icon, title, score, strokeColor, label, desc, metric, onClick,
  circumference, radius,
}: {
  icon: React.ElementType;
  title: string;
  score: number | null;
  strokeColor: string;
  label: string;
  desc: string;
  metric: string;
  onClick: () => void;
  circumference: number;
  radius: number;
}) {
  const [offset, setOffset] = useState(circumference);
  const size = 104;
  const normalizedScore = score ?? 0;

  useEffect(() => {
    const timer = setTimeout(() => {
      setOffset(circumference - (normalizedScore / 100) * circumference);
    }, 300);
    return () => clearTimeout(timer);
  }, [normalizedScore, circumference]);

  return (
    <div onClick={onClick} className="glass-card rounded-2xl p-5 hover:bg-white/[0.07] transition-all cursor-pointer group flex flex-col justify-between space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-white/50 group-hover:text-white/80 transition-colors">
          <Icon className="w-4 h-4" />
          <span className="font-serif text-base tracking-wide">{title}</span>
        </div>
        <ChevronRight className="w-4 h-4 text-white/20 group-hover:text-white/50 group-hover:translate-x-0.5 transition-all" />
      </div>

      <div className="flex items-center gap-5">
        {/* Animated Score Ring */}
        <div className="relative flex-shrink-0" style={{ width: size, height: size }}>
          <svg width={size} height={size} className="-rotate-90">
            <circle cx={size / 2} cy={size / 2} r={radius} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="7" />
            <circle
              cx={size / 2} cy={size / 2} r={radius} fill="none"
              stroke={strokeColor} strokeWidth="7" strokeLinecap="round"
              strokeDasharray={circumference} strokeDashoffset={offset}
              className="score-ring"
              style={{ filter: `drop-shadow(0 0 10px ${strokeColor}40)` }}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center px-2">
            <span className="font-serif text-2xl font-bold text-white">{score ?? '--'}</span>
            <span className="text-[9px] uppercase tracking-wider font-semibold mt-0.5 max-w-full truncate" style={{ color: score != null ? strokeColor : 'rgba(255,255,255,0.3)' }}>
              {label}
            </span>
          </div>
        </div>

        <div className="space-y-1">
          <p className="text-xs text-white/35 leading-relaxed">{desc}</p>
          {metric && <p className="text-[11px] text-white/50 font-medium">{metric}</p>}
        </div>
      </div>

      <div className="flex items-center text-xs text-enso-blue font-medium group-hover:underline">
        View Details <ArrowUpRight className="w-3 h-3 ml-1" />
      </div>
    </div>
  );
}
