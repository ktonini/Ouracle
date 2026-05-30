// In dev, use empty string so requests go through Vite's proxy (vite.config.ts).
// In production, the Electron window loads from http://127.0.0.1:8000/ (same origin).
const BASE_URL = import.meta.env.DEV ? '' : '';

export interface AutomationStatusResponse {
    status: string;
    message?: string;
    logged_in?: boolean;
    email?: string;
    last_run?: string | null;
    next_run?: string | null;
    otp_requested_at?: string | null;
    otp_expired?: boolean | null;
    otp_minutes_remaining?: number | null;
}

export interface ChatMessage {
    role: 'user' | 'assistant';
    content: string;
    thoughts?: any[];
    created_at?: string;
}

export interface ChatThread {
    id: string;
    title: string;
    created_at: string;
    updated_at: string;
}

export interface ChatThreadWithMessages extends ChatThread {
    messages: ChatMessage[];
}

export interface ContributorSummary {
    domain: string;
    key: string;
    label: string;
    status: 'optimal' | 'good' | 'fair' | 'pay_attention' | 'missing';
    value: number | null;
    unit: string;
    explanation: string;
    source_path: string;
}

export interface ContributorBundle {
    day: string;
    sleep: ContributorSummary[];
    readiness: ContributorSummary[];
    activity: ContributorSummary[];
}

export interface BaselineDelta {
    metric: string;
    label: string;
    unit: string;
    current: number | null;
    baseline_7d: number | null;
    baseline_14d: number | null;
    baseline_30d: number | null;
    delta_7d: number | null;
    delta_14d: number | null;
    delta_30d: number | null;
    direction: 'up' | 'down' | 'flat' | null;
    sample_count_7d: number;
    sample_count_14d: number;
    sample_count_30d: number;
    preferred: 'higher' | 'lower' | null;
}

export interface BaselineBundle {
    day: string;
    deltas: BaselineDelta[];
}

export interface ActionEvidence {
    metric: string;
    value: any;
    day: string | null;
    source_path: string;
}

export interface ActionCard {
    id: string;
    day: string;
    severity: 'critical' | 'warning' | 'info';
    category: 'sync' | 'recovery' | 'sleep' | 'activity' | 'data' | 'device';
    title: string;
    reason: string;
    recommendation: string;
    evidence: ActionEvidence[];
    dismissible: boolean;
}

export interface DailyGuidance {
    day: string;
    headline: string;
    body: string[];
    citations: Array<Record<string, any>>;
}

export interface SyncFreshness {
    latest_day: string | null;
    expected_latest_day: string | null;
    last_ingest_at: string | null;
    last_export_request_at: string | null;
    status: 'fresh' | 'stale' | 'very_stale' | 'empty' | 'syncing' | 'blocked';
    message: string | null;
    mobile_server_enabled: boolean;
    mobile_server_status: string | null;
    automation_status: string | null;
    next_run: string | null;
    days_behind: number | null;
}

// --- Phase 2: Analysis ---
export interface MetricSpec {
    path: string;
    label: string;
    unit: string;
    domain: string;
    preferred: 'higher' | 'lower' | null;
    description?: string;
}

export interface MetricSeriesPoint { day: string; value: number; }

export interface MetricSeries {
    metric_path: string;
    label: string;
    unit: string;
    date_range: [string, string];
    sample_count: number;
    missing_count: number;
    points: MetricSeriesPoint[];
}

export interface CorrelationResult {
    x_metric: string;
    y_metric: string;
    lag_days: number;
    method: string;
    coefficient: number | null;
    sample_count: number;
    paired_dates: Array<[string, string]>;
    warning: string | null;
    interpretation: string;
}

export interface AnomalyResult {
    metric_path: string;
    label: string;
    unit: string;
    day: string;
    value: number;
    baseline_median: number;
    baseline_mad: number;
    score: number;
    direction: 'above' | 'below';
    severity: 'warning' | 'critical';
    baseline_window: number;
    method: string;
    note: string;
}

