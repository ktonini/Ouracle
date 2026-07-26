import type { AutomationStatusResponse } from '@/lib/api';

/** Backend status values that mean Oura needs a fresh sign-in / OTP. */
export function needsOuraReauth(
    status: AutomationStatusResponse['status'] | string | undefined,
    message?: string | null,
): boolean {
    if (status === 'otp_needed' || status === 'Waiting') return true;
    if (message && /otp/i.test(message)) return true;
    return false;
}

/** Whether the desktop automation session is usable for Oura export right now. */
export function isOuraSessionActive(
    data: Pick<AutomationStatusResponse, 'status' | 'message' | 'logged_in'>,
): boolean {
    if (needsOuraReauth(data.status, data.message)) return false;
    return data.logged_in === true;
}

export function automationStatusLabel(
    data: Pick<AutomationStatusResponse, 'status' | 'message' | 'logged_in' | 'email'>,
): string {
    if (needsOuraReauth(data.status, data.message)) {
        return 'Oura sign-in required';
    }
    if (data.status === 'Waiting for export') {
        return 'Waiting for Oura export';
    }
    if (data.status === 'Processing' || data.status === 'Ingesting') {
        return 'Syncing…';
    }
    if (data.status === 'Error') {
        return 'Something went wrong';
    }
    if (isOuraSessionActive(data) && data.email) {
        return `Logged in as ${data.email}`;
    }
    if (isOuraSessionActive(data)) {
        return 'Logged in';
    }
    return 'Not logged in';
}
