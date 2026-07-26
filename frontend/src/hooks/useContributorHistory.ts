import { useEffect, useState } from 'react';
import { api } from '@/lib/api';

export type HistoryMap = Map<string, (number | null)[]>;

const WINDOW_DAYS = 7;

function isoDay(d: Date): string {
  return d.toISOString().split('T')[0];
}

/**
 * Fetches the last `WINDOW_DAYS` days of history for each `source_path`,
 * aligned to a fixed date axis ending at `day` (oldest → newest). Returns a
 * Map of source_path → array of values where missing days are `null`.
 *
 * Source paths come straight from `ContributorSummary.source_path`
 * (e.g. `sleep.contributors.deep_sleep`) and are passed to `/api/query`.
 */
export function buildContributorHistoryAxis(day: string): string[] {
  const endDate = new Date(day);
  const startDate = new Date(endDate);
  startDate.setDate(startDate.getDate() - (WINDOW_DAYS - 1));
  const axis: string[] = [];
  for (let i = 0; i < WINDOW_DAYS; i++) {
    const d = new Date(startDate);
    d.setDate(d.getDate() + i);
    axis.push(isoDay(d));
  }
  return axis;
}

export function useContributorHistory(
  day: string | null,
  paths: string[],
): { history: HistoryMap; axis: string[] } {
  const [history, setHistory] = useState<HistoryMap>(new Map());
  const [axis, setAxis] = useState<string[]>([]);
  const key = paths.join('|');

  useEffect(() => {
    if (!day || paths.length === 0) {
      setHistory(new Map());
      setAxis([]);
      return;
    }
    let cancelled = false;

    const endDate = new Date(day);
    const startDate = new Date(endDate);
    startDate.setDate(startDate.getDate() - (WINDOW_DAYS - 1));
    const start = isoDay(startDate);
    const end = isoDay(endDate);

    const dateAxis = buildContributorHistoryAxis(day);
    setAxis(dateAxis);

    Promise.all(
      paths.map(async (path) => {
        try {
          const rows = (await api.getQuery(path, start, end)) as Array<{
            day?: string;
            date?: string;
            value?: number | null;
            score?: number | null;
          }>;
          const byDate = new Map<string, number>();
          for (const row of rows ?? []) {
            const d = row.day ?? row.date;
            const v = row.value ?? row.score;
            if (d != null && typeof v === 'number') byDate.set(d, v);
          }
          const series = dateAxis.map((d) => (byDate.has(d) ? (byDate.get(d) as number) : null));
          return [path, series] as const;
        } catch {
          return [path, dateAxis.map(() => null)] as const;
        }
      }),
    )
      .then((entries) => {
        if (cancelled) return;
        setHistory(new Map(entries));
      })
      .catch(() => {
        if (!cancelled) setHistory(new Map());
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [day, key]);

  return { history, axis };
}
