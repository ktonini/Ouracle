import { format } from 'date-fns';
import { normalizeResilience } from '@/lib/resilience';

export interface DaySummary {
  date: string;
  greeting: string;
  scores: {
    sleep: number | null;
    readiness: number | null;
    activity: number | null;
  };
  metrics: {
    steps: number | null;
    totalSleepMinutes: number | null;
    totalSleepFormatted: string | null;
    restingHr: number | null;
    hrv: number | null;
    calories: number | null;
    resilience: string | null;
  };
  primarySleepSession: {
    start: string | null;
    end: string | null;
    durationMinutes: number | null;
    durationFormatted: string | null;
    deepMinutes: number | null;
    remMinutes: number | null;
    lightMinutes: number | null;
    awakeMinutes: number | null;
    avgHr: number | null;
    avgHrv: number | null;
  };
  timeline: TimelineItem[];
  tags: string[];
  insight: string;
  batterySamples: BatterySample[];
  battery: number | null;
  batteryTimestamp: string | null;
}

export interface BatterySample {
  timestamp: string;
  level: number;
  charging: boolean;
  in_charger: boolean;
}

export function batteryLevelTone(level: number | null): 'green' | 'yellow' | 'coral' | 'muted' {
  if (level == null) return 'muted';
  if (level > 30) return 'green';
  if (level >= 21) return 'yellow';
  return 'coral';
}

function parseSampleTime(timestamp: string): number {
  const normalized = timestamp.replace(' ', 'T');
  return new Date(normalized).getTime();
}

function normalizeBatterySamples(raw: any[]): BatterySample[] {
  return raw
    .map((b) => ({
      timestamp: String(b.timestamp ?? ''),
      level: typeof b.level === 'number' ? b.level : Number(b.level) || 0,
      charging: Boolean(b.charging),
      in_charger: Boolean(b.in_charger),
    }))
    .filter((b) => b.timestamp)
    .sort((a, b) => parseSampleTime(a.timestamp) - parseSampleTime(b.timestamp));
}

export interface TimelineItem {
  type: 'sleep' | 'workout' | 'meditation' | 'tag';
  time: string;
  label: string;
  detail?: string;
}

function formatMinutes(minutes: number | null | undefined): string | null {
  if (minutes == null || isNaN(minutes)) return null;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function getGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 6) return 'Good night';
  if (hour < 12) return 'Good morning';
  if (hour < 17) return 'Good afternoon';
  return 'Good evening';
}

function generateInsight(summary: DaySummary): string {
  const { scores, metrics } = summary;
  const parts: string[] = [];

  if (scores.sleep != null && scores.sleep < 60) {
    parts.push('Sleep score was below average');
  } else if (scores.sleep != null && scores.sleep >= 85) {
    parts.push('Strong sleep performance');
  }

  if (scores.readiness != null && scores.readiness < 50) {
    parts.push('Recovery may need attention');
  } else if (scores.readiness != null && scores.readiness >= 80) {
    parts.push('Well recovered and ready');
  }

  if (scores.activity != null && scores.activity >= 75) {
    parts.push('Active day');
  }

  if (metrics.steps != null && metrics.steps > 10000) {
    parts.push('Hit 10k+ steps');
  }

  if (parts.length === 0) {
    return 'No standout patterns for this day';
  }

  return parts.join(' · ');
}

