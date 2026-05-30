import { useState, useEffect, useRef, useCallback } from 'react';
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { X, Loader2, Copy, LogOut, RefreshCw } from "lucide-react";
import { cn, parseLocalDate } from "@/lib/utils";
import { Switch } from "@/components/ui/switch";
import { api, type AutomationStatusResponse, type MobileSyncSettings } from '@/lib/api';
import {
    automationStatusLabel,
    isOuraSessionActive,
    needsOuraReauth,
} from '@/lib/automation-status';
import { otpExpiryHint } from '@/lib/otp-timing';
import { formatDistanceToNow } from 'date-fns';
import { isAutomationBusy, syncStatusHeadline, syncStatusSubline } from '@/lib/sync-display';
import { useSyncFreshness } from '@/hooks/useInsights';
import { SyncFreshnessChip } from '@/components/health/InsightsPanels';

interface SettingsPanelProps {
    onClose: () => void;
}

type BackendStatus = AutomationStatusResponse['status'];

interface AutomationState {
    status: BackendStatus;
    email: string;
    lastRun: string | null;
    nextRun: string | null;
    message: string | null;
    loggedIn: boolean;
    otpRequestedAt: string | null;
    otpExpired: boolean | null;
    otpMinutesRemaining: number | null;
}

export function SettingsPanel({ onClose }: SettingsPanelProps) {
    const [automation, setAutomation] = useState<AutomationState | null>(null);
    const [loading, setLoading] = useState(false);
    const syncBusy = loading || isAutomationBusy(automation?.status);
    const { freshness, refresh: refreshFreshness } = useSyncFreshness(syncBusy ? 5_000 : 60_000);
    const [error, setError] = useState<string | null>(null);
    const [email, setEmail] = useState('');
    const [otp, setOtp] = useState('');

    const [dailySyncTime, setDailySyncTime] = useState("09:00");
    const [llmModel, setLlmModel] = useState("llama3.1:latest");
    const [llmHost, setLlmHost] = useState("http://localhost:1234/v1");
    const [llmApiKey, setLlmApiKey] = useState("not-needed");
    const [mobileSync, setMobileSync] = useState<MobileSyncSettings | null>(null);
    const [mobileSyncEnabled, setMobileSyncEnabled] = useState(false);
    const [mobileSyncToken, setMobileSyncToken] = useState("");
    const [mobileSyncHost, setMobileSyncHost] = useState("0.0.0.0");
    const [mobileSyncPort, setMobileSyncPort] = useState("8037");
    const [mobileSyncWindowDays, setMobileSyncWindowDays] = useState("180");

    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const mapAutomationStatus = useCallback((data: AutomationStatusResponse): AutomationState => ({
        status: data.status as BackendStatus,
        email: data.email || '',
        lastRun: data.last_run || null,
        nextRun: data.next_run || null,
        message: data.message || null,
        loggedIn: isOuraSessionActive(data),
        otpRequestedAt: data.otp_requested_at ?? null,
        otpExpired: data.otp_expired ?? null,
        otpMinutesRemaining: data.otp_minutes_remaining ?? null,
    }), []);

    const fetchStatus = useCallback(async () => {
        try {
            const data = await api.checkStatus();
            setAutomation(mapAutomationStatus(data));
            if (data.email) setEmail(data.email);
        } catch (err) {
            console.error("Failed to fetch status", err);
        }
    }, [mapAutomationStatus]);

    // Fetch initial state on mount
    useEffect(() => {
        fetchStatus();
        api.getSettings()
            .then(data => {
                if (data.daily_sync_time) setDailySyncTime(data.daily_sync_time);
                if (data.email) setEmail(data.email);
                if (data.llm_model) setLlmModel(data.llm_model);
                if (data.llm_host) setLlmHost(data.llm_host);
                if (data.llm_api_key) setLlmApiKey(data.llm_api_key);
            })
            .catch(err => console.error("Failed to fetch settings", err));

        api.getMobileSyncSettings()
            .then(data => {
                setMobileSync(data);
                setMobileSyncEnabled(data.enabled);
                setMobileSyncToken(data.token);
                setMobileSyncHost(data.bind_host);
                setMobileSyncPort(String(data.port));
                setMobileSyncWindowDays(String(data.default_window_days));
            })
            .catch(err => console.error("Failed to fetch mobile sync settings", err));

        return () => {
            if (pollRef.current) clearInterval(pollRef.current);
        };
    }, [fetchStatus]);

    const startPolling = useCallback(() => {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = setInterval(async () => {
            try {
                const data = await api.checkStatus();
                setAutomation(prev => {
                    const mapped = mapAutomationStatus(data);
                    return prev ? {
                        ...mapped,
                        lastRun: data.last_run || prev.lastRun,
                        nextRun: data.next_run || prev.nextRun,
                    } : mapped;
                });

                if (data.status === 'completed' || data.status === 'ready_to_download') {
                    if (pollRef.current) clearInterval(pollRef.current);
                    // Auto-download when ready
                    handleAutoDownload();
                } else if (data.status === 'Idle') {
                    refreshFreshness();
                    api.getMobileSyncSettings()
                        .then(ms => setMobileSync(ms))
                        .catch(() => {});
                    if (pollRef.current) clearInterval(pollRef.current);
                    setLoading(false);
                    fetchStatus();
                    api.getMobileSyncSettings().then(setMobileSync).catch(err => console.error("Failed to refresh mobile sync", err));
                } else if (data.status === 'Error') {
                    if (pollRef.current) clearInterval(pollRef.current);
                    setError(data.message || "Sync failed");
                    setLoading(false);
                } else if (needsOuraReauth(data.status, data.message)) {
                    if (pollRef.current) clearInterval(pollRef.current);
                    setLoading(false);
                }
            } catch (err) {
                console.error("Polling error", err);
            }
        }, 5000);
    }, [mapAutomationStatus, refreshFreshness]);

    const handleAutoDownload = async () => {
        setLoading(true);
        setError(null);
        try {
            await api.downloadExport();
            await fetchStatus();
        } catch (err: any) {
            setError(err?.message || 'Download failed');
        } finally {
            setLoading(false);
        }
    };

    const handleStartLogin = async () => {
        if (!email.trim()) return;
        setLoading(true);
        setError(null);
        // Clear any stale error status so the UI resets cleanly
        setAutomation(prev => prev ? { ...prev, status: 'Idle', message: null } : prev);
        try {
            await api.saveSettings({ daily_sync_time: dailySyncTime, email });
            await api.startLogin(email);
            await fetchStatus();
        } catch (err: any) {
            setError(err?.message || 'Login failed');
        } finally {
            setLoading(false);
        }
    };

    const handleSubmitOtp = async () => {
        if (!otp.trim()) return;
        setLoading(true);
        setError(null);
        try {
            const resumeSync = needsOuraReauth(automation?.status, automation?.message);
            const action = resumeSync ? 'run' : 'test';
            await api.submitOtp(otp, action);
            setOtp('');
            await fetchStatus();
            if (resumeSync) {
                startPolling();
            }
        } catch (err: any) {
            setError(err?.message || 'Invalid code');
        } finally {
            setLoading(false);
        }
    };

    const handleResendOtp = async () => {
        setLoading(true);
        setError(null);
        try {
            await api.resendOtp();
            setOtp('');
            await fetchStatus();
        } catch (err: any) {
            setError(err?.message || 'Failed to send a new code');
        } finally {
            setLoading(false);
        }
    };

    const handleSyncNow = async () => {
        setLoading(true);
        setError(null);
        try {
            await api.requestExport();
            setAutomation(prev => prev ? { ...prev, status: 'Processing', message: 'Requesting export from Oura...' } : null);
            startPolling();
        } catch (err: any) {
            // If export request fails, try downloading existing
            const errMsg = err?.message || '';
            if (errMsg.toLowerCase().includes('already') || errMsg.toLowerCase().includes('existing')) {
                await handleAutoDownload();
            } else {
                setError(errMsg || 'Sync failed');
                setLoading(false);
            }
        }
    };

    const handleClearSession = async () => {
        setLoading(true);
        try {
            await api.clearSession();
            setAutomation({
                status: 'Idle',
                email: '',
                lastRun: null,
                nextRun: null,
                message: null,
                loggedIn: false,
                otpRequestedAt: null,
                otpExpired: null,
                otpMinutesRemaining: null,
            });
            setError(null);
        } catch (err: any) {
            setError(err?.message || 'Failed to log out');
        } finally {
            setLoading(false);
        }
    };

    const handleSaveSchedule = async () => {
        setLoading(true);
        setError(null);
        try {
            await api.saveSettings({ daily_sync_time: dailySyncTime, email, llm_model: llmModel, llm_host: llmHost, llm_api_key: llmApiKey });
        } catch (err: any) {
            setError(err?.message || 'Failed to save');
        } finally {
            setLoading(false);
        }
    };

    const applyMobileSyncState = (data: MobileSyncSettings) => {
        setMobileSync(data);
        setMobileSyncEnabled(data.enabled);
        setMobileSyncToken(data.token);
        setMobileSyncHost(data.bind_host);
        setMobileSyncPort(String(data.port));
        setMobileSyncWindowDays(String(data.default_window_days));
    };

    const handleSaveMobileSync = async (regenerateToken = false) => {
        setLoading(true);
        setError(null);
        try {
            const normalizedToken = mobileSyncToken.trim();
            const data = await api.saveMobileSyncSettings({
                enabled: mobileSyncEnabled,
                token: regenerateToken ? undefined : normalizedToken || undefined,
                regenerate_token: regenerateToken,
                bind_host: mobileSyncHost,
                port: Number(mobileSyncPort),
                default_window_days: Number(mobileSyncWindowDays)
            });
            applyMobileSyncState(data);
        } catch (err: any) {
            setError(err?.message || 'Failed to save');
        } finally {
            setLoading(false);
        }
    };

    const handleFileUpload = async (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;
        setLoading(true);
        setError(null);
        try {
            await api.uploadZip(file);
            await fetchStatus();
        } catch (err: any) {
            setError(err?.message || 'Upload failed');
        } finally {
            setLoading(false);
            event.target.value = '';
        }
    };

    const isWaitingForOtp = needsOuraReauth(automation?.status, automation?.message);
    const isExporting = isAutomationBusy(automation?.status);
    const isError = automation?.status === 'Error';
    const isLoggedIn = automation?.loggedIn === true && !isWaitingForOtp && !isError;
    const otpHint = automation
        ? otpExpiryHint({
            otp_expired: automation.otpExpired,
            otp_requested_at: automation.otpRequestedAt,
            otp_minutes_remaining: automation.otpMinutesRemaining,
        })
        : null;
    const isBusy = loading || isExporting;
    const connectionLabel = automation
        ? automationStatusLabel({
            status: automation.status,
            message: automation.message ?? undefined,
            logged_in: automation.loggedIn,
            email: automation.email,
        })
        : 'Loading…';

    return (
        <div className="w-[420px] glass-panel flex flex-col h-full shadow-[0_18px_60px_rgba(0,0,0,0.24)]">
            {/* Header */}
            <div className="glass-nav p-4 flex items-center justify-between">
                <div>
                    <p className="text-[10px] uppercase tracking-widest text-white/30">Configuration</p>
                    <h2 className="font-serif text-xl font-semibold tracking-wide text-white/90 mt-0.5">Settings</h2>
                </div>
                <Button variant="ghost" size="icon" onClick={onClose} className="h-8 w-8 rounded-lg text-white/40 hover:text-white hover:bg-white/[0.06]">
                    <X className="h-4 w-4" />
                </Button>
            </div>

            <div className="flex-1 p-4 space-y-5 overflow-y-auto">
                {/* ─── Connection ─── */}
                <div className="space-y-3">
                    <h3 className="text-[10px] font-medium text-white/30 uppercase tracking-widest">Connection</h3>

                    <div className="glass-card rounded-2xl p-4 space-y-3">
                        {/* Status line */}
                        <div className="flex items-center gap-2">
                            <div className={cn(
                                "h-2.5 w-2.5 rounded-full shrink-0",
                                isWaitingForOtp ? "bg-yellow-500 animate-pulse" :
                                isLoggedIn && !isError ? "bg-green-500" :
                                isExporting ? "bg-yellow-500 animate-pulse" :
                                isError ? "bg-red-500" :
                                "bg-gray-500"
                            )} />
                            <span className="text-sm font-medium">
                                {connectionLabel}
                            </span>
                        </div>

                        {isWaitingForOtp && automation?.message && (
                            <p className="text-xs text-yellow-200/80 leading-relaxed">
                                {automation.message}
                            </p>
                        )}

                        {/* Data freshness (distinct from last ingest attempt) */}
                        {isLoggedIn && (freshness?.latest_day || automation?.lastRun || isExporting) && (
                            <div className="space-y-1 text-xs text-muted-foreground">
                                <p className={cn(
                                    "font-medium",
                                    freshness?.status === 'fresh' ? "text-foreground" : "text-amber-200/90",
                                )}>
                                    {syncStatusHeadline(
                                        {
                                            status: automation?.status ?? 'Idle',
                                            message: automation?.message ?? undefined,
                                            last_run: automation?.lastRun,
                                        },
                                        freshness,
                                    )}
                                </p>
                                {syncStatusSubline(
                                    { status: automation?.status ?? 'Idle', last_run: automation?.lastRun },
                                    freshness,
                                ) && (
                                    <p>{syncStatusSubline(
                                        { status: automation?.status ?? 'Idle', last_run: automation?.lastRun },
                                        freshness,
                                    )}</p>
                                )}
                                {freshness?.expected_latest_day && freshness.status !== 'fresh' && (
                                    <p className="text-[10px] text-white/40">
                                        Expecting data through {freshness.expected_latest_day} (tonight&apos;s sleep not included).
                                    </p>
                                )}
                            </div>
                        )}

                        {/* Reassurance message when logged in */}
                        {isLoggedIn && !isExporting && !isWaitingForOtp && freshness?.status === 'fresh' && (
                            <p className="text-xs text-score-green bg-score-green/10 rounded-md px-3 py-2">
                                You're all set! Data syncs automatically every day{automation?.nextRun ? ` at ${parseLocalDate(automation.nextRun).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : ''}. Click "Sync now" if you want fresh data immediately.
                            </p>
                        )}

                        {/* Error message */}
                        {isError && automation?.message && (
                            <p className="text-xs text-living-coral bg-living-coral/10 rounded-md px-3 py-2">{automation.message}</p>
                        )}

                        {/* Exporting message */}
                        {isExporting && automation?.message && (
                            <p className="text-xs text-muted-foreground">{automation.message}</p>
                        )}

                        {/* Login form — only when not logged in */}
                        {!isLoggedIn && !isWaitingForOtp && (
                            <div className="space-y-2 pt-1">
                                <Input
                                    placeholder="email@example.com"
                                    value={email}
                                    onChange={e => setEmail(e.target.value)}
                                    disabled={loading}
                                />
                                <Button className="w-full" onClick={handleStartLogin} disabled={!email.trim() || loading}>
                                    {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                                    Log in
                                </Button>
                            </div>
                        )}

                        {/* OTP input — only when waiting */}
                        {isWaitingForOtp && (
                            <div className="space-y-2 pt-1">
                                <p className="text-xs text-muted-foreground">
                                    Enter the code sent to <span className="font-medium text-foreground">{automation?.email}</span>
                                </p>
                                {otpHint && (
                                    <p className={cn(
                                        "text-xs rounded-md px-3 py-2 leading-relaxed",
                                        automation?.otpExpired
                                            ? "text-amber-100/90 bg-amber-500/15 border border-amber-500/25"
                                            : "text-muted-foreground bg-white/[0.04]",
                                    )}>
                                        {otpHint}
                                    </p>
                                )}
                                <Button
                                    variant="outline"
                                    className="w-full"
                                    onClick={handleResendOtp}
                                    disabled={loading}
                                >
                                    {loading ? (
                                        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                                    ) : (
                                        <RefreshCw className="mr-2 h-4 w-4" />
                                    )}
                                    Send new code
                                </Button>
                                <div className="flex gap-2">
                                    <Input
                                        placeholder="123456"
                                        value={otp}
                                        onChange={e => setOtp(e.target.value)}
                                        disabled={loading}
                                        className="flex-1"
                                    />
                                    <Button onClick={handleSubmitOtp} disabled={!otp.trim() || loading}>
                                        {loading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                                        Submit
                                    </Button>
                                </div>
                                <button
                                    className="text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"
                                    onClick={handleClearSession}
                                    disabled={loading}
                                >
                                    <LogOut className="h-3 w-3" />
                                    Use a different email
                                </button>
                            </div>
                        )}

                        {/* Log out — only when logged in and idle */}
                        {isLoggedIn && !isExporting && !isWaitingForOtp && (
                            <button
                                className="text-xs text-muted-foreground hover:text-foreground transition-colors flex items-center gap-1"
                                onClick={handleClearSession}
                                disabled={loading}
                            >
                                <LogOut className="h-3 w-3" />
                                Log out
                            </button>
                        )}
                    </div>
                </div>

                {/* ─── Sync Data ─── */}
                <div className="space-y-3">
                    <h3 className="text-[10px] font-medium text-white/40 uppercase tracking-[0.24em]">Sync Data</h3>

                    {freshness && (
                        <div className="glass-card rounded-2xl p-4 space-y-2 text-xs">
                            <div className="flex items-center justify-between">
                                <span className="text-white/60">Status</span>
                                <SyncFreshnessChip freshness={freshness} />
                            </div>
                            <div className="grid grid-cols-2 gap-2 text-[11px]">
                                <div className="space-y-0.5">
                                    <p className="text-white/40 uppercase tracking-wider text-[9px]">Latest day</p>
                                    <p className="text-white/80 tabular-nums">{freshness.latest_day ?? '—'}</p>
                                </div>
                                <div className="space-y-0.5">
                                    <p className="text-white/40 uppercase tracking-wider text-[9px]">Days behind expected</p>
                                    <p className="text-white/80 tabular-nums">{freshness.days_behind ?? '—'}</p>
                                </div>
                                <div className="space-y-0.5">
                                    <p className="text-white/40 uppercase tracking-wider text-[9px]">Expected through</p>
                                    <p className="text-white/80 tabular-nums">{freshness.expected_latest_day ?? '—'}</p>
                                </div>
                                <div className="space-y-0.5">
                                    <p className="text-white/40 uppercase tracking-wider text-[9px]">Last ingest</p>
                                    <p className="text-white/80 tabular-nums">{freshness.last_ingest_at ?? '—'}</p>
                                </div>
                                <div className="space-y-0.5">
                                    <p className="text-white/40 uppercase tracking-wider text-[9px]">Last export request</p>
                                    <p className="text-white/80 tabular-nums">{freshness.last_export_request_at ?? '—'}</p>
                                </div>
                                <div className="space-y-0.5">
                                    <p className="text-white/40 uppercase tracking-wider text-[9px]">Mobile server</p>
                                    <p className="text-white/80">
                                        {freshness.mobile_server_enabled
                                            ? (freshness.mobile_server_status ?? 'enabled')
                                            : 'disabled'}
                                    </p>
                                </div>
                                <div className="space-y-0.5">
                                    <p className="text-white/40 uppercase tracking-wider text-[9px]">Automation</p>
                                    <p className="text-white/80">{freshness.automation_status ?? '—'}</p>
                                </div>
                            </div>
                            {freshness.message && (
                                <p className="text-[11px] text-white/50">{freshness.message}</p>
                            )}
                        </div>
                    )}

                    <div className="space-y-2">
                        <Button
                            className="w-full"
                            onClick={handleSyncNow}
                            disabled={isBusy || isWaitingForOtp}
                        >
                            {isBusy
                                ? <><Loader2 className="mr-2 h-4 w-4 animate-spin" /> Syncing...</>
                                : <><RefreshCw className="mr-2 h-4 w-4" /> Sync now</>
                            }
                        </Button>
                        <p className="text-[10px] text-muted-foreground text-center">
                            Downloads a ready export first, then requests a new one if needed
                        </p>
                    </div>

                    {automation?.nextRun && (
                        <p className="text-xs text-muted-foreground">
                            Next auto-sync: {formatDistanceToNow(parseLocalDate(automation.nextRun), { addSuffix: true })}
                        </p>
                    )}

                    <div className="space-y-2">
                        <Label className="text-xs text-muted-foreground">Or upload a ZIP manually</Label>
                        <div className="flex gap-2">
                            <Input
                                type="file"
                                accept=".zip"
                                onChange={handleFileUpload}
                                disabled={loading}
                                className="cursor-pointer flex-1 text-xs"
                            />
                        </div>
                    </div>
                </div>

                {/* ─── Schedule ─── */}
                <div className="space-y-3">
                    <h3 className="text-[10px] font-medium text-white/40 uppercase tracking-[0.24em]">Schedule</h3>
                    <div className="flex items-center gap-3">
                        <Label className="text-sm shrink-0">Auto-sync daily at</Label>
                        <Input
                            type="time"
                            value={dailySyncTime}
                            onChange={e => setDailySyncTime(e.target.value)}
                            className="w-32"
                        />
                        <Button onClick={handleSaveSchedule} disabled={loading} variant="outline" size="sm">
                            Save
                        </Button>
                    </div>
                </div>

                {/* ─── AI Advisor ─── */}
                <div className="space-y-3">
                    <h3 className="text-[10px] font-medium text-white/40 uppercase tracking-[0.24em]">AI Advisor</h3>
                    <div className="glass-card rounded-2xl p-4 space-y-3">
                        <p className="text-xs text-muted-foreground">
                            The AI Advisor works with any OpenAI-compatible endpoint — <a href="https://lmstudio.ai" target="_blank" rel="noopener noreferrer" className="underline hover:text-foreground">LM Studio</a>, <a href="https://github.com/ggerganov/llama.cpp/blob/master/examples/server/README.md" target="_blank" rel="noopener noreferrer" className="underline hover:text-foreground">llama.cpp server</a>, local proxies, or cloud APIs.
                        </p>
                        <div className="space-y-2">
                            <Label className="text-xs text-muted-foreground">API Base URL</Label>
                            <Input
                                placeholder="http://localhost:1234/v1"
                                value={llmHost}
                                onChange={e => setLlmHost(e.target.value)}
                                disabled={loading}
                            />
                        </div>
                        <div className="space-y-2">
                            <Label className="text-xs text-muted-foreground">Model Name</Label>
                            <Input
                                placeholder="llama3.1"
                                value={llmModel}
                                onChange={e => setLlmModel(e.target.value)}
                                disabled={loading}
                            />
                        </div>
                        <div className="space-y-2">
                            <Label className="text-xs text-muted-foreground">API Key (optional)</Label>
                            <Input
                                placeholder="not-needed"
                                value={llmApiKey}
                                onChange={e => setLlmApiKey(e.target.value)}
                                disabled={loading}
                            />
                        </div>
                        <Button onClick={handleSaveSchedule} disabled={loading} variant="outline" size="sm">
                            Save AI Settings
                        </Button>
                        <div className="text-xs text-muted-foreground bg-secondary/40 rounded-md p-3 space-y-1">
                            <p className="font-medium text-foreground">Quick Start - LM Studio:</p>
                            <ol className="list-decimal list-inside space-y-1">
                                <li>Download LM Studio from <a href="https://lmstudio.ai" target="_blank" rel="noopener noreferrer" className="underline hover:text-foreground">lmstudio.ai</a></li>
                                <li>Load any GGUF model and start the local server</li>
                                <li>Keep the server running, then click &quot;AI Chat&quot;</li>
                            </ol>
                            <p className="mt-2 font-medium text-foreground">Quick Start - llama.cpp:</p>
                            <ol className="list-decimal list-inside space-y-1">
                                <li>Run: <code className="bg-background px-1 py-0.5 rounded text-[10px]">./server -m model.gguf</code></li>
                                <li>Defaults to <code className="bg-background px-1 py-0.5 rounded text-[10px]">http://localhost:8080/v1</code></li>
                            </ol>
                            <p className="mt-2 text-[10px] opacity-70">For local servers, leave API Key as &quot;not-needed&quot;. For OpenAI/Anthropic, paste your real key.</p>
                        </div>
                    </div>
                </div>

                {/* ─── Mobile App ─── */}
                <div className="space-y-3">
                    <h3 className="text-[10px] font-medium text-white/40 uppercase tracking-[0.24em]">Mobile App</h3>

                    <div className="glass-card rounded-2xl p-4 space-y-4">
                        <div className="flex items-center justify-between gap-4">
                            <Label>Enable Mobile API</Label>
                            <Switch
                                checked={mobileSyncEnabled}
                                onCheckedChange={setMobileSyncEnabled}
                            />
                        </div>

                        <div className="grid grid-cols-2 gap-3">
                            <div className="space-y-2">
                                <Label className="text-xs">Bind Host</Label>
                                <Input
                                    value={mobileSyncHost}
                                    onChange={e => setMobileSyncHost(e.target.value)}
                                    placeholder="0.0.0.0"
                                />
                            </div>
                            <div className="space-y-2">
                                <Label className="text-xs">Port</Label>
                                <Input
                                    type="number"
                                    value={mobileSyncPort}
                                    onChange={e => setMobileSyncPort(e.target.value)}
                                    placeholder="8037"
                                />
                            </div>
                        </div>

                        <div className="space-y-2">
                            <Label className="text-xs">Sync Window (days)</Label>
                            <Input
                                type="number"
                                value={mobileSyncWindowDays}
                                onChange={e => setMobileSyncWindowDays(e.target.value)}
                                placeholder="180"
                            />
                        </div>

                        <div className="space-y-2">
                            <div className="flex items-center justify-between gap-2">
                                <Label className="text-xs">Sync Token</Label>
                                <div className="flex gap-1">
                                    <Button
                                        variant="outline"
                                        size="sm"
                                        onClick={() => navigator.clipboard.writeText(mobileSyncToken)}
                                        disabled={!mobileSyncToken}
                                    >
                                        <Copy className="mr-1 h-3 w-3" />
                                        Copy
                                    </Button>
                                </div>
                            </div>
                            <Input
                                value={mobileSyncToken}
                                onChange={e => setMobileSyncToken(e.target.value)}
                                placeholder="Sync token"
                            />
                        </div>

                        <Button onClick={() => handleSaveMobileSync()} disabled={loading} size="sm">
                            {loading && <Loader2 className="mr-2 h-3 w-3 animate-spin" />}
                            Save
                        </Button>

                        {mobileSync?.server_status && (
                            <p className="text-xs text-muted-foreground rounded-md bg-secondary/40 p-2">
                                {mobileSync.server_status}
                            </p>
                        )}
                        <p className="text-xs text-white/35 leading-relaxed">
                            Read-only LAN API for your phone. Oura login and daily export stay on this desktop app only.
                        </p>
                        <p className="text-xs text-muted-foreground font-mono">
                            http://&lt;pc-or-tailscale-ip&gt;:{mobileSyncPort || "8037"}
                        </p>
                    </div>
                </div>

                {/* ─── Layout (collapsed, at bottom) ─── */}
                <div className="space-y-3 pt-4 border-t">
                    <h3 className="text-[10px] font-medium text-white/40 uppercase tracking-[0.24em]">Layout</h3>
                    <div className="grid grid-cols-1 gap-2">
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => {
                                api.getLayout()
                                    .then(data => navigator.clipboard.writeText(JSON.stringify(data, null, 2)))
                                    .catch(err => console.error("Failed to fetch layout", err));
                            }}
                        >
                            <Copy className="mr-2 h-3 w-3" />
                            Copy Layout JSON
                        </Button>
                        <Input
                            type="file"
                            accept=".json"
                            onChange={async (e) => {
                                const file = e.target.files?.[0];
                                if (!file) return;
                                try {
                                    const text = await file.text();
                                    const raw = JSON.parse(text);
                                    let payload = raw.dashboard?.dashboards ? raw.dashboard : raw;
                                    if (!payload.dashboards && !payload.widgets) {
                                        setError("Invalid layout file");
                                        return;
                                    }
                                    await api.saveLayout(payload);
                                    window.location.reload();
                                } catch (err: any) {
                                    setError("Failed to import: " + err.message);
                                }
                                e.target.value = '';
                            }}
                            className="cursor-pointer text-xs"
                        />
                    </div>
                </div>

                {/* Error toast */}
                {error && !isError && (
                    <div className="rounded-lg border border-living-coral/20 bg-living-coral/10 px-4 py-3 text-xs text-living-coral">
                        {error}
                    </div>
                )}
            </div>
        </div>
    );
}