export interface SavedInvestigation {
    id: string;
    name: string;
    kind: string;
    created_at: string;
    updated_at: string;
    payload: Record<string, any> | null;
}

export interface MobileSyncSettings {
    enabled: boolean;
    token: string;
    default_window_days: number;
    bind_host: string;
    port: number;
    latest_day?: string | null;
    has_data: boolean;
    run_command: string;
    server_running: boolean;
    server_status: string;
}

export const api = {
    // --- Settings & Automation ---
    getSettings: async (): Promise<{ daily_sync_time: string; email: string; llm_model: string; llm_host: string; llm_api_key: string }> => {
        const res = await fetch(`${BASE_URL}/api/settings`);
        if (!res.ok) throw new Error('Failed to fetch settings');
        return res.json();
    },

    saveSettings: async (settings: { daily_sync_time: string; email?: string; llm_model?: string; llm_host?: string; llm_api_key?: string }) => {
        const res = await fetch(`${BASE_URL}/api/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        if (!res.ok) throw new Error('Failed to save settings');
        return res.json();
    },

    getMobileSyncSettings: async (): Promise<MobileSyncSettings> => {
        const res = await fetch(`${BASE_URL}/api/mobile/settings`);
        if (!res.ok) throw new Error('Failed to fetch mobile sync settings');
        return res.json();
    },

    saveMobileSyncSettings: async (settings: {
        enabled?: boolean;
        token?: string;
        regenerate_token?: boolean;
        default_window_days?: number;
        bind_host?: string;
        port?: number;
    }): Promise<MobileSyncSettings> => {
        const res = await fetch(`${BASE_URL}/api/mobile/settings`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(settings)
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Failed to save mobile sync settings');
        return data;
    },

    clearSession: async () => {
        const res = await fetch(`${BASE_URL}/api/automation/clear-session`, { method: 'POST' });
        if (!res.ok) throw new Error('Failed to clear session');
        return res.json();
    },

    startLogin: async (email: string) => {
        const res = await fetch(`${BASE_URL}/api/automation/start-login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Login failed');
        return data;
    },

    submitOtp: async (otp: string, action: 'test' | 'run' | 'download' = 'test') => {
        const res = await fetch(`${BASE_URL}/api/automation/submit-otp`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ otp, action })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'OTP failed');
        return data;
    },

    resendOtp: async () => {
        const res = await fetch(`${BASE_URL}/api/automation/resend-otp`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || data.message || 'Failed to resend code');
        return data;
    },

    requestExport: async () => {
        const res = await fetch(`${BASE_URL}/api/automation/request-export`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Export request failed');
        return data;
    },

    checkStatus: async (): Promise<AutomationStatusResponse> => {
        const res = await fetch(`${BASE_URL}/api/automation/check-status`, { method: 'POST' });
        if (!res.ok) throw new Error('Failed to check status');
        return res.json();
    },

    downloadExport: async () => {
        const res = await fetch(`${BASE_URL}/api/automation/download`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Download failed');
        return data;
    },

    uploadZip: async (file: File) => {
        const formData = new FormData();
        formData.append('file', file);
        const res = await fetch(`${BASE_URL}/api/ingest/zip`, {
            method: 'POST',
            body: formData,
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || 'Upload failed');
        return data;
    },

    // --- Dashboard Data ---
    getDailyData: async (date: string) => {
        const res = await fetch(`${BASE_URL}/api/days/${date}`);
        if (!res.ok) throw new Error('Failed to fetch daily data');
        return res.json();
    },

    getQuery: async (path: string, startDate?: string, endDate?: string) => {
        const params = new URLSearchParams({ path });
        if (startDate) params.append('start_date', startDate);
        if (endDate) params.append('end_date', endDate);

        const res = await fetch(`${BASE_URL}/api/query?${params.toString()}`);
        if (!res.ok) throw new Error('Failed to fetch query data');
        return res.json();
    },

    getSchema: async () => {
        const res = await fetch(`${BASE_URL}/api/schema`);
        if (!res.ok) throw new Error('Failed to fetch schema');
        return res.json();
    },

    getTrends: async (metric: string, startDate: string, endDate: string) => {
        return api.getQuery(metric, startDate, endDate);
    },

    // --- Layout ---
    getLayout: async () => {
        const res = await fetch(`${BASE_URL}/api/dashboard`);
        if (!res.ok) throw new Error('Failed to fetch layout');
        return res.json();
    },

    saveLayout: async (layout: any) => {
        const res = await fetch(`${BASE_URL}/api/dashboard`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(layout)
        });
        if (!res.ok) throw new Error('Failed to save layout');
        return res.json();
    },

    // --- Chat Threads ---
    getThreads: async (): Promise<ChatThread[]> => {
        const res = await fetch(`${BASE_URL}/api/chat/threads`);
        if (!res.ok) throw new Error('Failed to fetch chat threads');
        return res.json();
    },

    getThread: async (id: string): Promise<ChatThreadWithMessages> => {
        const res = await fetch(`${BASE_URL}/api/chat/threads/${id}`);
        if (!res.ok) throw new Error('Failed to fetch chat thread');
        return res.json();
    },

    createThread: async (title?: string): Promise<ChatThread> => {
        const res = await fetch(`${BASE_URL}/api/chat/threads`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ title })
        });
        if (!res.ok) throw new Error('Failed to create chat thread');
        return res.json();
    },

    deleteThread: async (id: string): Promise<void> => {
        const res = await fetch(`${BASE_URL}/api/chat/threads/${id}`, {
            method: 'DELETE'
        });
        if (!res.ok) throw new Error('Failed to delete chat thread');
    },

    appendMessageToThread: async (threadId: string, role: string, content: string, thoughts?: any[]): Promise<void> => {
        const res = await fetch(`${BASE_URL}/api/chat/threads/${threadId}/messages`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ role, content, thoughts })
        });
        if (!res.ok) throw new Error('Failed to append message to thread');
    },

    // --- Chat ---
    sendChatMessageStream: async (
        message: string,
        threadId: string | null,
        onChunk: (chunk: any) => void,
        signal?: AbortSignal
    ): Promise<void> => {
        const res = await fetch(`${BASE_URL}/api/advisor/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message, thread_id: threadId }),
            signal
        });

        if (!res.ok) {
            const errText = await res.text().catch(() => 'Chat request failed');
            throw new Error(errText || 'Chat request failed');
        }

        if (!res.body) {
            throw new Error('ReadableStream not supported by browser or response has empty body');
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder('utf-8');
        let buffer = '';

        try {
            while (true) {
                const { value, done } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');

                // Save last incomplete line back to buffer
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (line.trim()) {
                        try {
                            const chunk = JSON.parse(line);
                            onChunk(chunk);
                        } catch (e) {
                            console.error('Failed to parse line-delimited JSON stream chunk:', e, line);
                        }
                    }
                }
            }

            // Parse final buffer if any
            if (buffer.trim()) {
                try {
                    const chunk = JSON.parse(buffer);
                    onChunk(chunk);
                } catch (e) {
                    console.error('Failed to parse final chunk:', e, buffer);
                }
            }
        } finally {
            reader.releaseLock();
        }
    },

    // --- Connection Health ---
    healthCheck: async (): Promise<boolean> => {
        try {
            const res = await fetch(`${BASE_URL}/api/settings`, { method: 'GET' });
            return res.ok;
        } catch {
            return false;
        }
    },

    getSyncStatus: async (): Promise<{
        status: string;
        last_run: string | null;
        next_run: string | null;
        [key: string]: any;
    }> => {
        const res = await fetch(`${BASE_URL}/api/automation/check-status`, { method: 'POST' });
        if (!res.ok) throw new Error('Failed to fetch sync status');
        return res.json();
    },

    // --- Insights (Phase 1) ---
    getContributors: async (day: string): Promise<ContributorBundle> => {
        const res = await fetch(`${BASE_URL}/api/insights/contributors/${day}`);
        if (!res.ok) throw new Error('Failed to fetch contributors');
        return res.json();
    },

    getBaselines: async (day: string): Promise<BaselineBundle> => {
        const res = await fetch(`${BASE_URL}/api/insights/baselines/${day}`);
        if (!res.ok) throw new Error('Failed to fetch baselines');
        return res.json();
    },

    getActionCards: async (day: string): Promise<ActionCard[]> => {
        const res = await fetch(`${BASE_URL}/api/insights/action-cards/${day}`);
        if (!res.ok) throw new Error('Failed to fetch action cards');
        return res.json();
    },

    getGuidance: async (day: string): Promise<DailyGuidance> => {
        const res = await fetch(`${BASE_URL}/api/insights/guidance/${day}`);
        if (!res.ok) throw new Error('Failed to fetch guidance');
        return res.json();
    },

    getSyncFreshness: async (): Promise<SyncFreshness> => {
        const res = await fetch(`${BASE_URL}/api/insights/sync-freshness`);
        if (!res.ok) throw new Error('Failed to fetch sync freshness');
        return res.json();
    },

    // --- Analysis (Phase 2) ---
    getAnalysisCatalog: async (): Promise<MetricSpec[]> => {
        const res = await fetch(`${BASE_URL}/api/analysis/catalog`);
        if (!res.ok) throw new Error('Failed to fetch metric catalog');
        return res.json();
    },

    getAnalysisSeries: async (metric: string, start: string, end: string): Promise<MetricSeries> => {
        const q = new URLSearchParams({ metric, start_date: start, end_date: end });
        const res = await fetch(`${BASE_URL}/api/analysis/series?${q.toString()}`);
        if (!res.ok) throw new Error('Failed to fetch series');
        return res.json();
    },

    getCorrelation: async (
        x: string, y: string, lagDays: number, start: string, end: string, method: 'pearson' | 'spearman' = 'pearson'
    ): Promise<CorrelationResult> => {
        const q = new URLSearchParams({
            x_metric: x, y_metric: y, lag_days: String(lagDays),
            method, start_date: start, end_date: end,
        });
        const res = await fetch(`${BASE_URL}/api/analysis/correlate?${q.toString()}`);
        if (!res.ok) throw new Error('Failed to compute correlation');
        return res.json();
    },

    getAnomalies: async (day: string, windowDays = 7, baselineWindow = 28): Promise<AnomalyResult[]> => {
        const q = new URLSearchParams({
            window_days: String(windowDays),
            baseline_window: String(baselineWindow),
        });
        const res = await fetch(`${BASE_URL}/api/analysis/anomalies/${day}?${q.toString()}`);
        if (!res.ok) throw new Error('Failed to fetch anomalies');
        return res.json();
    },

    // --- Investigations (Phase 2) ---
    listInvestigations: async (): Promise<SavedInvestigation[]> => {
        const res = await fetch(`${BASE_URL}/api/investigations`);
        if (!res.ok) throw new Error('Failed to list investigations');
        return res.json();
    },

    createInvestigation: async (body: { name: string; kind: string; payload: Record<string, any> }): Promise<SavedInvestigation> => {
        const res = await fetch(`${BASE_URL}/api/investigations`, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
        });
        if (!res.ok) throw new Error('Failed to save investigation');
        return res.json();
    },

    deleteInvestigation: async (id: string): Promise<void> => {
        const res = await fetch(`${BASE_URL}/api/investigations/${id}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Failed to delete investigation');
    },
};
