import { useState, useEffect, useMemo } from 'react';

import { api } from "@/lib/api";

interface QueryResult {
    date: string;
    value: any;
}

export function useMultiOuraQuery(paths: string[], startDate?: string, endDate?: string) {
    const [data, setData] = useState<any[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Stable key derived from paths content — avoids JSON.stringify in dep array
    const pathsKey = useMemo(() => paths.slice().sort().join('|'), [paths]);

    useEffect(() => {
        if (!paths.length) {
            setData([]);
            return;
        }

        let cancelled = false;

        const fetchData = async () => {
            setLoading(true);
            setError(null);
            try {
                const results = await Promise.all(
                    paths.map(async (path) => ({
                        path,
                        data: (await api.getQuery(path, startDate, endDate)) as QueryResult[],
                    }))
                );

                if (cancelled) return;

                // Merge all series by date
                const merged = new Map<string, any>();

                for (const { path, data } of results) {
                    for (const item of data) {
                        const key = item.date;
                        if (!merged.has(key)) {
                            merged.set(key, { date: key, timestamp: key });
                        }
                        merged.get(key)![path] = item.value;
                    }
                }

                const sorted = Array.from(merged.values()).sort(
                    (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
                );

                setData(sorted);
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : 'Unknown error');
                    console.error("Multi Query Error:", err);
                }
            } finally {
                if (!cancelled) setLoading(false);
            }
        };

        fetchData();

        return () => { cancelled = true; };
        // `pathsKey` is a content-derived stable dependency; `paths` itself is often a new array.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [pathsKey, startDate, endDate]);

    return { data, loading, error };
}

