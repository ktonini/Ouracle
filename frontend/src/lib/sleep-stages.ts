import { format } from 'date-fns';

export type SleepStageKey = 'deep' | 'light' | 'rem' | 'awake';

/** How much epoch detail to show on the sleep stage bar. */
export type SleepStageDetailPreference = 'auto' | '30_sec' | '5_min' | 'summary';

export const SLEEP_STAGE_DETAIL_STORAGE_KEY = 'cracked-oura-sleep-stage-detail';

export interface SleepStageSegment {
  stage: SleepStageKey;
  label: string;
  start: Date;
  end: Date;
  minutes: number;
  colorClass: string;
}

export interface SleepStageBuildResult {
  source: '30_sec' | '5_min' | 'aggregate';
  segments: SleepStageSegment[];
  totals: Record<SleepStageKey, number>;
  totalsMismatchNote: boolean;
}

export interface MovementMarker {
  timestamp: Date;
  value: number;
}

const STAGE_META: Record<
  SleepStageKey,
  { label: string; colorClass: string }
> = {
  deep: { label: 'Deep', colorClass: 'bg-indigo-500' },
  light: { label: 'Light', colorClass: 'bg-blue-400' },
  rem: { label: 'REM', colorClass: 'bg-violet-500' },
  awake: { label: 'Awake', colorClass: 'bg-white/20' },
};

const EMPTY_TOTALS: Record<SleepStageKey, number> = {
  deep: 0,
  light: 0,
  rem: 0,
  awake: 0,
};

function parseTimestamp(raw: unknown): Date | null {
  if (raw instanceof Date) {
    return Number.isNaN(raw.getTime()) ? null : raw;
  }
  if (typeof raw === 'number' && Number.isFinite(raw)) {
    const d = new Date(raw);
    return Number.isNaN(d.getTime()) ? null : d;
  }
  if (typeof raw !== 'string' || !raw.trim()) return null;
  const normalized = raw.includes('T') ? raw : raw.replace(' ', 'T');
  const d = new Date(normalized);
  return Number.isNaN(d.getTime()) ? null : d;
}

function mapStageCode(value: number): SleepStageKey | null {
  switch (value) {
    case 1:
      return 'deep';
    case 2:
      return 'light';
    case 3:
      return 'rem';
    case 4:
      return 'awake';
    default:
      return null;
  }
}

function isNonEmptyArray(value: unknown): value is unknown[] {
  return Array.isArray(value) && value.length > 0;
}

function normalizePhaseEpochs(items: unknown[]): { timestamp: Date; stage: SleepStageKey }[] {
  const epochs: { timestamp: Date; stage: SleepStageKey }[] = [];

  for (const item of items) {
    if (item == null) continue;

    let timestampRaw: unknown;
    let valueRaw: unknown;

    if (typeof item === 'object') {
      const rec = item as Record<string, unknown>;
      timestampRaw = rec.timestamp ?? rec.time;
      valueRaw = rec.value ?? rec.stage ?? rec.sleep_phase;
    } else if (typeof item === 'number' || typeof item === 'string') {
      valueRaw = item;
      continue;
    } else {
      continue;
    }

    if (valueRaw == null) continue;
    const numeric = Number(valueRaw);
    if (!Number.isFinite(numeric)) continue;

    const stage = mapStageCode(numeric);
    if (!stage) continue;

    const timestamp = parseTimestamp(timestampRaw);
    if (!timestamp) continue;

    epochs.push({ timestamp, stage });
  }

  return epochs.sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());
}

function mergeEpochsIntoSegments(
  epochs: { timestamp: Date; stage: SleepStageKey }[],
  intervalMs: number,
): SleepStageSegment[] {
  if (epochs.length === 0) return [];

  const segments: SleepStageSegment[] = [];

  for (let i = 0; i < epochs.length; i++) {
    const { timestamp: start, stage } = epochs[i];
    const end =
      i < epochs.length - 1
        ? epochs[i + 1].timestamp
        : new Date(start.getTime() + intervalMs);
    const minutes = (end.getTime() - start.getTime()) / 60000;
    const meta = STAGE_META[stage];

    const last = segments[segments.length - 1];
    if (last && last.stage === stage) {
      last.end = end;
      last.minutes = (end.getTime() - last.start.getTime()) / 60000;
      continue;
    }

    segments.push({
      stage,
      label: meta.label,
      start,
      end,
      minutes,
      colorClass: meta.colorClass,
    });
  }

  return segments;
}

function sumTotals(segments: SleepStageSegment[]): Record<SleepStageKey, number> {
  const totals = { ...EMPTY_TOTALS };
  for (const seg of segments) {
    totals[seg.stage] += seg.minutes;
  }
  return totals;
}

function aggregateMinutesFromSession(session: Record<string, unknown>): Record<SleepStageKey, number> {
  return {
    deep: session.deep_sleep_duration != null ? Number(session.deep_sleep_duration) / 60 : 0,
    light: session.light_sleep_duration != null ? Number(session.light_sleep_duration) / 60 : 0,
    rem: session.rem_sleep_duration != null ? Number(session.rem_sleep_duration) / 60 : 0,
    awake: session.awake_time != null ? Number(session.awake_time) / 60 : 0,
  };
}

function totalsMismatch(
  detailed: Record<SleepStageKey, number>,
  aggregate: Record<SleepStageKey, number>,
): boolean {
  const detailSum = Object.values(detailed).reduce((sum, m) => sum + m, 0);
  const aggregateSum = Object.values(aggregate).reduce((sum, m) => sum + m, 0);
  return Math.abs(detailSum - aggregateSum) > 20;
}

