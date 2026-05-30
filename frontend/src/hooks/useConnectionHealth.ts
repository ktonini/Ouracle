import { useState, useEffect, useCallback, useRef } from 'react';
import { api, type SyncFreshness } from '@/lib/api';

type ConnectionStatus = 'connected' | 'disconnected' | 'checking';

interface SyncInfo {
    status: string;
    lastRun: string | null;
    nextRun: string | null;
    freshness: SyncFreshness | null;
}

export function useConnectionHealth() {
    const [connectionStatus, setConnectionStatus] = useState<ConnectionStatus>('checking');
    const [syncInfo, setSyncInfo] = useState<SyncInfo>({
        status: 'Unknown',
        lastRun: null,
        nextRun: null,
        freshness: null,
    });
    const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

    const checkConnection = useCallback(async () => {
        try {
            const healthy = await api.healthCheck();
            setConnectionStatus(healthy ? 'connected' : 'disconnected');

            if (healthy) {
                try {
                    const [status, freshness] = await Promise.all([
                        api.getSyncStatus(),
                        api.getSyncFreshness(),
                    ]);
                    setSyncInfo({
                        status: status.status || 'Unknown',
                        lastRun: status.last_run || null,
                        nextRun: status.next_run || null,
                        freshness,
                    });
                } catch {
                    // Don't flip connection status for sync status failure
                }
            }
        } catch {
            setConnectionStatus('disconnected');
        }
    }, []);

    useEffect(() => {
        checkConnection();
        intervalRef.current = setInterval(checkConnection, 30000);
        return () => {
            if (intervalRef.current) clearInterval(intervalRef.current);
        };
    }, [checkConnection]);

    const retryNow = useCallback(() => {
        checkConnection();
    }, [checkConnection]);

    return { connectionStatus, syncInfo, retryNow };
}
