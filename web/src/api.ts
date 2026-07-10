export type Health = { status: string; dataSource: string; cachePath: string; versions: Record<string, string> }
export type Bar = {
  date: string; open: number; high: number; low: number; close: number;
  open_qfq: number; high_qfq: number; low_qfq: number; close_qfq: number;
  volume: number; ma5?: number | null; ma10?: number | null; ma20?: number | null; ma60?: number | null;
}
export type Audit = {
  eligibility: { eligible: boolean; status: string; reasons: string[] }
  entry: { status: string; entry_date?: string; entry_price?: number; entry_delay?: number }
  labels: Record<string, { status: string; theoretical_return?: number; executable_return?: number; excess_executable_return?: number }>
  path?: { success: boolean; reason: string }
  drawdown?: { max_drawdown: number; hit_risk: boolean }
  maturityDate?: string
  dataSnapshotVersion?: string
  factorVersion?: string
}
export type FeatureValue = number | boolean | string | null
export type FeatureAudit = {
  exchange: string; code: string; date: string; availableHistory: number;
  groups: Record<'trend' | 'position' | 'momentum' | 'volumePrice' | 'tradingBehavior', Record<string, FeatureValue>>;
  reasons: string[]; priceBasis: string;
  versions: Record<string, string | null>;
}
export type ScoreComponent = { score: number; weight: number; available: boolean; reasons: string[] }
export type ScoreAudit = {
  exchange: string; code: string; date: string; availableHistory: number;
  featureDefinitionVersion: string; priceBasis: string;
  score: {
    version: string; score: number; grade: string; usable: boolean;
    components: Record<'trend' | 'position' | 'momentum' | 'volumePrice' | 'tradingBehavior', ScoreComponent>;
    reasons: string[];
  };
  versions: Record<string, string | null>;
}
export type HistoryBackfillTask = {
  status: string; done: number; total: number; completed: number;
  listingHistoryShort: number; errors: unknown[]; currentSecurity?: string | null;
  speed: number; etaSeconds?: number | null;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...init })
  if (!response.ok) {
    let message = `请求失败：${response.status}`
    try {
      const body = await response.json() as { detail?: string | { message?: string } }
      if (typeof body.detail === 'string') message = body.detail
      else if (body.detail?.message) message = body.detail.message
    } catch { /* keep the status-based fallback */ }
    const allowed = response.headers?.get('allow')
    if (allowed) message += ` · Allow ${allowed}`
    throw new Error(message)
  }
  return response.json() as Promise<T>
}

export const api = {
  health: () => request<Health>('/api/system/health'),
  bars: (exchange: string, code: string) => request<Bar[]>(`/api/securities/${exchange}/${code}/bars`),
  audit: (exchange: string, code: string, signalDate: string) => request<Audit>('/api/p1/audit', {
    method: 'POST', body: JSON.stringify({ exchange, code, signal_date: signalDate }),
  }),
  importData: (scope: 'representative' | 'all') => request<{ taskId: string; total: number; requested: number; skipped: number }>('/api/datasets/import', {
    method: 'POST', body: JSON.stringify({ scope }),
  }),
  importTask: (taskId: string) => request<{ status: string; done: number; total: number; errors: unknown[]; currentSecurity?: string; stage?: string; speed?: number; etaSeconds?: number; directAvailable?: boolean }>(`/api/datasets/tasks/${taskId}`),
  startHistoryBackfill: () => request<{ taskId: string; total: number; threshold: number }>('/api/datasets/import', {
    method: 'POST', body: JSON.stringify({ scope: 'history_backfill' }),
  }),
  historyBackfillTask: (taskId: string) => request<HistoryBackfillTask>(`/api/datasets/backfill-history/${taskId}`),
  quality: () => request<{ totalCached: number }>('/api/datasets/quality'),
  buildLabels: (scope: 'representative' | 'all') => request<{ taskId: string; total: number }>('/api/labels/build', {
    method: 'POST', body: JSON.stringify({ scope }),
  }),
  labelTask: (taskId: string) => request<{ status: string; done: number; total: number; rows: number; errors: unknown[] }>(`/api/labels/tasks/${taskId}`),
  buildFeatures: (scope: 'representative' | 'all') => request<{ taskId: string; total: number }>('/api/features/build', {
    method: 'POST', body: JSON.stringify({ scope }),
  }),
  featureTask: (taskId: string) => request<{ status: string; done: number; total: number; rows: number; errors: unknown[]; currentSecurity?: string }>(`/api/features/tasks/${taskId}`),
  buildScores: (scope: 'representative' | 'all') => request<{ taskId: string; total: number }>('/api/scores/build', {
    method: 'POST', body: JSON.stringify({ scope }),
  }),
  scoreTask: (taskId: string) => request<{ status: string; done: number; total: number; rows: number; errors: unknown[]; currentSecurity?: string }>(`/api/scores/tasks/${taskId}`),
  featureAudit: (exchange: string, code: string, signalDate: string) => request<FeatureAudit>('/api/p2/audit', {
    method: 'POST', body: JSON.stringify({ exchange, code, signal_date: signalDate }),
  }),
  scoreAudit: (exchange: string, code: string, signalDate: string) => request<ScoreAudit>('/api/p3/audit', {
    method: 'POST', body: JSON.stringify({ exchange, code, signal_date: signalDate }),
  }),
}