function buildEpochSegments(
  session: Record<string, unknown>,
  key: 'sleep_phase_30_sec' | 'sleep_phase_5_min',
  intervalMs: number,
  source: '30_sec' | '5_min',
): SleepStageBuildResult | null {
  const raw = session[key];
  if (!isNonEmptyArray(raw)) return null;

  const epochs = normalizePhaseEpochs(raw);
  if (epochs.length === 0) return null;

  const segments = mergeEpochsIntoSegments(epochs, intervalMs);
  if (segments.length === 0) return null;

  const totals = sumTotals(segments);
  const aggregate = aggregateMinutesFromSession(session);

  return {
    source,
    segments,
    totals,
    totalsMismatchNote: totalsMismatch(totals, aggregate),
  };
}

function sessionStartTime(session: Record<string, unknown>): Date | null {
  return (
    parseTimestamp(session.start_time) ??
    parseTimestamp(session.bedtime_start) ??
    null
  );
}

function buildAggregateSegments(session: Record<string, unknown>): SleepStageBuildResult {
  const ordered = (
    [
      { stage: 'deep' as const, seconds: Number(session.deep_sleep_duration) || 0 },
      { stage: 'rem' as const, seconds: Number(session.rem_sleep_duration) || 0 },
      { stage: 'light' as const, seconds: Number(session.light_sleep_duration) || 0 },
      { stage: 'awake' as const, seconds: Number(session.awake_time) || 0 },
    ] as const
  ).filter((s) => s.seconds > 0);

  const segments: SleepStageSegment[] = [];
  let cursor = sessionStartTime(session);

  for (const { stage, seconds } of ordered) {
    const meta = STAGE_META[stage];
    const minutes = seconds / 60;
    const start = cursor ?? new Date(0);
    const end = cursor ? new Date(cursor.getTime() + seconds * 1000) : new Date(seconds * 1000);
    segments.push({
      stage,
      label: meta.label,
      start,
      end,
      minutes,
      colorClass: meta.colorClass,
    });
    if (cursor) cursor = end;
  }

  const totals = sumTotals(segments);

  return {
    source: 'aggregate',
    segments,
    totals,
    totalsMismatchNote: false,
  };
}

export function buildSleepStageSegments(
  session: unknown,
  preference: SleepStageDetailPreference = 'auto',
): SleepStageBuildResult {
  if (!session || typeof session !== 'object') {
    return {
      source: 'aggregate',
      segments: [],
      totals: { ...EMPTY_TOTALS },
      totalsMismatchNote: false,
    };
  }

  const rec = session as Record<string, unknown>;

  if (preference === 'summary') {
    return buildAggregateSegments(rec);
  }

  if (preference === '30_sec') {
    const from30 = buildEpochSegments(rec, 'sleep_phase_30_sec', 30_000, '30_sec');
    if (from30) return from30;
    const from5 = buildEpochSegments(rec, 'sleep_phase_5_min', 300_000, '5_min');
    if (from5) return from5;
    return buildAggregateSegments(rec);
  }

  if (preference === '5_min') {
    const from5 = buildEpochSegments(rec, 'sleep_phase_5_min', 300_000, '5_min');
    if (from5) return from5;
    const from30 = buildEpochSegments(rec, 'sleep_phase_30_sec', 30_000, '30_sec');
    if (from30) return from30;
    return buildAggregateSegments(rec);
  }

  // auto: finest available export
  const from30 = buildEpochSegments(rec, 'sleep_phase_30_sec', 30_000, '30_sec');
  if (from30) return from30;

  const from5 = buildEpochSegments(rec, 'sleep_phase_5_min', 300_000, '5_min');
  if (from5) return from5;

  return buildAggregateSegments(rec);
}

export function readSleepStageDetailPreference(): SleepStageDetailPreference {
  if (typeof localStorage === 'undefined') return 'auto';
  const raw = localStorage.getItem(SLEEP_STAGE_DETAIL_STORAGE_KEY);
  if (raw === '30_sec' || raw === '5_min' || raw === 'summary' || raw === 'auto') return raw;
  return 'auto';
}

export function sleepStageDetailLabel(preference: SleepStageDetailPreference, source: SleepStageBuildResult['source']): string {
  if (preference === 'summary' || source === 'aggregate') return 'Summary blocks';
  if (source === '30_sec') return '30s epochs';
  if (source === '5_min') return '5m epochs';
  return 'Auto';
}

export function buildMovementMarkers(session: unknown): MovementMarker[] {
  if (!session || typeof session !== 'object') return [];
  const raw = (session as Record<string, unknown>).movement_30_sec;
  if (!isNonEmptyArray(raw)) return [];

  const markers: MovementMarker[] = [];
  for (const item of raw) {
    if (item == null || typeof item !== 'object') continue;
    const rec = item as Record<string, unknown>;
    const timestamp = parseTimestamp(rec.timestamp ?? rec.time);
    const value = Number(rec.value);
    if (!timestamp || !Number.isFinite(value)) continue;
    markers.push({ timestamp, value });
  }

  return markers.sort((a, b) => a.timestamp.getTime() - b.timestamp.getTime());
}

export function formatSegmentRange(seg: SleepStageSegment): string {
  return `${format(seg.start, 'HH:mm')} – ${format(seg.end, 'HH:mm')}`;
}

export function formatStageMinutes(minutes: number): string {
  const rounded = Math.round(minutes);
  if (rounded < 60) return `${rounded}m`;
  const h = Math.floor(rounded / 60);
  const m = rounded % 60;
  return m > 0 ? `${h}h ${m}m` : `${h}h`;
}

export const SLEEP_STAGE_LEGEND_ORDER: SleepStageKey[] = ['deep', 'rem', 'light', 'awake'];
