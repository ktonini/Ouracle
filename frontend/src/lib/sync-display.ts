import { formatDistanceToNow, formatDistanceToNowStrict } from 'date-fns';

import type { AutomationStatusResponse, SyncFreshness } from '@/lib/api';
import { parseLocalDate } from '@/lib/utils';

function computeNextDailyRunFromSchedule(now: Date, scheduleTime: string): Date {
  let hour = 11;
  let minute = 0;
  try {
    const [h, m] = scheduleTime.split(':').map((part) => parseInt(part, 10));
    if (h >= 0 && h <= 23 && m >= 0 && m <= 59) {
      hour = h;
      minute = m;
    }
  } catch {
    // fallback 11:00
  }
  const candidate = new Date(now);
  candidate.setHours(hour, minute, 0, 0);
  if (candidate.getTime() <= now.getTime()) {
    candidate.setDate(candidate.getDate() + 1);
  }
  return candidate;
}

function parseNextRun(nextRun: string | null | undefined): Date | null {
  if (!nextRun) return null;
  try {
    const parsed = parseLocalDate(nextRun);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  } catch {
    return null;
  }
}

/** Human label for the next scheduled auto-sync; never uses an "ago" suffix. */
export function nextAutoSyncLabel(
  nextRun: string | null | undefined,
  scheduleTime: string | null | undefined,
): string | null {
  const now = new Date();
  let target = parseNextRun(nextRun);

  if (!target) {
    if (!scheduleTime) return null;
    target = computeNextDailyRunFromSchedule(now, scheduleTime);
  } else if (target.getTime() <= now.getTime()) {
    if (!scheduleTime) return null;
    target = computeNextDailyRunFromSchedule(now, scheduleTime);
  }

  const msUntil = target.getTime() - now.getTime();
  if (msUntil < 60_000) return 'due now';
  return `in ${formatDistanceToNowStrict(target, { addSuffix: false })}`;
}

export function isWaitingForExport(
  status: AutomationStatusResponse['status'] | string | undefined,
): boolean {
  return status === 'Waiting for export';
}

export function isAutomationBusy(
  status: AutomationStatusResponse['status'] | string | undefined,
): boolean {
  if (!status) return false;
  if (isWaitingForExport(status)) return false;
  return status !== 'Idle' && status !== 'Error' && status !== 'otp_needed' && status !== 'Waiting';
}

export function syncStatusHeadline(
  automation: Pick<AutomationStatusResponse, 'status' | 'message' | 'last_run'> | null | undefined,
  freshness: SyncFreshness | null | undefined,
): string {
  if (!automation) return 'Checking sync…';

  if (isWaitingForExport(automation.status)) {
    return automation.message || 'Waiting for Oura export…';
  }

  if (isAutomationBusy(automation.status)) {
    return automation.message || 'Sync in progress…';
  }

  if (freshness?.latest_day) {
    if (freshness.status === 'fresh') {
      return `Data through ${freshness.latest_day}`;
    }
    if (freshness.days_behind != null && freshness.days_behind > 0) {
      return `Data through ${freshness.latest_day} (${freshness.days_behind} day${freshness.days_behind === 1 ? '' : 's'} behind)`;
    }
    return `Data through ${freshness.latest_day}`;
  }

  if (automation.last_run) {
    return `Last ingest ${formatDistanceToNow(parseLocalDate(automation.last_run), { addSuffix: true })}`;
  }

  return 'No data ingested yet';
}

export function syncStatusSubline(
  automation: Pick<AutomationStatusResponse, 'status' | 'last_run'> | null | undefined,
  freshness: SyncFreshness | null | undefined,
): string | null {
  if (isWaitingForExport(automation?.status)) {
    return 'Checks continue while the app is running, including after restart';
  }
  if (!automation?.last_run || isAutomationBusy(automation.status)) return null;

  const ingestAgo = formatDistanceToNow(parseLocalDate(automation.last_run), { addSuffix: true });

  if (freshness && freshness.status !== 'fresh') {
    return `Last ingest attempt ${ingestAgo} — data still stale`;
  }

  return `Last ingest ${ingestAgo}`;
}

export function syncIndicatorTone(
  automationStatus: string | undefined,
  freshness: SyncFreshness | null | undefined,
): 'busy' | 'error' | 'fresh' | 'stale' | 'unknown' {
  if (isWaitingForExport(automationStatus)) return 'stale';
  if (isAutomationBusy(automationStatus)) return 'busy';
  if (automationStatus === 'Error') return 'error';
  if (freshness?.status === 'fresh') return 'fresh';
  if (freshness && freshness.status !== 'empty') return 'stale';
  return 'unknown';
}
