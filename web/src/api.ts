export type Health = {
  status: string;
  dataSource: string;
  cachePath: string;
  versions: Record<string, string>;
  recoverableTasks?: number;
};
export type LabelStatus = {
  currentVersion: string;
  snapshotSetHash?: string;
  trackedSecurities?: number;
  files: number;
  currentSnapshotFiles?: number;
  staleSnapshotFiles?: number;
  missingCurrentFiles?: number;
  supersededFiles: number;
  orphanedFiles: number;
  rows: number;
  versionCounts: Record<string, number>;
  compatibleFiles: number;
  staleFiles: number;
  unreadableFiles: number;
  unreadableExamples: string[];
  incompatibleFiles: number;
  legacyFiles: number;
  delayedExitReady: boolean;
};
export type Bar = {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  open_qfq: number;
  high_qfq: number;
  low_qfq: number;
  close_qfq: number;
  volume: number;
  ma5?: number | null;
  ma10?: number | null;
  ma20?: number | null;
  ma60?: number | null;
};
export type Audit = {
  eligibility: { eligible: boolean; status: string; reasons: string[] };
  entry: {
    status: string;
    entry_date?: string;
    entry_price?: number;
    entry_delay?: number;
    entry_reason?: string;
  };
  labels: Record<
    string,
    {
      status: string;
      theoretical_return?: number;
      executable_return?: number;
      delayed_executable_return?: number | null;
      excess_executable_return?: number;
      planned_exit_date?: string | null;
    }
  >;
  exits: Record<
    string,
    {
      executable: boolean;
      status: string;
      exit_date?: string | null;
      exit_price?: number | null;
      exit_delay?: number | null;
      reason?: string;
    }
  >;
  securityStatus?: { is_st: boolean; is_approx: boolean; reason: string };
  path?: {
    success: boolean;
    reason: string;
    hit_date?: string | null;
    fail_date?: string | null;
  };
  drawdown?: {
    max_drawdown: number;
    hit_risk: boolean;
    hit_date?: string | null;
    peak_date?: string | null;
  };
  maturityDate?: string;
  dataSnapshotVersion?: string;
  factorVersion?: string;
};
export type FeatureValue = number | boolean | string | null;
export type FeatureAudit = {
  exchange: string;
  code: string;
  date: string;
  availableHistory: number;
  groups: Record<
    "trend" | "position" | "momentum" | "volumePrice" | "tradingBehavior",
    Record<string, FeatureValue>
  >;
  reasons: string[];
  priceBasis: string;
  versions: Record<string, string | null>;
};
export type Security = { exchange: "sh" | "sz"; code: string; name: string };
export type ScoreComponent = {
  score: number;
  weight: number;
  available: boolean;
  reasons: string[];
};
export type ScoreAudit = {
  exchange: string;
  code: string;
  date: string;
  availableHistory: number;
  featureDefinitionVersion: string;
  priceBasis: string;
  score: {
    version: string;
    score: number;
    grade: string;
    usable: boolean;
    components: Record<
      "trend" | "position" | "momentum" | "volumePrice" | "tradingBehavior",
      ScoreComponent
    >;
    reasons: string[];
  };
  versions: Record<string, string | null>;
};
export type ConfidenceInterval = {
  lower: number;
  upper: number;
  confidence: number;
  samples: number;
};
export type ValidationBucket = {
  bucket: number;
  count: number;
  minFactor: number;
  maxFactor: number;
  avgFactor: number;
  avgLabel: number;
  medianLabel: number;
  winRate: number;
  pathSuccessRate?: number | null;
  avgMaxDrawdown?: number | null;
  avgLabelInterval?: ConfidenceInterval | null;
  winRateInterval?: ConfidenceInterval | null;
};
export type SingleFactorValidation = {
  version: string;
  factorColumn: string;
  labelColumn: string;
  bucketCount: number;
  sampleCount: number;
  independentPeriodCount: number;
  independenceGapDays: number;
  rankCorrelation?: number | null;
  rankCorrelationInterval?: ConfidenceInterval | null;
  buckets: ValidationBucket[];
  missingColumns: string[];
  dropped: Record<string, number>;
  stability?: {
    status: string;
    periods: Array<{ period: number; startDate: string; endDate: string; sampleCount: number; rankCorrelation?: number | null; pValue?: number | null; qValue?: number | null }>;
  };
  multipleTesting?: { method: string; falseDiscoveryRate?: number; tests: Array<{ period: number; pValue?: number | null; qValue?: number | null; significant: boolean }> };
};
export type IsolationAudit = { version: string; trainUntil: string; testAfter: string; evaluationEnd: string; embargoDays: number; purgedImmatureTrain: number; embargoedSamples: number; immatureTest: number };
export type CalibrationBucket = {
  bucket: number;
  count: number;
  minScore: number;
  maxScore: number;
  avgScore: number;
  observedProbability: number;
  observedProbabilityInterval?: ConfidenceInterval | null;
  avgLabel: number;
  avgLabelInterval?: ConfidenceInterval | null;
};
export type ScoreCalibration = {
  version: string;
  labelColumn: string;
  bucketCount: number;
  sampleCount: number;
  buckets: CalibrationBucket[];
  missingColumns: string[];
  dropped: Record<string, number>;
  reliability: { status: string; warnings: string[] };
  quality: {
    brierScore?: number | null;
    logLoss?: number | null;
    expectedCalibrationError?: number | null;
  };
};
export type ScanRow = {
  exchange: string;
  code: string;
  date: string;
  score: number;
  grade?: string | null;
};
export type ScanResult = {
  version: string;
  asOfDate?: string | null;
  exchange?: string | null;
  minScore: number;
  scannedCount: number;
  truncated: boolean;
  rows: ScanRow[];
};
export type BaselineModel = {
  version: string;
  labelColumn: string;
  status: string;
  trainCount: number;
  testCount: number;
  positiveRate?: number | null;
  testPositiveRate?: number | null;
  accuracy?: number | null;
  auc?: number | null;
  intercept?: number | null;
  coefficient?: number | null;
  trainUntil?: string | null;
  warnings: string[];
  isolation?: IsolationAudit;
  modelId?: string;
  artifactPath?: string;
};
export type MultiFeatureModel = {
  version: string;
  labelColumn: string;
  featureColumns: string[];
  status: string;
  trainCount: number;
  testCount: number;
  accuracy?: number | null;
  auc?: number | null;
  weights: Record<string, number>;
  warnings: string[];
  isolation?: IsolationAudit;
  modelId?: string;
  artifactPath?: string;
};
export type WalkForwardResult = {
  version: string;
  averageAuc?: number | null;
  averageAccuracy?: number | null;
  folds: Array<{
    trainUntil: string;
    testUntil: string;
    status: string;
    trainCount: number;
    testCount: number;
    auc?: number | null;
    accuracy?: number | null;
  }>;
  warnings: string[];
};
export type DriftMetric = {
  column: string;
  status: "stable" | "watch" | "drift";
  referenceCount: number;
  recentCount: number;
  referenceMean?: number | null;
  recentMean?: number | null;
  standardizedMeanShift?: number | null;
  populationStabilityIndex?: number | null;
  missingRateDelta: number;
};
export type DriftReport = {
  version: string;
  status: "stable" | "watch" | "drift" | "insufficient_data";
  referenceWindow?: {
    startDate: string;
    endDate: string;
    tradingDays: number;
    rows: number;
  };
  recentWindow?: {
    startDate: string;
    endDate: string;
    tradingDays: number;
    rows: number;
  };
  metrics: DriftMetric[];
  segments: Array<{
    exchange: string;
    status: "stable" | "watch" | "drift";
    metrics: DriftMetric[];
  }>;
  warnings: string[];
};
export type FeatureCatalog = {
  version: string;
  snapshotSetHash?: string;
  trackedSecurities?: number;
  featureColumns: string[];
  missingColumns: string[];
  securityCount: number;
  rowCount: number;
  unreadableFiles: number;
  unreadableExamples: string[];
  currentSnapshotFiles?: number;
  staleSnapshotFiles?: number;
  missingCurrentFiles?: number;
  orphanedFiles?: number;
  supersededFiles?: number;
  ready: boolean;
};
export type PortfolioValidation = {
  version: string;
  labelColumn: string;
  topFraction: number;
  sampleCount: number;
  tradingDayCount: number;
  selectedCount: number;
  averageReturn?: number | null;
  netAverageReturn?: number | null;
  benchmarkReturn?: number | null;
  excessReturn?: number | null;
  netExcessReturn?: number | null;
  winRate?: number | null;
  maxDrawdown?: number | null;
  annualizedReturn?: number | null;
  annualizedVolatility?: number | null;
  sharpeRatio?: number | null;
  calmarRatio?: number | null;
  equityCurve: Array<{ date: string; value: number }>;
  benchmarkEquityCurve: Array<{ date: string; value: number }>;
  nonOverlapping: boolean;
  transactionCostBps: number;
  slippageBps: number;
  totalCostRate: number;
  warnings: string[];
};
export type HistoryBackfillTask = {
  status: string;
  done: number;
  total: number;
  completed: number;
  listingHistoryShort: number;
  errors: unknown[];
  currentSecurity?: string | null;
  speed: number;
  etaSeconds?: number | null;
};
export type GenericTask = {
  id: string;
  jobType: string;
  status: string;
  resumable: boolean;
  createdAt: string;
  updatedAt: string;
  done: number;
  total: number;
  rows?: number;
  errors: unknown[];
  currentSecurity?: string | null;
  speed?: number;
  etaSeconds?: number | null;
  stage?: string;
  stages?: Record<
    string,
    { status: string; done: number; total: number; rows: number; errors: number }
  >;
};
export type ProviderMetric = {
  observations: number;
  successes: number;
  success_rate: number;
  mean_latency_seconds: number;
  p95_latency_seconds: number;
  empty_response_count: number;
  missing_field_count: number;
  error_categories: Record<string, number>;
};
export type ProviderObservation = {
  provider: string;
  security: string;
  success: boolean;
  elapsed_seconds: number;
  rows: number;
  missing_fields: string[];
  error_type?: string | null;
  error_message?: string | null;
};
export type ProviderGateReport = {
  gateVersion: string;
  passed: boolean;
  probedAt?: string;
  reasons: string[];
  warnings?: string[];
  providers?: Record<string, ProviderMetric>;
  requiredChecks?: Record<string, boolean>;
  diagnosticChecks?: Record<string, boolean>;
  observations?: ProviderObservation[];
};
export type ProviderGateStatus = {
  available: boolean;
  report: ProviderGateReport | null;
  maxAgeHours: number;
  diagnosticAvailable: boolean;
  diagnostic: ProviderGateReport | null;
};
export type DatasetQuality = {
  totalCached: number;
  shortHistoryCached: number;
  listingHistoryShort: number;
  historyBackfillFailed: number;
  identityMismatchSecurities: number;
  identityMismatchExamples: string[];
  featureRows: number;
  approximateRuleRows: number;
  approximateRuleRatio?: number | null;
  approximateFactorSecurities: number;
  approximateFactorExamples: string[];
  latestDataDate?: string | null;
  freshSecurities: number;
  staleSecurities: number;
  freshnessCoverage: number;
  freshnessMinCoverage: number;
  freshnessThresholdDays: number;
  staleExamples: Array<{ security: string; latestDate: string }>;
  unreadableSecurities: number;
  unreadableExamples: string[];
  qualityEvents: Array<{
    dataset_key: string;
    event_type: string;
    severity: string;
    message: string;
    created_at: string;
  }>;
};
export type CoverageItem = {
  security: string;
  exchange: string;
  code: string;
  name: string;
  status: string;
  rows: number;
  firstDate?: string | null;
  latestDate?: string | null;
  calendarGapCount: number;
  reason: string;
};
export type CoverageResponse = {
  available: boolean;
  total: number;
  report: null | {
    version: string;
    generatedAt: string;
    universeSize: number;
    cachedCount: number;
    readyCount: number;
    repairableCount: number;
    coverageRate: number;
    statusCounts: Record<string, number>;
  };
  items: CoverageItem[];
};
export type MaintenanceSchedule = {
  enabled: boolean;
  hour: number;
  minute: number;
  timezone: string;
  nextRunAt?: string | null;
  lastAttemptAt?: string | null;
  lastTaskId?: string | null;
  lastOutcome?: string | null;
  lastError?: string | null;
};
export type BackupList = {
  path: string;
  items: Array<{ name: string; size: number; createdAt: string }>;
};
export type ResearchRun = {
  runId: string;
  kind: string;
  createdAt: string;
  codeVersion: string;
  parameters: Record<string, unknown>;
  dependencies: Record<string, unknown>;
  dataSnapshot: { manifestHash?: string; securityCount?: number };
  summary: Record<string, unknown>;
};
export type ResearchRunList = {
  version: string;
  runs: ResearchRun[];
  total: number;
  unreadableFiles: number;
};
export type ResearchRunDetail = ResearchRun & { result: Record<string, unknown> };
export type ResearchRunComparison = {
  kind: string;
  left: { runId: string; createdAt: string };
  right: { runId: string; createdAt: string };
  parameterChanges: Array<{ parameter: string; left: unknown; right: unknown }>;
  metrics: Array<{ metric: string; left: unknown; right: unknown; delta?: number | null }>;
};
export type ResearchReadiness = {
  version: string;
  readyForRefresh: boolean;
  readyForAudit: boolean;
  readyForModel: boolean;
  freshnessCoverage: number;
  freshnessMinCoverage: number;
  providerGateAgeHours?: number | null;
  providerGateMaxAgeHours: number;
  checks: Record<string, boolean>;
  blockers: string[];
};
export type ResearchAcceptance = {
  version: string;
  generatedAt: string;
  ready: boolean;
  blockers: string[];
  data: {
    totalCached: number;
    latestDataDate?: string | null;
    freshnessCoverage: number;
    staleSecurities: number;
    unreadableSecurities: number;
    identityMismatchSecurities: number;
  };
  experiments: {
    requiredKinds: string[];
    missingKinds: string[];
    counts: Record<string, number>;
    totalPermanentRuns: number;
  };
  models: {
    registered: number;
    trained: number;
    activeModels: Record<string, unknown>;
  };
  readiness: ResearchReadiness;
};
export type ScoreStatus = {
  currentVersion: string;
  snapshotSetHash?: string;
  trackedSecurities?: number;
  files: number;
  currentSnapshotFiles?: number;
  staleSnapshotFiles?: number;
  missingCurrentFiles?: number;
  orphanedFiles?: number;
  supersededFiles?: number;
  rows: number;
  compatibleFiles: number;
  staleFiles: number;
  unreadableFiles: number;
  unreadableExamples: string[];
  incompatibleFiles: number;
  legacyFiles: number;
  ready: boolean;
};
export type ModelArtifact = {
  modelId: string;
  kind: string;
  createdAt: string;
  version?: string | null;
  status?: string | null;
  labelColumn?: string | null;
  artifactPath: string;
  dependencies: Record<string, unknown>;
  active: boolean;
};
export type ModelRegistryStatus = {
  version: string;
  activationVersion: string;
  activeModels: Record<
    string,
    {
      modelId: string;
      kind: string;
      promotedAt: string;
      previousModelId?: string | null;
    }
  >;
  artifacts: ModelArtifact[];
  unreadableFiles: number;
  unreadableExamples: string[];
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let message = `请求失败：${response.status}`;
    try {
      const body = (await response.json()) as {
        detail?: string | { message?: string };
      };
      if (typeof body.detail === "string") message = body.detail;
      else if (body.detail?.message) message = body.detail.message;
    } catch {
      /* keep the status-based fallback */
    }
    const allowed = response.headers?.get("allow");
    if (allowed) message += ` · Allow ${allowed}`;
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

export const api = {
  health: () => request<Health>("/api/system/health"),
  providerGate: () => request<ProviderGateStatus>("/api/system/provider-gate"),
  readiness: () => request<ResearchReadiness>("/api/system/readiness"),
  researchAcceptance: () =>
    request<ResearchAcceptance>("/api/system/research-acceptance"),
  scoreStatus: () => request<ScoreStatus>("/api/scores/status"),
  modelRegistry: () => request<ModelRegistryStatus>("/api/model/p7/registry"),
  promoteModel: (modelId: string) =>
    request<{
      status: string;
      modelId: string;
      kind: string;
      promotedAt: string;
      previousModelId?: string | null;
    }>(`/api/model/p7/registry/${encodeURIComponent(modelId)}/promote`, {
      method: "POST",
    }),
  probeProviders: (quick = false) =>
    request<{ taskId: string; quick: boolean }>(
      `/api/system/provider-gate/probe?quick=${quick}`,
      { method: "POST" },
    ),
  recentTasks: (limit = 10) =>
    request<GenericTask[]>(`/api/tasks/recent?limit=${limit}`),
  taskStatus: (taskId: string) => request<GenericTask>(`/api/tasks/${taskId}`),
  buildResearchPipeline: (scope: "representative" | "stale" | "all" = "stale") =>
    request<{ taskId: string; total: number; stages: number }>(
      "/api/pipeline/research/build",
      { method: "POST", body: JSON.stringify({ scope }) },
    ),
  labelStatus: () => request<LabelStatus>("/api/labels/status"),
  bars: (exchange: string, code: string) =>
    request<Bar[]>(`/api/securities/${exchange}/${code}/bars`),
  securities: (query: string) =>
    request<Security[]>(`/api/securities?query=${encodeURIComponent(query)}`),
  audit: (exchange: string, code: string, signalDate: string) =>
    request<Audit>("/api/p1/audit", {
      method: "POST",
      body: JSON.stringify({ exchange, code, signal_date: signalDate }),
    }),
  importData: (scope: "representative" | "failed" | "all") =>
    request<{
      taskId: string;
      total: number;
      requested: number;
      skipped: number;
    }>("/api/datasets/import", {
      method: "POST",
      body: JSON.stringify({ scope }),
    }),
  importTask: (taskId: string) =>
    request<{
      status: string;
      done: number;
      total: number;
      errors: unknown[];
      currentSecurity?: string;
      stage?: string;
      speed?: number;
      etaSeconds?: number;
      directAvailable?: boolean;
    }>(`/api/datasets/tasks/${taskId}`),
  startHistoryBackfill: () =>
    request<{ taskId: string; total: number; threshold: number }>(
      "/api/datasets/import",
      {
        method: "POST",
        body: JSON.stringify({ scope: "history_backfill" }),
      },
    ),
  historyBackfillTask: (taskId: string) =>
    request<HistoryBackfillTask>(`/api/datasets/backfill-history/${taskId}`),
  quality: () => request<DatasetQuality>("/api/datasets/quality"),
  coverage: (status = "") =>
    request<CoverageResponse>(
      `/api/datasets/coverage?limit=100${status ? `&status=${encodeURIComponent(status)}` : ""}`,
    ),
  rebuildCoverage: () =>
    request<{ taskId: string }>("/api/datasets/coverage/rebuild", {
      method: "POST",
      body: JSON.stringify({ refresh_security_master: false }),
    }),
  runRepairQueue: (limit = 500) =>
    request<{ taskId: string; total: number }>(
      "/api/datasets/repair-queue/run",
      { method: "POST", body: JSON.stringify({ limit }) },
    ),
  incrementalUpdate: () =>
    request<{ taskId: string; total: number }>("/api/datasets/incremental", {
      method: "POST",
    }),
  maintenanceSchedule: () =>
    request<MaintenanceSchedule>("/api/system/maintenance-schedule"),
  configureMaintenanceSchedule: (enabled: boolean, hour: number, minute: number) =>
    request<MaintenanceSchedule>("/api/system/maintenance-schedule", {
      method: "PUT",
      body: JSON.stringify({ enabled, hour, minute }),
    }),
  backups: () => request<BackupList>("/api/system/backups"),
  createBackup: () =>
    request<{ taskId: string }>("/api/system/backups", { method: "POST" }),
  researchRuns: (kind = "", limit = 100) =>
    request<ResearchRunList>(
      `/api/research/runs?limit=${limit}${kind ? `&kind=${encodeURIComponent(kind)}` : ""}`,
    ),
  researchRun: (runId: string) =>
    request<ResearchRunDetail>(`/api/research/runs/${encodeURIComponent(runId)}`),
  compareResearchRuns: (left: string, right: string) =>
    request<ResearchRunComparison>(
      `/api/research/runs/compare?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`,
    ),
  buildLabels: (scope: "representative" | "failed" | "all") =>
    request<{ taskId: string; total: number }>("/api/labels/build", {
      method: "POST",
      body: JSON.stringify({ scope }),
    }),
  labelTask: (taskId: string) =>
    request<{
      status: string;
      done: number;
      total: number;
      rows: number;
      errors: unknown[];
    }>(`/api/labels/tasks/${taskId}`),
  buildFeatures: (scope: "representative" | "all") =>
    request<{ taskId: string; total: number }>("/api/features/build", {
      method: "POST",
      body: JSON.stringify({ scope }),
    }),
  featureTask: (taskId: string) =>
    request<{
      status: string;
      done: number;
      total: number;
      rows: number;
      errors: unknown[];
      currentSecurity?: string;
    }>(`/api/features/tasks/${taskId}`),
  buildScores: (scope: "representative" | "all") =>
    request<{ taskId: string; total: number }>("/api/scores/build", {
      method: "POST",
      body: JSON.stringify({ scope }),
    }),
  scoreTask: (taskId: string) =>
    request<{
      status: string;
      done: number;
      total: number;
      rows: number;
      errors: unknown[];
      currentSecurity?: string;
    }>(`/api/scores/tasks/${taskId}`),
  featureAudit: (exchange: string, code: string, signalDate: string) =>
    request<FeatureAudit>("/api/p2/audit", {
      method: "POST",
      body: JSON.stringify({ exchange, code, signal_date: signalDate }),
    }),
  scoreAudit: (exchange: string, code: string, signalDate: string) =>
    request<ScoreAudit>("/api/p3/audit", {
      method: "POST",
      body: JSON.stringify({ exchange, code, signal_date: signalDate }),
    }),
  validateSingleFactor: (labelColumn = "p20_executable_return") =>
    request<SingleFactorValidation>("/api/validation/single-factor", {
      method: "POST",
      body: JSON.stringify({
        factor_column: "score",
        label_column: labelColumn,
        buckets: 5,
      }),
    }),
  calibrateScore: (labelColumn = "p20_executable_return", buckets = 10) =>
    request<ScoreCalibration>("/api/validation/calibration", {
      method: "POST",
      body: JSON.stringify({ label_column: labelColumn, buckets }),
    }),
  scanP3: (minScore = 70, exchange?: string, asOfDate?: string) =>
    request<ScanResult>("/api/scan/p3", {
      method: "POST",
      body: JSON.stringify({
        min_score: minScore,
        exchange,
        as_of_date: asOfDate || undefined,
        limit: 50,
      }),
    }),
  trainBaseline: (trainUntil?: string, labelColumn = "p20_executable_return") =>
    request<BaselineModel>("/api/model/p7/baseline", {
      method: "POST",
      body: JSON.stringify({
        label_column: labelColumn,
        train_until: trainUntil || undefined,
      }),
    }),
  trainMultifeature: (
    trainUntil?: string,
    labelColumn = "p20_executable_return",
  ) =>
    request<MultiFeatureModel>("/api/model/p7/multifeature", {
      method: "POST",
      body: JSON.stringify({
        label_column: labelColumn,
        train_until: trainUntil || undefined,
      }),
    }),
  walkForward: (labelColumn = "p20_executable_return", folds = 3) =>
    request<WalkForwardResult>("/api/model/p7/walk-forward", {
      method: "POST",
      body: JSON.stringify({ label_column: labelColumn, folds }),
    }),
  runDriftMonitor: (recentDays = 60, referenceDays = 250) =>
    request<DriftReport>("/api/monitoring/drift", {
      method: "POST",
      body: JSON.stringify({
        recent_days: recentDays,
        reference_days: referenceDays,
      }),
    }),
  featureCatalog: () => request<FeatureCatalog>("/api/model/p7/features"),
  validatePortfolio: (
    topFraction = 0.1,
    labelColumn = "p20_executable_return",
    asOfDate?: string,
    transactionCostBps = 10,
    slippageBps = 5,
  ) =>
    request<PortfolioValidation>("/api/validation/portfolio", {
      method: "POST",
      body: JSON.stringify({
        label_column: labelColumn,
        top_fraction: topFraction,
        as_of_date: asOfDate || undefined,
        non_overlapping: true,
        transaction_cost_bps: transactionCostBps,
        slippage_bps: slippageBps,
      }),
    }),
};