export function buildDaySummary(raw: any, dateString: string): DaySummary {
  const sleepScore = raw?.sleep?.score ?? raw?.scores?.sleep ?? null;
  const readinessScore = raw?.readiness?.score ?? raw?.scores?.readiness ?? null;
  const activityScore = raw?.activity?.score ?? raw?.scores?.activity ?? null;

  const totalSleepMin = raw?.sleep?.total_sleep_duration
    ? Math.round(raw.sleep.total_sleep_duration / 60)
    : raw?.sleep_session?.total_sleep_duration
      ? Math.round(raw.sleep_session.total_sleep_duration / 60)
      : null;

  const primarySession = raw?.sleep_session || raw?.sleep_sessions?.[0] || null;
  const deepMin = primarySession?.deep_sleep_duration
    ? Math.round(primarySession.deep_sleep_duration / 60)
    : null;
  const remMin = primarySession?.rem_sleep_duration
    ? Math.round(primarySession.rem_sleep_duration / 60)
    : null;
  const lightMin = primarySession?.light_sleep_duration
    ? Math.round(primarySession.light_sleep_duration / 60)
    : null;
  const awakeMin = primarySession?.awake_time
    ? Math.round(primarySession.awake_time / 60)
    : null;

  // Use correct field names from backend schema
  const avgHr = primarySession?.average_heart_rate ?? null;
  const avgHrv = primarySession?.average_hrv ?? null;

  const resilienceLevel = normalizeResilience(raw?.resilience)?.level ?? null;

  const batterySamples = normalizeBatterySamples(
    Array.isArray(raw?.ring_battery) ? raw.ring_battery : [],
  );
  const latestBattery = batterySamples.length > 0 ? batterySamples[batterySamples.length - 1] : null;
  const battery = latestBattery?.level ?? null;
  const batteryTimestamp = latestBattery?.timestamp ?? null;

  const tags: string[] = [];
  if (raw?.tags && Array.isArray(raw.tags)) {
    raw.tags.forEach((t: any) => {
      if (t?.tag_type_code && !tags.includes(t.tag_type_code)) tags.push(t.tag_type_code);
      if (t?.comment && !tags.includes(t.comment)) tags.push(t.comment);
    });
  }

  const timeline: TimelineItem[] = [];

  if (primarySession?.start_time) {
    const startTime = typeof primarySession.start_time === 'string'
      ? primarySession.start_time.replace(' ', 'T')
      : primarySession.start_time;
    const start = new Date(startTime);
    timeline.push({
      type: 'sleep',
      time: format(start, 'HH:mm'),
      label: 'Sleep',
      detail: totalSleepMin ? formatMinutes(totalSleepMin) ?? undefined : undefined,
    });
  }

  if (raw?.workouts && Array.isArray(raw.workouts)) {
    raw.workouts.forEach((w: any) => {
      if (w?.start_time) {
        const startTime = typeof w.start_time === 'string'
          ? w.start_time.replace(' ', 'T')
          : w.start_time;
        const start = new Date(startTime);
        timeline.push({
          type: 'workout',
          time: format(start, 'HH:mm'),
          label: w.activity || w.type || 'Workout',
          detail: w.intensity ? `${w.intensity}` : undefined,
        });
      }
    });
  }

  const summary: DaySummary = {
    date: dateString,
    greeting: getGreeting(),
    scores: {
      sleep: typeof sleepScore === 'number' ? Math.round(sleepScore) : null,
      readiness: typeof readinessScore === 'number' ? Math.round(readinessScore) : null,
      activity: typeof activityScore === 'number' ? Math.round(activityScore) : null,
    },
    metrics: {
      steps: raw?.activity?.steps ?? null,
      totalSleepMinutes: totalSleepMin,
      totalSleepFormatted: formatMinutes(totalSleepMin),
      restingHr: avgHr,
      hrv: avgHrv,
      calories: raw?.activity?.total_calories ?? raw?.activity?.calories_total ?? null,
      resilience: resilienceLevel,
    },
    primarySleepSession: {
      start: primarySession?.start_time ?? null,
      end: primarySession?.end_time ?? null,
      durationMinutes: totalSleepMin,
      durationFormatted: formatMinutes(totalSleepMin),
      deepMinutes: deepMin,
      remMinutes: remMin,
      lightMinutes: lightMin,
      awakeMinutes: awakeMin,
      avgHr,
      avgHrv,
    },
    timeline,
    tags,
    batterySamples,
    battery,
    batteryTimestamp,
    insight: '',
  };

  summary.insight = generateInsight(summary);

  return summary;
}
