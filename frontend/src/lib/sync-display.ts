import { formatDistanceToNow } from 'date-fns';

import type { AutomationStatusResponse, SyncFreshness } from '@/lib/api';
import { parseLocalDate } from '@/lib/utils';

export function isAutomationBusy(
  status: AutomationStatusResponse['status'] | string | undefined,
): boolean {
  if (!status) return false;
  return status !== 'Idle' && status !== 'Error' && status !== 'otp_needed' && status !== 'Waiting';
}

export function syncStatusHeadline(
  automation: Pick<AutomationStatusResponse, 'status' | 'message' | 'last_run'> | null | undefined,
  freshness: SyncFreshness | null | undefined,
): string {
  if (!automation) return 'Checking sync…';

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
  if (isAutomationBusy(automationStatus)) return 'busy';
  if (automationStatus === 'Error') return 'error';
  if (freshness?.status === 'fresh') return 'fresh';
  if (freshness && freshness.status !== 'empty') return 'stale';
  return 'unknown';
}
