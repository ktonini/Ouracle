import { format, subDays } from 'date-fns';

export interface ResilienceSnapshot {
  day: string;
  level: string | null;
  sleep_recovery: number | null;
  daytime_recovery: number | null;
  stress: number | null;
}

export interface ResilienceSelection extends ResilienceSnapshot {
  isExactDay: boolean;
  sourceDay: string;
}

export interface QueryPoint {
  date: string;
  value: number | string | null;
}

function hasUsableMetrics(row: ResilienceSnapshot): boolean {
  return (
    row.level != null ||
    row.sleep_recovery != null ||
    row.daytime_recovery != null ||
    row.stress != null
  );
}

export function normalizeResilience(input: unknown): ResilienceSnapshot | null {
  const raw = Array.isArray(input) ? input[0] : input;
  if (!raw || typeof raw !== 'object') return null;

  const row = raw as Record<string, unknown>;
  const day =
    typeof row.day === 'string'
      ? row.day
      : row.day != null
        ? String(row.day).slice(0, 10)
        : null;

  const level =
    typeof row.level === 'string' && row.level.trim()
      ? row.level.trim()
      : null;

  return {
    day: day ?? '',
    level,
    sleep_recovery: toNumber(row.sleep_recovery),
    daytime_recovery: toNumber(row.daytime_recovery),
    stress: toNumber(row.stress),
  };
}

function toNumber(value: unknown): number | null {
  if (value == null || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function mergeResilienceHistory(
  level: QueryPoint[],
  sleepRecovery: QueryPoint[],
  daytimeRecovery: QueryPoint[],
  stress: QueryPoint[],
): ResilienceSnapshot[] {
  const byDay = new Map<string, ResilienceSnapshot>();

  const ensure = (day: string): ResilienceSnapshot => {
    let row = byDay.get(day);
    if (!row) {
      row = {
        day,
        level: null,
        sleep_recovery: null,
        daytime_recovery: null,
        stress: null,
      };
      byDay.set(day, row);
    }
    return row;
  };

  for (const point of level) {
    const day = normalizeDay(point.date);
    if (!day) continue;
    const row = ensure(day);
    if (point.value != null && String(point.value).trim()) {
      row.level = String(point.value).trim();
    }
  }

  for (const [points, field] of [
    [sleepRecovery, 'sleep_recovery'],
    [daytimeRecovery, 'daytime_recovery'],
    [stress, 'stress'],
  ] as const) {
    for (const point of points) {
      const day = normalizeDay(point.date);
      if (!day) continue;
      const row = ensure(day);
      const n = toNumber(point.value);
      if (n != null) row[field] = n;
    }
  }

  return Array.from(byDay.values()).sort((a, b) => a.day.localeCompare(b.day));
}

function normalizeDay(value: string | Date | null | undefined): string | null {
  if (value == null) return null;
  if (value instanceof Date) return format(value, 'yyyy-MM-dd');
  const text = String(value);
  return text.length >= 10 ? text.slice(0, 10) : text;
}

export function selectResilienceForDay(
  selectedDay: string,
  selectedDayRow: ResilienceSnapshot | null,
  history: ResilienceSnapshot[],
): ResilienceSelection | null {
  if (selectedDayRow?.day && hasUsableMetrics(selectedDayRow)) {
    return {
      ...selectedDayRow,
      day: selectedDay,
      isExactDay: true,
      sourceDay: selectedDay,
    };
  }

  const candidates = history.filter(
    (row) => row.day <= selectedDay && hasUsableMetrics(row),
  );
  if (candidates.length === 0) return null;

  const latest = candidates[candidates.length - 1];
  return {
    ...latest,
    isExactDay: latest.day === selectedDay,
    sourceDay: latest.day,
  };
}

export function resilienceHistoryRange(selectedDay: string, days = 365): {
  start: string;
  end: string;
} {
  const end = selectedDay;
  const start = format(subDays(new Date(`${selectedDay}T12:00:00`), days), 'yyyy-MM-dd');
  return { start, end };
}

export function hasReadinessStressBalance(readiness: unknown): boolean {
  if (!readiness || typeof readiness !== 'object') return false;
  const r = readiness as Record<string, unknown>;
  return r.stress_high != null || r.recovery_high != null;
}

export function hasDaytimeStressSeries(activity: unknown): boolean {
  if (!activity || typeof activity !== 'object') return false;
  const stress = (activity as Record<string, unknown>).stress;
  return Array.isArray(stress) && stress.length > 0;
}

export function hasAnyResilienceContent(
  selection: ResilienceSelection | null,
  readiness: unknown,
  activity: unknown,
): boolean {
  return (
    selection != null ||
    hasReadinessStressBalance(readiness) ||
    hasDaytimeStressSeries(activity)
  );
}
