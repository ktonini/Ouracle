import { useEffect, useMemo, useState } from 'react';
import {
  api,
  type AnomalyResult,
  type CorrelationResult,
  type InterestingCorrelation,
  type MetricSpec,
  type SavedInvestigation,
} from '@/lib/api';
import { CorrelationPanel } from '@/components/analysis/CorrelationPanel';
import { InterestingCorrelationsPanel } from '@/components/analysis/InterestingCorrelationsPanel';
import { AnomalyList } from '@/components/analysis/AnomalyList';
import { SavedInvestigationsPanel } from '@/components/analysis/SavedInvestigationsPanel';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

type Tab = 'discover' | 'correlate' | 'anomalies' | 'saved';

const DEFAULT_X = 'sleep_session.bedtime_start_minutes';
const DEFAULT_Y = 'readiness.score';
const RANGES = [
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
  { label: '180d', days: 180 },
];

export function ExplorerView() {
  const [tab, setTab] = useState<Tab>('discover');
  const [catalog, setCatalog] = useState<MetricSpec[]>([]);
  const [xMetric, setXMetric] = useState(DEFAULT_X);
  const [yMetric, setYMetric] = useState(DEFAULT_Y);
  const [lag, setLag] = useState(1);
  const [range, setRange] = useState(RANGES[1]);
  const [result, setResult] = useState<CorrelationResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [interesting, setInteresting] = useState<InterestingCorrelation[]>([]);
  const [discoverLoading, setDiscoverLoading] = useState(false);
  const [discoverError, setDiscoverError] = useState<string | null>(null);

  const [anomalies, setAnomalies] = useState<AnomalyResult[]>([]);
  const [anomalyLoading, setAnomalyLoading] = useState(false);

  const [investigations, setInvestigations] = useState<SavedInvestigation[]>([]);
  const [invLoading, setInvLoading] = useState(false);

  const endDate = useMemo(() => new Date().toISOString().split('T')[0], []);
  const startDate = useMemo(() => {
    const d = new Date();
    d.setDate(d.getDate() - range.days);
    return d.toISOString().split('T')[0];
  }, [range]);

  useEffect(() => { api.getAnalysisCatalog().then(setCatalog).catch(() => setCatalog([])); }, []);

  useEffect(() => {
    if (tab !== 'discover') return;
    setDiscoverLoading(true);
    setDiscoverError(null);
    api.getInterestingCorrelations(startDate, endDate)
      .then(setInteresting)
      .catch((e) => setDiscoverError(e.message))
      .finally(() => setDiscoverLoading(false));
  }, [tab, startDate, endDate]);

  useEffect(() => {
    if (tab !== 'correlate') return;
    setLoading(true); setError(null);
    api.getCorrelation(xMetric, yMetric, lag, startDate, endDate)
      .then(setResult)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [tab, xMetric, yMetric, lag, startDate, endDate]);

  useEffect(() => {
    if (tab !== 'anomalies') return;
    setAnomalyLoading(true);
    api.getAnomalies(endDate, 14)
      .then(setAnomalies)
      .catch(() => setAnomalies([]))
      .finally(() => setAnomalyLoading(false));
  }, [tab, endDate]);

  const refreshInvestigations = () => {
    setInvLoading(true);
    api.listInvestigations()
      .then(setInvestigations).catch(() => setInvestigations([]))
      .finally(() => setInvLoading(false));
  };
  useEffect(() => { if (tab === 'saved') refreshInvestigations(); }, [tab]);

  const handleInspect = (item: InterestingCorrelation) => {
    setXMetric(item.x_metric);
    setYMetric(item.y_metric);
    setLag(item.lag_days);
    setTab('correlate');
  };

  const handleSaveCurrent = async () => {
    if (!result) return;
    const xLabel = catalog.find(c => c.path === xMetric)?.label ?? xMetric;
    const yLabel = catalog.find(c => c.path === yMetric)?.label ?? yMetric;
    await api.createInvestigation({
      name: `${xLabel} → ${yLabel} (lag ${lag}d)`,
      kind: 'correlation',
      payload: { x_metric: xMetric, y_metric: yMetric, lag_days: lag, method: 'pearson',
        start_date: startDate, end_date: endDate, coefficient: result.coefficient,
        sample_count: result.sample_count, interpretation: result.interpretation },
    });
    refreshInvestigations();
  };

  const tabLabels: { id: Tab; label: string }[] = [
    { id: 'discover', label: 'Discover' },
    { id: 'correlate', label: 'Correlate' },
    { id: 'anomalies', label: 'Anomalies' },
    { id: 'saved', label: 'Saved' },
  ];

  return (
    <div className="p-6 md:p-8 space-y-6 max-w-5xl mx-auto animate-fadeIn">
      <div>
        <h1 className="font-serif text-3xl text-white tracking-wide">Explorer</h1>
        <p className="text-sm text-white/40 mt-1">Discover correlations, drill into pairs, surface anomalies, save investigations.</p>
      </div>

      <div className="flex gap-1 flex-wrap">
        {tabLabels.map(({ id, label }) => (
          <Button key={id} variant="ghost" size="sm" onClick={() => setTab(id)}
            className={cn('rounded-lg text-xs h-7',
              tab === id ? 'glass-tab text-white' : 'text-white/40 hover:text-white/70')}>
            {label}
          </Button>
        ))}
      </div>

      {tab === 'discover' && (
        <InterestingCorrelationsPanel
          results={interesting}
          loading={discoverLoading}
          error={discoverError}
          range={range}
          ranges={RANGES}
          onRangeChange={setRange}
          onInspect={handleInspect}
        />
      )}

      {tab === 'correlate' && (
        <CorrelationPanel
          catalog={catalog}
          xMetric={xMetric} yMetric={yMetric} lag={lag}
          range={range} ranges={RANGES}
          onXChange={setXMetric} onYChange={setYMetric}
          onLagChange={setLag} onRangeChange={setRange}
          result={result} loading={loading} error={error}
          onSave={handleSaveCurrent}
        />
      )}

      {tab === 'anomalies' && (
        <AnomalyList anomalies={anomalies} loading={anomalyLoading} day={endDate} />
      )}

      {tab === 'saved' && (
        <SavedInvestigationsPanel
          investigations={investigations} loading={invLoading}
          onDelete={async (id) => { await api.deleteInvestigation(id); refreshInvestigations(); }}
        />
      )}
    </div>
  );
}
