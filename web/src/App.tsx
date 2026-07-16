import { FormEvent, useEffect, useState } from "react";
import {
  api,
  type Audit,
  type Bar,
  type FeatureAudit,
  type FeatureValue,
  type Health,
  type LabelStatus,
  type Security,
  type ScoreAudit,
  type SingleFactorValidation,
  type ScoreCalibration,
  type ScanResult,
  type BaselineModel,
  type PortfolioValidation,
  type FeatureCatalog,
  type MultiFeatureModel,
  type WalkForwardResult,
  type ProviderGateStatus,
  type DatasetQuality,
  type ResearchReadiness,
  type ScoreStatus,
  type ModelRegistryStatus,
  type GenericTask,
  type CoverageResponse,
  type MaintenanceSchedule,
  type BackupList,
  type ResearchRunList,
  type ResearchRunComparison,
  type DriftReport,
  type ResearchAcceptance,
} from "./api";
import { KlineChart } from "./KlineChart";
import { EquityCurveChart } from "./EquityCurveChart";
import "./styles.css";

const pct = (value?: number | null) =>
  value == null ? "—" : `${(value * 100).toFixed(2)}%`;
const intervalPct = (value?: { lower: number; upper: number } | null) =>
  value ? `${pct(value.lower)}～${pct(value.upper)}` : "—";
const coverageStatusNames: Record<string, string> = {
  ready: "可研究",
  missing: "缺少缓存",
  unreadable: "文件不可读",
  short_history: "日线历史不足",
  stale: "行情过期",
  calendar_gap: "行情有缺口",
  approximate_factor: "近似复权",
};
const researchKindNames: Record<string, string> = {
  "p4-single-factor": "P4 单因子验证",
  "p5-calibration": "P5 概率校准",
  "p6-scan": "P6 高分扫描",
  "p7-baseline": "P7 基线模型",
  "p7-multifeature": "P7 多特征模型",
  "p7-walk-forward": "P7 滚动验证",
  "drift-monitor": "特征与评分漂移监控",
  "p8-portfolio": "P8 组合验证",
};
const groupNames = {
  trend: "趋势",
  position: "位置",
  momentum: "动量",
  volumePrice: "量价",
  tradingBehavior: "交易行为",
};
const featureNames: Record<string, string> = {
  score: "P3 结构评分",
  ma5: "MA5",
  ma10: "MA10",
  ma20: "MA20",
  ma60: "MA60",
  ma5_slope: "MA5 五日斜率",
  ma10_slope: "MA10 五日斜率",
  ma20_slope: "MA20 五日斜率",
  ma60_slope: "MA60 五日斜率",
  close_to_ma5: "收盘偏离 MA5",
  close_to_ma10: "收盘偏离 MA10",
  close_to_ma20: "收盘偏离 MA20",
  close_to_ma60: "收盘偏离 MA60",
  bullish_alignment: "多头排列",
  bearish_alignment: "空头排列",
  range_position_20: "20 日位置",
  range_position_60: "60 日位置",
  range_position_120: "120 日位置",
  range_position_250: "250 日位置",
  drawdown_from_high_20: "距 20 日高点",
  drawdown_from_high_60: "距 60 日高点",
  drawdown_from_high_120: "距 120 日高点",
  drawdown_from_high_250: "距 250 日高点",
  return_5: "5 日动量",
  return_10: "10 日动量",
  return_20: "20 日动量",
  return_60: "60 日动量",
  return_120: "120 日动量",
  volume_ratio_5: "5 日量比",
  volume_percentile_20: "20 日成交量分位",
  amount: "成交额",
  volatility_20: "20 日波动",
  amplitude: "当日振幅",
  is_limit_up: "当日涨停",
  limit_up_count_20: "20 日涨停数",
  locked_limit_up_streak: "连续一字板",
  gap_open: "开盘缺口",
  suspension_gap_days: "停牌间隔",
  is_approx: "交易规则是否近似",
  rule_reason: "交易规则依据",
};
const featureValue = (value: FeatureValue) =>
  value == null
    ? "历史不足"
    : typeof value === "boolean"
      ? value
        ? "是"
        : "否"
      : typeof value === "number"
        ? value.toFixed(4)
        : p1TermName(value);
const ResultLabelOptions = () => (
  <>
    <option value="p5_executable_return">P5 计划收盘卖出</option>
    <option value="p5_delayed_executable_return">P5 可执行顺延卖出</option>
    <option value="p10_executable_return">P10 计划收盘卖出</option>
    <option value="p10_delayed_executable_return">P10 可执行顺延卖出</option>
    <option value="p20_executable_return">P20 计划收盘卖出</option>
    <option value="p20_delayed_executable_return">P20 可执行顺延卖出</option>
    <option value="p60_executable_return">P60 计划收盘卖出</option>
    <option value="p60_delayed_executable_return">P60 可执行顺延卖出</option>
  </>
);
const resultLabelNames: Record<string, string> = {
  p5_executable_return: "P5 计划收盘卖出",
  p5_delayed_executable_return: "P5 可执行顺延卖出",
  p10_executable_return: "P10 计划收盘卖出",
  p10_delayed_executable_return: "P10 可执行顺延卖出",
  p20_executable_return: "P20 计划收盘卖出",
  p20_delayed_executable_return: "P20 可执行顺延卖出",
  p60_executable_return: "P60 计划收盘卖出",
  p60_delayed_executable_return: "P60 可执行顺延卖出",
};
const resultLabelName = (value?: string | null) =>
  value ? (resultLabelNames[value] ?? value) : "—";
const modelKindNames: Record<string, string> = {
  baseline: "P3 单分数基线",
  multifeature: "P2/P3 多特征基线",
  walk_forward: "滚动窗口验证",
};
type TaskView = {
  kind: string;
  id: string;
  status: string;
  done: number;
  total: number;
  rows?: number;
  errors: number;
  errorItems: unknown[];
  current?: string | null;
  speed?: number;
  etaSeconds?: number | null;
  createdAt?: string;
  updatedAt?: string;
  resumable?: boolean;
};
const taskErrorText = (error: unknown) =>
  typeof error === "string"
    ? error
    : error && typeof error === "object"
      ? [
          String("security" in error ? error.security : ""),
          String("message" in error ? error.message : ""),
        ]
          .filter(Boolean)
          .join("：")
      : String(error);
const taskKindNames: Record<string, string> = {
  import: "行情导入",
  incremental: "日线增量更新",
  repair: "异常证券修复",
  coverage: "市场覆盖检查",
  backup: "数据备份",
  history_backfill: "历史补全",
  labels: "P1 标签",
  features: "P2 特征",
  scores: "P3 评分",
  provider_probe: "数据源诊断",
};
const taskStatusNames: Record<string, string> = {
  queued: "等待中",
  running: "进行中",
  completed: "已完成",
  completed_with_errors: "完成（有错误）",
  failed: "失败",
  interrupted: "已中断（可恢复）",
};
const taskStatusName = (status: string) => taskStatusNames[status] ?? status;
const taskElapsedTime = (createdAt?: string, updatedAt?: string) => {
  if (!createdAt || !updatedAt) return null;
  const seconds = Math.max(
    0,
    Math.round((Date.parse(updatedAt) - Date.parse(createdAt)) / 1000),
  );
  if (!Number.isFinite(seconds)) return null;
  if (seconds < 60) return `${seconds} 秒`;
  if (seconds < 3600)
    return `${Math.floor(seconds / 60)} 分 ${seconds % 60} 秒`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours} 小时 ${minutes} 分`;
};
const p1TermNames: Record<string, string> = {
  ok: "正常",
  eligible: "符合样本资格",
  "invalid-ohlc": "价格字段无效",
  "rights-warn": "权息数据需要复核",
  "insufficient-history": "历史不足 250 个交易日",
  "noLimit-excluded": "无涨跌幅限制，已排除",
  executable: "可正常执行",
  delayed: "顺延后可执行",
  "insufficient-forward-data": "未来交易日不足",
  "suspended-abandoned": "疑似长期停牌，放弃入场",
  "invalid-entry-price": "入场价格无效",
  abandoned: "连续受阻，已放弃",
  success: "成功",
  failed: "失败",
  "benchmark-missing": "基准行情缺失",
  "same-day-double-hit": "同日同时触及止盈和止损，保守判失败",
  "downside-hit-first": "先触及下行阈值",
  "upside-hit-first": "先触及上行阈值",
  "no-upside-hit": "观察期内未触及上行阈值",
  "current-name approximation": "根据当前证券名称近似推断历史状态",
  "entry window has no price limit": "入场窗口处于无涨跌幅限制阶段",
  "non-positive entry price": "入场价格不是有效正数",
  "entry blocked through T+3": "T+1 至 T+3 均无法买入",
  "opening gain below executable threshold": "开盘涨幅低于不可买入阈值",
  "exit window incomplete": "卖出顺延窗口尚未完整结束",
  "target close executable": "计划日收盘可执行卖出",
  "exit delayed": "计划日无法卖出，已顺延",
  "exit blocked through delay window": "整个顺延窗口均无法卖出",
  "board/date rule": "按交易所、板块和日期适用正式涨跌幅规则",
  "approximated ST": "历史 ST 状态采用近似推断",
  "historical status inferred": "历史特殊交易状态由现有信息近似推断",
  "available_history<120": "有效历史不足 120 个交易日",
  "limit-rule-approx": "交易规则使用了近似状态",
};
const p1TermName = (value?: string | null) =>
  value ? (p1TermNames[value] ?? value) : "—";
const researchStatusNames: Record<string, string> = {
  trained: "已完成训练",
  review: "需要复核",
  insufficient_data: "数据不足",
  insufficient_sample: "样本不足",
  usable: "可用于研究",
  ready: "就绪",
};
const researchStatusName = (status?: string | null) =>
  status ? (researchStatusNames[status] ?? status) : "—";
const priceBasisNames: Record<string, string> = {
  "raw+qfq+total-return": "原始价 + 前复权 + 总回报",
};
const versionNames: Record<string, string> = {
  snapshotVersion: "数据快照",
  factorVersion: "复权因子",
  limitRuleVersion: "交易规则",
  featureDefinitionVersion: "特征定义",
};
const initialAuditParameter = (name: string, fallback: string) => {
  const value = new URLSearchParams(window.location.search).get(name)?.trim();
  if (!value) return fallback;
  if (name === "exchange")
    return value === "sh" || value === "sz" ? value : fallback;
  if (name === "code") return /^\d{6}$/.test(value) ? value : fallback;
  if (name === "signalDate")
    return /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : fallback;
  return value;
};
const providerNames: Record<string, string> = {
  tencent: "腾讯股票",
  "tencent-index": "腾讯指数",
  "sina-factor": "新浪复权因子",
  "sina-raw": "新浪原始行情",
  calendar: "交易日历",
  eastmoney: "东方财富诊断",
};
const providerCheckNames: Record<string, string> = {
  tencentStocks: "腾讯沪深股票",
  tencentIndexes: "腾讯沪深指数",
  sinaFactors: "新浪复权因子",
  sinaRawFallback: "新浪行情回退",
  tradingCalendar: "交易日历",
  eastmoney: "东方财富诊断",
};
const readinessCheckNames: Record<string, string> = {
  providerGate: "数据源 Gate 通过",
  providerGateFresh: "数据源 Gate 未过期",
  hasMarketData: "存在本地行情",
  marketDataReadable: "行情文件可读",
  securityIdentityConsistent: "交易所与证券代码一致",
  marketDataFresh: "行情覆盖新鲜",
  labelsAvailable: "已有 P1 标签",
  labelsReadable: "P1 标签可读",
  labelsCurrent: "P1 标签版本最新",
  featuresReady: "P2 特征覆盖达标",
  scoresAvailable: "已有 P3 评分",
  scoresReadable: "P3 评分可读",
  scoresCurrent: "P3 评分版本最新",
};

export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [providerGate, setProviderGate] = useState<ProviderGateStatus | null>(
    null,
  );
  const [labelStatus, setLabelStatus] = useState<LabelStatus | null>(null);
  const [exchange, setExchange] = useState(() =>
    initialAuditParameter("exchange", "sh"),
  );
  const [code, setCode] = useState(() =>
    initialAuditParameter("code", "600000"),
  );
  const [securitySuggestions, setSecuritySuggestions] = useState<Security[]>(
    [],
  );
  const [signalDate, setSignalDate] = useState(() =>
    initialAuditParameter("signalDate", "2024-01-02"),
  );
  const [bars, setBars] = useState<Bar[]>([]);
  const [audit, setAudit] = useState<Audit | null>(null);
  const [featureAudit, setFeatureAudit] = useState<FeatureAudit | null>(null);
  const [scoreAudit, setScoreAudit] = useState<ScoreAudit | null>(null);
  const [validation, setValidation] = useState<SingleFactorValidation | null>(
    null,
  );
  const [validationLabel, setValidationLabel] = useState(
    "p20_executable_return",
  );
  const [calibration, setCalibration] = useState<ScoreCalibration | null>(null);
  const [calibrationLabel, setCalibrationLabel] = useState(
    "p20_executable_return",
  );
  const [calibrationBuckets, setCalibrationBuckets] = useState(10);
  const [scan, setScan] = useState<ScanResult | null>(null);
  const [scanExchange, setScanExchange] = useState("");
  const [scanMinScore, setScanMinScore] = useState(70);
  const [scanAsOfDate, setScanAsOfDate] = useState("");
  const [baseline, setBaseline] = useState<BaselineModel | null>(null);
  const [baselineTrainUntil, setBaselineTrainUntil] = useState("");
  const [baselineLabel, setBaselineLabel] = useState("p20_executable_return");
  const [featureCatalog, setFeatureCatalog] = useState<FeatureCatalog | null>(
    null,
  );
  const [multifeature, setMultifeature] = useState<MultiFeatureModel | null>(
    null,
  );
  const [walkForward, setWalkForward] = useState<WalkForwardResult | null>(
    null,
  );
  const [driftReport, setDriftReport] = useState<DriftReport | null>(null);
  const [driftRecentDays, setDriftRecentDays] = useState(60);
  const [driftReferenceDays, setDriftReferenceDays] = useState(250);
  const [portfolio, setPortfolio] = useState<PortfolioValidation | null>(null);
  const [portfolioFraction, setPortfolioFraction] = useState(10);
  const [portfolioLabel, setPortfolioLabel] = useState("p20_executable_return");
  const [portfolioAsOfDate, setPortfolioAsOfDate] = useState("");
  const [transactionCostBps, setTransactionCostBps] = useState(10);
  const [slippageBps, setSlippageBps] = useState(5);
  const [message, setMessage] = useState("等待检查");
  const [busy, setBusy] = useState(false);
  const [cachedCount, setCachedCount] = useState<number | null>(null);
  const [approximateRuleRatio, setApproximateRuleRatio] = useState<
    number | null
  >(null);
  const [datasetQuality, setDatasetQuality] = useState<DatasetQuality | null>(
    null,
  );
  const [readiness, setReadiness] = useState<ResearchReadiness | null>(null);
  const [researchAcceptance, setResearchAcceptance] =
    useState<ResearchAcceptance | null>(null);
  const [scoreStatus, setScoreStatus] = useState<ScoreStatus | null>(null);
  const [modelRegistry, setModelRegistry] =
    useState<ModelRegistryStatus | null>(null);
  const [taskView, setTaskView] = useState<TaskView | null>(null);
  const [taskHistory, setTaskHistory] = useState<GenericTask[]>([]);
  const [taskTypeFilter, setTaskTypeFilter] = useState("");
  const [taskStatusFilter, setTaskStatusFilter] = useState("");
  const [coverage, setCoverage] = useState<CoverageResponse | null>(null);
  const [coverageStatus, setCoverageStatus] = useState("");
  const [maintenance, setMaintenance] = useState<MaintenanceSchedule | null>(null);
  const [backups, setBackups] = useState<BackupList | null>(null);
  const [researchRuns, setResearchRuns] = useState<ResearchRunList | null>(null);
  const [researchKindFilter, setResearchKindFilter] = useState("");
  const [comparison, setComparison] = useState<ResearchRunComparison | null>(null);
  const [compareLeft, setCompareLeft] = useState("");
  const [compareRight, setCompareRight] = useState("");

  const showTask = (
    kind: string,
    id: string,
    task: {
      status: string;
      done: number;
      total: number;
      rows?: number;
      errors: unknown[];
      currentSecurity?: string | null;
      speed?: number;
      etaSeconds?: number | null;
      createdAt?: string;
      updatedAt?: string;
      resumable?: boolean;
    },
  ) => {
    setTaskView({
      kind,
      id,
      status: task.status,
      done: task.done,
      total: task.total,
      rows: task.rows,
      errors: task.errors.length,
      errorItems: task.errors,
      current: task.currentSecurity,
      speed: task.speed,
      etaSeconds: task.etaSeconds,
      createdAt: task.createdAt,
      updatedAt: task.updatedAt,
      resumable: task.resumable,
    });
  };

  async function inspectTask(task: GenericTask) {
    try {
      const detail = await api.taskStatus(task.id);
      showTask(
        taskKindNames[detail.jobType] ?? detail.jobType,
        detail.id,
        detail,
      );
      setMessage(`已载入任务 ${detail.id} 的完整记录`);
      window.setTimeout(
        () =>
          document
            .getElementById("task-progress")
            ?.scrollIntoView?.({ behavior: "smooth" }),
        0,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "读取任务失败");
    }
  }

  async function refreshTaskHistory(announce = true) {
    try {
      const tasks = await api.recentTasks(50);
      const items = Array.isArray(tasks) ? tasks : [];
      setTaskHistory(items);
      if (announce) setMessage(`任务历史已刷新，共 ${items.length} 条`);
    } catch (error) {
      if (announce)
        setMessage(error instanceof Error ? error.message : "刷新任务历史失败");
    }
  }

  function resumeHistoricalTask(task: GenericTask) {
    if (task.status !== "interrupted" || !task.resumable) {
      setMessage(`任务 ${task.id} 当前不可续跑`);
      return;
    }
    setMessage(
      `正在恢复${taskKindNames[task.jobType] ?? task.jobType}任务 ${task.id}`,
    );
    switch (task.jobType) {
      case "import":
        void startImport("all");
        break;
      case "incremental":
        void runIncrementalUpdate();
        break;
      case "repair":
        void runRepairQueue();
        break;
      case "history_backfill":
        void startHistoryBackfill();
        break;
      case "labels":
        void startLabels("all");
        break;
      case "features":
        void startFeatures();
        break;
      case "scores":
        void startScores();
        break;
      default:
        setMessage(`任务类型 ${task.jobType} 不支持续跑`);
    }
  }

  const refreshResearchStatus = () =>
    Promise.all([
      api.labelStatus().then(setLabelStatus),
      api.featureCatalog().then(setFeatureCatalog),
      api.scoreStatus().then(setScoreStatus),
      api.readiness().then(setReadiness),
    ]).catch(() => undefined);

  useEffect(() => {
    api
      .health()
      .then(setHealth)
      .catch((e) => setMessage(e.message));
    api
      .providerGate()
      .then(setProviderGate)
      .catch(() => undefined);
    api
      .readiness()
      .then(setReadiness)
      .catch(() => undefined);
    api
      .scoreStatus()
      .then(setScoreStatus)
      .catch(() => undefined);
    api
      .featureCatalog()
      .then(setFeatureCatalog)
      .catch(() => undefined);
    api
      .modelRegistry()
      .then(setModelRegistry)
      .catch(() => undefined);
    api
      .labelStatus()
      .then(setLabelStatus)
      .catch(() => undefined);
    api.coverage().then(setCoverage).catch(() => undefined);
    api.maintenanceSchedule().then(setMaintenance).catch(() => undefined);
    api.backups().then(setBackups).catch(() => undefined);
    api.researchRuns().then(setResearchRuns).catch(() => undefined);
    const restoreTask = (task: GenericTask) => {
      showTask(taskKindNames[task.jobType] ?? task.jobType, task.id, task);
      if (task.status === "queued" || task.status === "running") {
        window.setTimeout(
          () =>
            api
              .taskStatus(task.id)
              .then(restoreTask)
              .catch(() => undefined),
          1000,
        );
      }
    };
    let didRestoreTask = false;
    const refreshTasks = () =>
      api
        .recentTasks(50)
        .then((tasks) => {
          const items = Array.isArray(tasks) ? tasks : [];
          setTaskHistory(items);
          if (!didRestoreTask && items[0]) {
            didRestoreTask = true;
            restoreTask(items[0]);
          }
        })
        .catch(() => undefined);
    refreshTasks();
    const refresh = () =>
      api
        .quality()
        .then((q) => {
          setCachedCount(q.totalCached);
          setApproximateRuleRatio(q.approximateRuleRatio ?? null);
          setDatasetQuality(q);
        })
        .catch(() => undefined);
    refresh();
    const timer = window.setInterval(refresh, 5000);
    const taskTimer = window.setInterval(refreshTasks, 15000);
    return () => {
      window.clearInterval(timer);
      window.clearInterval(taskTimer);
    };
  }, []);

  useEffect(() => {
    const query = code.trim();
    if (query.length < 2) {
      setSecuritySuggestions([]);
      return;
    }
    const timer = window.setTimeout(() => {
      api
        .securities(query)
        .then((rows) => setSecuritySuggestions(Array.isArray(rows) ? rows : []))
        .catch(() => setSecuritySuggestions([]));
    }, 250);
    return () => window.clearTimeout(timer);
  }, [code]);

  const changeSecurityQuery = (value: string) => {
    setCode(value);
    const selected = securitySuggestions.find((item) => item.code === value);
    if (selected) setExchange(selected.exchange);
  };

  const persistAuditLocation = (nextSignalDate = signalDate) => {
    const params = new URLSearchParams(window.location.search);
    params.set("exchange", exchange);
    params.set("code", code);
    params.set("signalDate", nextSignalDate);
    window.history.replaceState(
      window.history.state,
      "",
      `${window.location.pathname}?${params.toString()}#p1-auditor`,
    );
  };

  async function runAudit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setMessage("正在读取本地行情并计算…");
    try {
      const [nextBars, nextAudit, nextFeatures, nextScore] = await Promise.all([
        api.bars(exchange, code),
        api.audit(exchange, code, signalDate),
        api.featureAudit(exchange, code, signalDate),
        api.scoreAudit(exchange, code, signalDate),
      ]);
      setBars(nextBars);
      setAudit(nextAudit);
      setFeatureAudit(nextFeatures);
      setScoreAudit(nextScore);
      persistAuditLocation();
      setMessage(`已载入 ${nextBars.length} 个交易日`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "计算失败");
    } finally {
      setBusy(false);
    }
  }

  async function chooseLatestMatureSignalDate() {
    setBusy(true);
    setMessage("正在查找最近的 P60 成熟交易日…");
    try {
      const nextBars = await api.bars(exchange, code);
      const futureTradingDays = 61;
      const signalIndex = nextBars.length - 1 - futureTradingDays;
      if (signalIndex < 250) {
        setMessage(
          `历史不足：共 ${nextBars.length} 个交易日，无法同时满足 250 日历史和 P60 成熟要求`,
        );
        return;
      }
      const nextSignalDate = nextBars[signalIndex].date;
      setSignalDate(nextSignalDate);
      persistAuditLocation(nextSignalDate);
      setMessage(`已选择最近 P60 成熟日 ${nextSignalDate}，可点击“计算并审计”`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "读取交易日失败");
    } finally {
      setBusy(false);
    }
  }

  async function startImport(scope: "representative" | "failed" | "all") {
    setBusy(true);
    try {
      const result = await api.importData(scope);
      setMessage(
        `任务 ${result.taskId} 已启动：待下载 ${result.total}，已跳过缓存 ${result.skipped}`,
      );
      const poll = async () => {
        const task = await api.importTask(result.taskId);
        showTask(
          scope === "all"
            ? "全市场行情"
            : scope === "failed"
              ? "失败行情重试"
              : "代表样本行情",
          result.taskId,
          task,
        );
        const current = task.currentSecurity
          ? `，最近 ${task.currentSecurity}`
          : "";
        const speed = task.speed
          ? `，${task.speed.toFixed(2)} 只/秒，ETA ${task.etaSeconds ?? "—"} 秒`
          : "";
        const provider =
          task.directAvailable === false ? "，已切换 AkShare/Sina" : "";
        setMessage(
          `任务 ${result.taskId}：${task.status} ${task.done}/${task.total}，错误 ${task.errors.length}${speed}${current}${provider}`,
        );
        if (task.status === "queued" || task.status === "running")
          window.setTimeout(poll, 1000);
        else {
          setBusy(false);
          setMessage(
            `任务${task.errors.length ? "完成但有错误" : "已完成"}：${task.done}/${task.total}，错误 ${task.errors.length}`,
          );
        }
      };
      await poll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "启动失败");
      setBusy(false);
    } finally {
      /* polling releases busy when the task reaches a terminal state */
    }
  }

  async function pollOperationsTask(taskId: string, kind: string) {
    const poll = async (): Promise<void> => {
      const task = await api.taskStatus(taskId);
      showTask(kind, taskId, task);
      setMessage(`${kind}：${task.done}/${task.total}，错误 ${task.errors.length}`);
      if (task.status === "queued" || task.status === "running") {
        window.setTimeout(() => void poll(), 1000);
      } else {
        setBusy(false);
        await Promise.all([
          api.coverage(coverageStatus).then(setCoverage),
          api.quality().then(setDatasetQuality),
          api.backups().then(setBackups),
          refreshTaskHistory(false),
        ]).catch(() => undefined);
      }
    };
    await poll();
  }

  async function rebuildCoverage() {
    setBusy(true);
    setMessage("正在生成全市场覆盖台账…");
    try {
      const result = await api.rebuildCoverage();
      await pollOperationsTask(result.taskId, "市场覆盖检查");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "覆盖检查启动失败");
      setBusy(false);
    }
  }

  async function runRepairQueue() {
    setBusy(true);
    setMessage("正在提交异常证券修复队列…");
    try {
      const result = await api.runRepairQueue();
      await pollOperationsTask(result.taskId, "异常证券修复");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "修复队列启动失败");
      setBusy(false);
    }
  }

  async function runIncrementalUpdate() {
    setBusy(true);
    setMessage("正在提交日线增量更新…");
    try {
      const result = await api.incrementalUpdate();
      await pollOperationsTask(result.taskId, "日线增量更新");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "增量更新启动失败");
      setBusy(false);
    }
  }

  async function toggleMaintenanceSchedule() {
    try {
      const current = maintenance ?? { enabled: false, hour: 18, minute: 30 };
      const next = await api.configureMaintenanceSchedule(
        !current.enabled,
        current.hour,
        current.minute,
      );
      setMaintenance(next);
      setMessage(next.enabled ? "工作日自动增量更新已开启" : "自动增量更新已关闭");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "更新维护计划失败");
    }
  }

  async function createBackup() {
    setBusy(true);
    setMessage("正在创建并校验数据备份…");
    try {
      const result = await api.createBackup();
      await pollOperationsTask(result.taskId, "数据备份");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "备份启动失败");
      setBusy(false);
    }
  }

  async function startLabels(scope: "failed" | "all" = "all") {
    setBusy(true);
    try {
      const result = await api.buildLabels(scope);
      setMessage(`P1 标签任务 ${result.taskId.slice(0, 8)} 已启动`);
      const poll = async () => {
        const task = await api.labelTask(result.taskId);
        showTask("P1 标签", result.taskId, task);
        setMessage(
          `P1 标签：${task.done}/${task.total}，已生成 ${task.rows} 条`,
        );
        if (task.status === "queued" || task.status === "running")
          window.setTimeout(poll, 1000);
        else {
          setBusy(false);
          if (task.errors.length)
            setMessage(`标签完成，但有 ${task.errors.length} 个错误`);
          void refreshResearchStatus();
        }
      };
      await poll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "标签任务启动失败");
      setBusy(false);
    }
  }

  async function startHistoryBackfill() {
    setBusy(true);
    try {
      const result = await api.startHistoryBackfill();
      setMessage(
        `历史补全任务 ${result.taskId.slice(0, 8)} 已启动：候选 ${result.total} 只`,
      );
      const poll = async () => {
        const task = await api.historyBackfillTask(result.taskId);
        showTask("历史补全", result.taskId, task);
        const current = task.currentSecurity
          ? ` · 当前 ${task.currentSecurity}`
          : "";
        const speed = task.speed
          ? ` · ${task.speed.toFixed(2)} 只/秒 · ETA ${task.etaSeconds ?? "—"} 秒`
          : "";
        setMessage(
          `历史补全 ${task.done}/${task.total} · 已补全 ${task.completed} · 新股 ${task.listingHistoryShort} · 错误 ${task.errors.length}${current}${speed}`,
        );
        if (task.status === "queued" || task.status === "running")
          window.setTimeout(poll, 1000);
        else {
          setBusy(false);
          setMessage(
            `历史补全完成：已补全 ${task.completed} · 新股 ${task.listingHistoryShort} · 错误 ${task.errors.length}；检查错误后，再手动生成 P1 和 P2`,
          );
        }
      };
      await poll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "历史补全启动失败");
      setBusy(false);
    }
  }

  async function startFeatures() {
    setBusy(true);
    try {
      const result = await api.buildFeatures("all");
      setMessage(`P2 特征任务 ${result.taskId.slice(0, 8)} 已启动`);
      const poll = async () => {
        const task = await api.featureTask(result.taskId);
        showTask("P2 特征", result.taskId, task);
        setMessage(
          `P2 特征：${task.done}/${task.total}，已生成 ${task.rows} 行`,
        );
        if (task.status === "queued" || task.status === "running")
          window.setTimeout(poll, 1000);
        else {
          setBusy(false);
          if (task.errors.length)
            setMessage(`特征完成，但有 ${task.errors.length} 个错误`);
          void refreshResearchStatus();
        }
      };
      await poll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "特征任务启动失败");
      setBusy(false);
    }
  }

  async function probeProviders(quick: boolean) {
    setBusy(true);
    setMessage(quick ? "正在快速诊断数据源…" : "正在执行完整上线 Gate…");
    try {
      const result = await api.probeProviders(quick);
      const poll = async () => {
        const task = await api.taskStatus(result.taskId);
        showTask(
          quick ? "数据源快速诊断" : "数据源上线 Gate",
          result.taskId,
          task,
        );
        if (task.status === "queued" || task.status === "running")
          window.setTimeout(poll, 1000);
        else if (
          task.status !== "completed" &&
          task.status !== "completed_with_errors"
        ) {
          setBusy(false);
          setMessage(
            `数据源探测失败：${task.errors.map(taskErrorText).join("；") || task.status}`,
          );
        } else {
          const [latest, latestReadiness] = await Promise.all([
            api.providerGate(),
            api.readiness(),
          ]);
          setProviderGate(latest);
          setReadiness(latestReadiness);
          setBusy(false);
          setMessage(
            quick
              ? "快速诊断完成（正式 Gate 结论保持不变）"
              : latest.report?.passed
                ? "数据源上线 Gate 已通过"
                : `上线 Gate 未通过：${latest.report?.reasons.join("；") || "请查看任务错误"}`,
          );
        }
      };
      await poll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "数据源探测失败");
      setBusy(false);
    }
  }

  async function startScores() {
    setBusy(true);
    try {
      const result = await api.buildScores("all");
      setMessage(`P3 评分任务 ${result.taskId.slice(0, 8)} 已启动`);
      const poll = async () => {
        const task = await api.scoreTask(result.taskId);
        showTask("P3 评分", result.taskId, task);
        setMessage(
          `P3 评分：${task.done}/${task.total}，已生成 ${task.rows} 行`,
        );
        if (task.status === "queued" || task.status === "running")
          window.setTimeout(poll, 1000);
        else {
          setBusy(false);
          if (task.errors.length)
            setMessage(`评分完成，但有 ${task.errors.length} 个错误`);
          void refreshResearchStatus();
        }
      };
      await poll();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "评分任务启动失败");
      setBusy(false);
    }
  }

  async function runValidation() {
    setBusy(true);
    try {
      const result = await api.validateSingleFactor(validationLabel);
      setValidation(result);
      void refreshResearchRunHistory();
      setMessage(`P4 单因子验证：${result.sampleCount} 个成熟样本`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "验证失败");
    } finally {
      setBusy(false);
    }
  }

  async function runCalibration() {
    setBusy(true);
    try {
      const result = await api.calibrateScore(
        calibrationLabel,
        calibrationBuckets,
      );
      setCalibration(result);
      void refreshResearchRunHistory();
      setMessage(`P5 校准：${result.sampleCount} 个成熟样本`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "校准失败");
    } finally {
      setBusy(false);
    }
  }

  async function runScan() {
    setBusy(true);
    try {
      const result = await api.scanP3(
        scanMinScore,
        scanExchange || undefined,
        scanAsOfDate,
      );
      setScan(result);
      void refreshResearchRunHistory();
      setMessage(
        `P6 扫描：${result.rows.length} 个高分样本${result.truncated ? "（已达返回上限）" : ""}`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "扫描失败");
    } finally {
      setBusy(false);
    }
  }

  async function runBaseline() {
    setBusy(true);
    try {
      const result = await api.trainBaseline(baselineTrainUntil, baselineLabel);
      setBaseline(result);
      void refreshResearchRunHistory();
      setMessage(`P7 基线模型：${researchStatusName(result.status)}`);
      void api
        .modelRegistry()
        .then(setModelRegistry)
        .catch(() => undefined);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "模型训练失败");
    } finally {
      setBusy(false);
    }
  }

  async function checkFeatureCatalog() {
    setBusy(true);
    try {
      const result = await api.featureCatalog();
      setFeatureCatalog(result);
      setMessage(`P7 特征门槛：${result.securityCount} 只证券`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "特征检查失败");
    } finally {
      setBusy(false);
    }
  }

  async function runMultifeature() {
    setBusy(true);
    try {
      const result = await api.trainMultifeature(
        baselineTrainUntil,
        baselineLabel,
      );
      setMultifeature(result);
      void refreshResearchRunHistory();
      setMessage(`P7 多特征模型：${researchStatusName(result.status)}`);
      void api
        .modelRegistry()
        .then(setModelRegistry)
        .catch(() => undefined);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "多特征训练失败");
    } finally {
      setBusy(false);
    }
  }

  async function runWalkForward() {
    setBusy(true);
    try {
      const result = await api.walkForward(baselineLabel, 3);
      setWalkForward(result);
      void refreshResearchRunHistory();
      setMessage(`P7 walk-forward：${result.folds.length} 折`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "walk-forward 失败");
    } finally {
      setBusy(false);
    }
  }

  async function promoteModel(modelId: string) {
    setBusy(true);
    try {
      const result = await api.promoteModel(modelId);
      const registry = await api.modelRegistry();
      setModelRegistry(registry);
      setMessage(
        `已将${modelKindNames[result.kind] ?? result.kind}设为当前模型`,
      );
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "设置当前模型失败");
    } finally {
      setBusy(false);
    }
  }

  async function runDriftMonitor() {
    setBusy(true);
    try {
      const result = await api.runDriftMonitor(
        driftRecentDays,
        driftReferenceDays,
      );
      setDriftReport(result);
      void refreshResearchRunHistory();
      const status =
        result.status === "stable"
          ? "稳定"
          : result.status === "watch"
            ? "需要观察"
            : result.status === "drift"
              ? "发现漂移"
              : "数据不足";
      setMessage(`特征漂移监控：${status}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "漂移监控失败");
    } finally {
      setBusy(false);
    }
  }

  function exportMultifeature() {
    if (!multifeature) return;
    const csv = [
      "version,labelColumn,status,trainCount,testCount,accuracy,auc,feature,weight,warnings",
      ...Object.entries(multifeature.weights).map(([feature, weight]) =>
        [
          multifeature.version,
          multifeature.labelColumn,
          multifeature.status,
          multifeature.trainCount,
          multifeature.testCount,
          multifeature.accuracy ?? "",
          multifeature.auc ?? "",
          feature,
          weight,
          `"${multifeature.warnings.join(";")}"`,
        ].join(","),
      ),
    ].join("\n");
    const url = URL.createObjectURL(
      new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "p7-multifeature-model.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  function exportBaseline() {
    if (!baseline) return;
    const csv = [
      "version,labelColumn,status,trainUntil,trainCount,testCount,positiveRate,testPositiveRate,accuracy,auc,coefficient,warnings",
      [
        baseline.version,
        baseline.labelColumn,
        baseline.status,
        baseline.trainUntil ?? "",
        baseline.trainCount,
        baseline.testCount,
        baseline.positiveRate ?? "",
        baseline.testPositiveRate ?? "",
        baseline.accuracy ?? "",
        baseline.auc ?? "",
        baseline.coefficient ?? "",
        `"${baseline.warnings.join(";")}"`,
      ].join(","),
    ].join("\n");
    const url = URL.createObjectURL(
      new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "p7-baseline-model.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  async function runPortfolio() {
    setBusy(true);
    try {
      const result = await api.validatePortfolio(
        portfolioFraction / 100,
        portfolioLabel,
        portfolioAsOfDate,
        transactionCostBps,
        slippageBps,
      );
      setPortfolio(result);
      void refreshResearchRunHistory();
      setMessage(`P8 组合验证：${result.selectedCount} 个入选样本`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "组合验证失败");
    } finally {
      setBusy(false);
    }
  }

  function exportPortfolio() {
    if (!portfolio) return;
    const csv = [
      "version,labelColumn,topFraction,tradingDayCount,sampleCount,selectedCount,grossReturn,netReturn,benchmarkReturn,netExcessReturn,winRate,maxDrawdown,transactionCostBps,slippageBps,warnings",
      [
        portfolio.version,
        portfolio.labelColumn,
        portfolio.topFraction,
        portfolio.tradingDayCount,
        portfolio.sampleCount,
        portfolio.selectedCount,
        portfolio.averageReturn ?? "",
        portfolio.netAverageReturn ?? "",
        portfolio.benchmarkReturn ?? "",
        portfolio.netExcessReturn ?? "",
        portfolio.winRate ?? "",
        portfolio.maxDrawdown ?? "",
        portfolio.transactionCostBps,
        portfolio.slippageBps,
        `"${portfolio.warnings.join(";")}"`,
      ].join(","),
    ].join("\n");
    const url = URL.createObjectURL(
      new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "p8-portfolio-validation.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  function exportScan() {
    if (!scan?.rows.length) return;
    const csv = [
      "exchange,code,date,score,grade",
      ...scan.rows.map((row) =>
        [row.exchange, row.code, row.date, row.score, row.grade ?? ""].join(
          ",",
        ),
      ),
    ].join("\n");
    const url = URL.createObjectURL(
      new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `p6-scan-${scan.asOfDate ?? "latest"}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function exportTaskErrors() {
    if (!taskView?.errorItems.length) return;
    const csv = [
      "task_id,task_kind,index,error",
      ...taskView.errorItems.map((error, index) =>
        [taskView.id, taskView.kind, index + 1, taskErrorText(error)]
          .map((value) => `"${String(value).replaceAll('"', '""')}"`)
          .join(","),
      ),
    ].join("\n");
    const url = URL.createObjectURL(
      new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `task-errors-${taskView.id.slice(0, 8)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function exportTaskHistory() {
    if (!taskHistory.length) return;
    const csv = [
      "task_id,task_type,status,created_at,updated_at,done,total,rows,error_count,resumable",
      ...taskHistory.map((task) =>
        [
          task.id,
          task.jobType,
          task.status,
          task.createdAt,
          task.updatedAt,
          task.done ?? 0,
          task.total ?? 0,
          task.rows ?? "",
          task.errors?.length ?? 0,
          task.resumable,
        ]
          .map((value) => `"${String(value).replaceAll('"', '""')}"`)
          .join(","),
      ),
    ].join("\n");
    const url = URL.createObjectURL(
      new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `task-history-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function refreshResearchRunHistory(kind = researchKindFilter) {
    try {
      const runs = await api.researchRuns(kind);
      setResearchRuns(runs);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "刷新实验历史失败");
    }
  }

  async function reloadResearchRun(runId: string) {
    try {
      const detail = await api.researchRun(runId);
      const result = detail.result;
      switch (detail.kind) {
        case "p4-single-factor":
          setValidation(result as unknown as SingleFactorValidation);
          break;
        case "p5-calibration":
          setCalibration(result as unknown as ScoreCalibration);
          break;
        case "p6-scan":
          setScan(result as unknown as ScanResult);
          break;
        case "p7-baseline":
          setBaseline(result as unknown as BaselineModel);
          break;
        case "p7-multifeature":
          setMultifeature(result as unknown as MultiFeatureModel);
          break;
        case "p7-walk-forward":
          setWalkForward(result as unknown as WalkForwardResult);
          break;
        case "drift-monitor":
          setDriftReport(result as unknown as DriftReport);
          break;
        case "p8-portfolio":
          setPortfolio(result as unknown as PortfolioValidation);
          break;
      }
      setMessage(`已重新载入实验 ${runId.slice(0, 8)}`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "载入实验失败");
    }
  }

  async function compareSelectedResearchRuns() {
    if (!compareLeft || !compareRight) return;
    try {
      setComparison(await api.compareResearchRuns(compareLeft, compareRight));
      setMessage("实验对比已生成");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "实验对比失败");
    }
  }

  function exportDatasetQuality() {
    if (!datasetQuality) return;
    const payload = JSON.stringify(
      { exportedAt: new Date().toISOString(), report: datasetQuality },
      null,
      2,
    );
    const url = URL.createObjectURL(
      new Blob([payload], { type: "application/json;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `data-quality-${datasetQuality.latestDataDate ?? new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function exportProviderGate() {
    if (!providerGate) return;
    const payload = JSON.stringify(
      { exportedAt: new Date().toISOString(), ...providerGate },
      null,
      2,
    );
    const url = URL.createObjectURL(
      new Blob([payload], { type: "application/json;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `provider-gate-${providerGate.report?.probedAt?.slice(0, 10) ?? "latest"}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function exportResearchReadiness() {
    if (!readiness) return;
    const payload = JSON.stringify(
      { exportedAt: new Date().toISOString(), readiness },
      null,
      2,
    );
    const url = URL.createObjectURL(
      new Blob([payload], { type: "application/json;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `research-readiness-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function loadResearchAcceptance() {
    setBusy(true);
    try {
      const report = await api.researchAcceptance();
      setResearchAcceptance(report);
      setMessage(report.ready ? "研究验收已通过" : `研究验收：${report.blockers.length} 项待完成`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "生成研究验收报告失败");
    } finally {
      setBusy(false);
    }
  }

  function exportResearchAcceptance() {
    if (!researchAcceptance) return;
    const payload = JSON.stringify(researchAcceptance, null, 2);
    const url = URL.createObjectURL(
      new Blob([payload], { type: "application/json;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `research-acceptance-${researchAcceptance.generatedAt.slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function exportCurrentAuditReport() {
    if (!audit || !featureAudit || !scoreAudit) return;
    const payload = JSON.stringify(
      {
        exportedAt: new Date().toISOString(),
        security: { exchange, code },
        signalDate,
        marketData: {
          barCount: bars.length,
          firstDate: bars.at(0)?.date ?? null,
          lastDate: bars.at(-1)?.date ?? null,
        },
        systemVersions: health?.versions ?? {},
        p1: audit,
        p2: featureAudit,
        p3: scoreAudit,
      },
      null,
      2,
    );
    const url = URL.createObjectURL(
      new Blob([payload], { type: "application/json;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = `audit-${exchange}${code}-${signalDate}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  function exportModelRegistry() {
    if (!modelRegistry?.artifacts?.length) return;
    const csv = [
      "model_id,kind,active,promoted_at,created_at,status,label_column,version",
      ...modelRegistry.artifacts.map((artifact) =>
        [
          artifact.modelId,
          artifact.kind,
          artifact.active,
          modelRegistry.activeModels[artifact.kind]?.modelId === artifact.modelId
            ? modelRegistry.activeModels[artifact.kind].promotedAt
            : "",
          artifact.createdAt,
          artifact.status ?? "",
          artifact.labelColumn ?? "",
          artifact.version ?? "",
        ]
          .map((value) => `"${String(value).replaceAll('"', '""')}"`)
          .join(","),
      ),
    ].join("\n");
    const url = URL.createObjectURL(
      new Blob([`\ufeff${csv}`], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = "p7-model-registry.csv";
    link.click();
    URL.revokeObjectURL(url);
  }

  const gateDetailReport = providerGate?.report ?? providerGate?.diagnostic;
  const gateDetailIsDiagnostic =
    !providerGate?.report && Boolean(providerGate?.diagnostic);
  const filteredTaskHistory = taskHistory.filter(
    (task) =>
      (!taskTypeFilter || task.jobType === taskTypeFilter) &&
      (!taskStatusFilter || task.status === taskStatusFilter),
  );

  return (
    <main>
      <header className="workflow-header">
        <div>
          <span className="eyebrow">LOCAL RESEARCH SYSTEM</span>
          <h1>K 线结构概率研究台</h1>
        </div>
        <span className={`health ${health?.status === "ok" ? "ok" : ""}`}>
          {health?.status === "ok" ? "本地服务正常" : "正在连接"}
        </span>
      </header>
      <nav className="workflow-nav" aria-label="研究流程导航">
        <a href="#data-status">数据</a>
        <a href="#p1-auditor">P1 标签</a>
        <a href="#p2-auditor">P2 特征</a>
        <a href="#p3-score">P3 评分</a>
        <a href="#p4-validation">P4 验证</a>
        <a href="#p5-calibration">P5 校准</a>
        <a href="#p6-scanner">P6 扫描</a>
        <a href="#p7-models">P7 模型</a>
        <a href="#drift-monitor">漂移监控</a>
        <a href="#p8-portfolio">P8 组合</a>
        <a href="#research-history">实验历史</a>
      </nav>
      <section id="data-status" className="panel status-panel workflow-status">
        <div className="status-summary">
          <h2>数据状态</h2>
          <p className="muted">
            {health
              ? `${health.dataSource} · 缓存 ${health.cachePath} · ${cachedCount ?? "—"} 只证券 · 近似规则 ${approximateRuleRatio == null ? "—" : `${(approximateRuleRatio * 100).toFixed(2)}%`}`
              : "正在读取配置…"}
          </p>
        </div>
        <div className="status-grid">
          <div className="version">
            <span>标签版本</span>
            <strong>{health?.versions.labelDefinitionVersion ?? "—"}</strong>
          </div>
          <div className="version">
            <span>标签数据兼容</span>
            <strong>
              {labelStatus && Number.isFinite(labelStatus.files)
                ? `${labelStatus.compatibleFiles}/${labelStatus.files}`
                : "—"}
            </strong>
            <small>
              {labelStatus?.unreadableFiles
                ? `${labelStatus.unreadableFiles} 个文件不可读`
                : labelStatus?.staleFiles
                  ? `${labelStatus.staleFiles} 个文件待重建`
                  : labelStatus?.delayedExitReady
                    ? "顺延卖出口径就绪"
                    : "暂无标签数据"}
            </small>
          </div>
          <div className="version">
            <span>可恢复任务</span>
            <strong>{health?.recoverableTasks ?? 0}</strong>
            <small>再次点击对应任务即可续跑</small>
          </div>
          <div className="version">
            <span>交易规则</span>
            <strong>{health?.versions.limitRuleVersion ?? "—"}</strong>
          </div>
          <div className="version">
            <span>复权因子近似</span>
            <strong>
              {datasetQuality?.approximateFactorSecurities ?? "—"}
            </strong>
            <small>
              {datasetQuality?.approximateFactorSecurities
                ? `需审计：${datasetQuality.approximateFactorExamples.slice(0, 3).join("、")}`
                : "未发现近似复权因子"}
            </small>
          </div>
          <div className="version">
            <span>特征版本</span>
            <strong>{health?.versions.featureDefinitionVersion ?? "—"}</strong>
          </div>
          <div className="version">
            <span>评分版本</span>
            <strong>{health?.versions.scoreDefinitionVersion ?? "—"}</strong>
          </div>
          <div className="version">
            <span>P3 评分数据</span>
            <strong>
              {scoreStatus
                ? `${scoreStatus.compatibleFiles}/${scoreStatus.files}`
                : "—"}
            </strong>
            <small>
              {scoreStatus?.unreadableFiles
                ? `${scoreStatus.unreadableFiles} 个文件不可读`
                : scoreStatus?.staleFiles
                  ? `${scoreStatus.staleFiles} 个旧版本文件`
                  : scoreStatus?.ready
                    ? `${scoreStatus.rows} 行就绪`
                    : "暂无评分数据"}
            </small>
          </div>
          <div className="version">
            <span>模型版本</span>
            <strong>{health?.versions.modelDefinitionVersion ?? "—"}</strong>
          </div>
          <div className="version">
            <span>模型注册表</span>
            <strong>{modelRegistry?.artifacts?.length ?? 0}</strong>
            <small>
              {modelRegistry?.unreadableFiles
                ? `${modelRegistry.unreadableFiles} 个模型文件不可读`
                : (modelRegistry?.version ?? "尚无持久化模型")}
            </small>
          </div>
          <div className="version">
            <span>多特征模型</span>
            <strong>
              {health?.versions.multiFeatureModelDefinitionVersion ?? "—"}
            </strong>
          </div>
          <div className="version">
            <span>滚动验证</span>
            <strong>
              {health?.versions.walkForwardModelDefinitionVersion ?? "—"}
            </strong>
          </div>
          <div className="version">
            <span>组合验证版本</span>
            <strong>
              {health?.versions.portfolioValidationVersion ?? "—"}
            </strong>
          </div>
          <div className="version">
            <span>行情策略</span>
            <strong>{health?.versions.providerPolicyVersion ?? "—"}</strong>
          </div>
          <div className="version">
            <span>数据源上线 Gate</span>
            <strong>
              {providerGate?.report
                ? providerGate.report.passed
                  ? "通过"
                  : "未通过"
                : "未执行"}
            </strong>
            <small>
              {providerGate?.report
                ? `${providerGate.report.gateVersion} · ${providerGate.report.probedAt ? new Date(providerGate.report.probedAt).toLocaleString("zh-CN") : "时间未知"}`
                : "完整探测后可作为上线依据"}
            </small>
          </div>
          <div className="version">
            <span>行情新鲜度</span>
            <strong>{datasetQuality?.latestDataDate ?? "暂无数据"}</strong>
            <small>
              {datasetQuality
                ? `覆盖 ${((datasetQuality.freshnessCoverage ?? 0) * 100).toFixed(1)}% · 新鲜 ${datasetQuality.freshSecurities} · 过期 ${datasetQuality.staleSecurities} · 不可读 ${datasetQuality.unreadableSecurities}`
                : "正在统计覆盖日期"}
            </small>
          </div>
          <div className="version">
            <span>研究运行 Gate</span>
            <strong>
              {readiness?.readyForModel
                ? "模型就绪"
                : readiness?.readyForAudit
                  ? "仅审计就绪"
                  : "未就绪"}
            </strong>
            <small>
              {readiness?.blockers?.length
                ? readiness.blockers.slice(0, 3).join("；")
                : readiness?.readyForModel
                  ? `${readiness.version} · 行情覆盖达到 ${((readiness.freshnessMinCoverage ?? 0) * 100).toFixed(0)}% 门槛`
                  : "正在检查运行条件"}
            </small>
          </div>
        </div>
        {gateDetailReport && (
          <details className="gate-details">
            <summary>
              <span>
                {gateDetailIsDiagnostic
                  ? "数据源快速诊断明细"
                  : "数据源上线 Gate 明细"}
              </span>
              <strong>{gateDetailReport.passed ? "通过" : "未通过"}</strong>
            </summary>
            <div className="gate-checks">
              {Object.entries({
                ...(gateDetailReport.requiredChecks ?? {}),
                ...(gateDetailReport.diagnosticChecks ?? {}),
              }).map(([name, passed]) => (
                <span className={passed ? "passed" : "failed"} key={name}>
                  {passed ? "✓" : "×"} {providerCheckNames[name] ?? name}
                </span>
              ))}
            </div>
            {gateDetailReport.providers && (
              <div className="gate-table-wrap">
                <table className="gate-table">
                  <thead>
                    <tr>
                      <th>数据源</th>
                      <th>成功</th>
                      <th>成功率</th>
                      <th>平均延迟</th>
                      <th>P95 延迟</th>
                      <th>空响应</th>
                      <th>缺失字段</th>
                      <th>错误分类</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(gateDetailReport.providers).map(
                      ([name, metric]) => (
                        <tr key={name}>
                          <td>{providerNames[name] ?? name}</td>
                          <td>
                            {metric.successes}/{metric.observations}
                          </td>
                          <td>{pct(metric.success_rate)}</td>
                          <td>{metric.mean_latency_seconds.toFixed(2)} 秒</td>
                          <td>{metric.p95_latency_seconds.toFixed(2)} 秒</td>
                          <td>{metric.empty_response_count}</td>
                          <td>{metric.missing_field_count}</td>
                          <td>
                            {Object.entries(metric.error_categories ?? {})
                              .map(([kind, count]) => `${kind} ${count}`)
                              .join("；") || "无"}
                          </td>
                        </tr>
                      ),
                    )}
                  </tbody>
                </table>
              </div>
            )}
            {(gateDetailReport.reasons?.length > 0 ||
              (gateDetailReport.warnings?.length ?? 0) > 0) && (
              <ul className="gate-messages">
                {gateDetailReport.reasons?.map((reason) => (
                  <li className="failed" key={`reason-${reason}`}>
                    阻断：{reason}
                  </li>
                ))}
                {gateDetailReport.warnings?.map((warning) => (
                  <li key={`warning-${warning}`}>警告：{warning}</li>
                ))}
              </ul>
            )}
            <button
              className="secondary gate-export"
              onClick={exportProviderGate}
            >
              导出 Gate 完整报告 JSON
            </button>
          </details>
        )}
        {readiness && (
          <details className="gate-details readiness-details">
            <summary>
              <span>研究运行 Gate 明细</span>
              <strong>
                {readiness.readyForModel
                  ? "模型就绪"
                  : readiness.readyForAudit
                    ? "仅审计就绪"
                    : "未就绪"}
              </strong>
            </summary>
            <div className="readiness-summary">
              <article>
                <span>行情新鲜覆盖</span>
                <strong>{pct(readiness.freshnessCoverage)}</strong>
                <small>最低要求 {pct(readiness.freshnessMinCoverage)}</small>
              </article>
              <article>
                <span>数据源 Gate 年龄</span>
                <strong>
                  {readiness.providerGateAgeHours == null
                    ? "—"
                    : `${readiness.providerGateAgeHours.toFixed(1)} 小时`}
                </strong>
                <small>最长 {readiness.providerGateMaxAgeHours} 小时</small>
              </article>
            </div>
            <div className="gate-checks readiness-checks">
              {Object.entries(readiness.checks ?? {}).map(([name, passed]) => (
                <span className={passed ? "passed" : "failed"} key={name}>
                  {passed ? "✓" : "×"} {readinessCheckNames[name] ?? name}
                </span>
              ))}
            </div>
            {(readiness.blockers?.length ?? 0) > 0 && (
              <ul className="gate-messages readiness-blockers">
                {readiness.blockers.map((blocker) => (
                  <li className="failed" key={blocker}>
                    阻断：{blocker}
                  </li>
                ))}
              </ul>
            )}
            <button
              className="secondary gate-export"
              onClick={exportResearchReadiness}
            >
              导出研究 Gate 报告 JSON
            </button>
            <button
              className="secondary gate-export"
              disabled={busy}
              onClick={loadResearchAcceptance}
            >
              生成完整研究验收报告
            </button>
          </details>
        )}
        {researchAcceptance && (
          <details className="gate-details acceptance-details" open>
            <summary>
              <span>研究验收报告</span>
              <strong>{researchAcceptance.ready ? "通过" : "待完善"}</strong>
            </summary>
            <div className="readiness-summary">
              <article>
                <span>正式实验</span>
                <strong>
                  {researchAcceptance.experiments.requiredKinds.length -
                    researchAcceptance.experiments.missingKinds.length}
                  /{researchAcceptance.experiments.requiredKinds.length}
                </strong>
                <small>
                  永久记录 {researchAcceptance.experiments.totalPermanentRuns} 次
                </small>
              </article>
              <article>
                <span>注册 / 训练模型</span>
                <strong>
                  {researchAcceptance.models.registered} / {researchAcceptance.models.trained}
                </strong>
                <small>
                  当前模型 {Object.keys(researchAcceptance.models.activeModels).length} 个
                </small>
              </article>
              <article>
                <span>行情覆盖</span>
                <strong>{pct(researchAcceptance.data.freshnessCoverage)}</strong>
                <small>
                  过期 {researchAcceptance.data.staleSecurities} · 身份错配{" "}
                  {researchAcceptance.data.identityMismatchSecurities}
                </small>
              </article>
            </div>
            {researchAcceptance.experiments.missingKinds.length > 0 && (
              <p className="muted">
                缺少实验：
                {researchAcceptance.experiments.missingKinds
                  .map((kind) => researchKindNames[kind] ?? kind)
                  .join("、")}
              </p>
            )}
            {researchAcceptance.blockers.length > 0 && (
              <ul className="gate-messages readiness-blockers">
                {researchAcceptance.blockers.map((blocker) => (
                  <li className="failed" key={blocker}>阻断：{blocker}</li>
                ))}
              </ul>
            )}
            <button className="secondary gate-export" onClick={exportResearchAcceptance}>
              导出研究验收报告 JSON
            </button>
          </details>
        )}
        <details className="quality-details">
          <summary>
            <span>数据质量明细</span>
            <strong>
              {datasetQuality
                ? (datasetQuality.staleSecurities ?? 0) +
                  (datasetQuality.unreadableSecurities ?? 0) +
                  (datasetQuality.approximateFactorSecurities ?? 0) +
                  (datasetQuality.identityMismatchSecurities ?? 0) +
                  (datasetQuality.historyBackfillFailed ?? 0)
                : "—"}
            </strong>
          </summary>
          {datasetQuality ? (
            <>
              <div className="quality-grid">
                <article>
                  <span>过期行情</span>
                  <strong>{datasetQuality.staleSecurities ?? 0}</strong>
                  <small>
                    {datasetQuality.staleExamples
                      ?.slice(0, 5)
                      .map((item) => `${item.security}(${item.latestDate})`)
                      .join("、") || "无"}
                  </small>
                </article>
                <article>
                  <span>不可读文件</span>
                  <strong>{datasetQuality.unreadableSecurities ?? 0}</strong>
                  <small>
                    {datasetQuality.unreadableExamples
                      ?.slice(0, 5)
                      .join("；") || "无"}
                  </small>
                </article>
                <article>
                  <span>近似复权</span>
                  <strong>
                    {datasetQuality.approximateFactorSecurities ?? 0}
                  </strong>
                  <small>
                    {datasetQuality.approximateFactorExamples
                      ?.slice(0, 5)
                      .join("、") || "无"}
                  </small>
                </article>
                <article>
                  <span>短历史 / 补全失败</span>
                  <strong>
                    {datasetQuality.shortHistoryCached ?? 0} /{" "}
                    {datasetQuality.historyBackfillFailed ?? 0}
                  </strong>
                  <small>
                    上市历史不足 {datasetQuality.listingHistoryShort ?? 0}
                  </small>
                </article>
                <article>
                  <span>交易所/代码错配</span>
                  <strong>{datasetQuality.identityMismatchSecurities ?? 0}</strong>
                  <small>
                    {datasetQuality.identityMismatchExamples
                      ?.slice(0, 5)
                      .join("、") || "无"}
                  </small>
                </article>
                <article className="quality-events-card">
                  <span>最近质量事件</span>
                  <strong>{datasetQuality.qualityEvents?.length ?? 0}</strong>
                  <small>
                    {datasetQuality.qualityEvents
                      ?.slice(0, 5)
                      .map(
                        (event) => `${event.dataset_key}：${event.event_type}`,
                      )
                      .join("；") || "无质量事件"}
                  </small>
                </article>
              </div>
              {datasetQuality.qualityEvents?.length > 0 && (
                <ul className="quality-event-list">
                  {datasetQuality.qualityEvents.map((event, index) => (
                    <li
                      key={`${event.dataset_key}-${event.created_at}-${index}`}
                    >
                      <strong>{event.dataset_key}</strong>
                      <span>
                        {event.event_type} · {event.severity}
                        {event.created_at
                          ? ` · ${new Date(event.created_at).toLocaleString("zh-CN")}`
                          : ""}
                      </span>
                      <small>{event.message || "无补充说明"}</small>
                    </li>
                  ))}
                </ul>
              )}
              <button
                className="secondary quality-export"
                onClick={exportDatasetQuality}
              >
                导出完整质量报告 JSON
              </button>
            </>
          ) : (
            <p className="muted">正在读取质量报告…</p>
          )}
        </details>
        <details className="quality-details coverage-details">
          <summary>
            <span>全市场覆盖台账</span>
            <strong>
              {coverage?.report
                ? `${pct(coverage.report.coverageRate)} · ${coverage.report.readyCount}/${coverage.report.universeSize}`
                : "未生成"}
            </strong>
          </summary>
          <div className="coverage-toolbar">
            <label>
              查看状态
              <select
                value={coverageStatus}
                onChange={(event) => {
                  const value = event.target.value;
                  setCoverageStatus(value);
                  void api.coverage(value).then(setCoverage);
                }}
              >
                <option value="">全部状态</option>
                {Object.entries(coverageStatusNames).map(([value, label]) => (
                  <option value={value} key={value}>{label}</option>
                ))}
              </select>
            </label>
            <button className="secondary" disabled={busy} onClick={rebuildCoverage}>
              重新检查覆盖
            </button>
            <button className="secondary" disabled={busy} onClick={runRepairQueue}>
              修复异常证券
            </button>
            <button className="secondary" disabled={busy} onClick={runIncrementalUpdate}>
              更新今日行情
            </button>
          </div>
          {coverage?.report ? (
            <>
              <div className="quality-grid coverage-summary">
                <article><span>证券总数</span><strong>{coverage.report.universeSize}</strong></article>
                <article><span>已有缓存</span><strong>{coverage.report.cachedCount}</strong></article>
                <article><span>可研究</span><strong>{coverage.report.readyCount}</strong></article>
                <article><span>待修复</span><strong>{coverage.report.repairableCount}</strong></article>
              </div>
              <div className="gate-table-wrap">
                <table className="gate-table coverage-table">
                  <thead><tr><th>证券</th><th>状态</th><th>起止日期</th><th>行数</th><th>缺口</th><th>说明</th></tr></thead>
                  <tbody>
                    {coverage.items.map((item) => (
                      <tr key={item.security}>
                        <td>{item.security} {item.name}</td>
                        <td>{coverageStatusNames[item.status] ?? item.status}</td>
                        <td>{item.firstDate ?? "—"} ～ {item.latestDate ?? "—"}</td>
                        <td>{item.rows}</td>
                        <td>{item.calendarGapCount}</td>
                        <td>{item.reason}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <small className="muted">当前筛选共 {coverage.total} 只，表格最多显示前 100 只。</small>
            </>
          ) : (
            <p className="muted">首次使用请点击“重新检查覆盖”，系统会生成可追溯台账。</p>
          )}
        </details>
        <details className="quality-details maintenance-details">
          <summary>
            <span>自动维护与备份</span>
            <strong>{maintenance?.enabled ? "自动更新已开启" : "自动更新未开启"}</strong>
          </summary>
          <div className="quality-grid">
            <article>
              <span>下次自动更新</span>
              <strong>{maintenance?.nextRunAt ? new Date(maintenance.nextRunAt).toLocaleString("zh-CN") : "—"}</strong>
              <small>工作日 {String(maintenance?.hour ?? 18).padStart(2, "0")}:{String(maintenance?.minute ?? 30).padStart(2, "0")}</small>
            </article>
            <article>
              <span>最近自动任务</span>
              <strong>{maintenance?.lastOutcome === "submitted" ? "已提交" : maintenance?.lastOutcome === "skipped" ? "已跳过" : "尚未执行"}</strong>
              <small>{maintenance?.lastError || maintenance?.lastAttemptAt || "无记录"}</small>
            </article>
            <article>
              <span>可用备份</span>
              <strong>{backups?.items?.length ?? 0}</strong>
              <small>{backups?.items?.[0]?.createdAt ? `最新 ${new Date(backups.items[0].createdAt).toLocaleString("zh-CN")}` : "尚无备份"}</small>
            </article>
          </div>
          <div className="status-actions">
            <button className="secondary" onClick={toggleMaintenanceSchedule}>
              {maintenance?.enabled ? "关闭自动更新" : "开启自动更新"}
            </button>
            <button className="secondary" disabled={busy} onClick={createBackup}>立即备份并校验</button>
          </div>
          <p className="muted">恢复操作需先停止服务，并使用服务器恢复命令，避免运行中的数据库被替换。</p>
        </details>
        <div className="status-actions">
          <button
            className="secondary"
            disabled={busy}
            onClick={() => probeProviders(true)}
          >
            快速诊断数据源
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => probeProviders(false)}
          >
            执行数据源上线 Gate
          </button>
          <button disabled={busy} onClick={() => startImport("representative")}>
            拉取代表样本
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => startImport("all")}
          >
            高速下载全市场
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => startImport("failed")}
          >
            重试下载错误
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={startHistoryBackfill}
          >
            补全短历史
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => startLabels("all")}
          >
            生成 P1 标签
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => startLabels("failed")}
          >
            重试 P1 错误
          </button>
          <button className="secondary" disabled={busy} onClick={startFeatures}>
            生成 P2 特征
          </button>
          <button className="secondary" disabled={busy} onClick={startScores}>
            生成 P3 评分
          </button>
          <button className="secondary" disabled={busy} onClick={runValidation}>
            验证 P4 单因子
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={runCalibration}
          >
            运行 P5 概率校准
          </button>
          <button className="secondary" disabled={busy} onClick={runScan}>
            扫描 P6 高分样本
          </button>
          <button
            className="secondary"
            disabled={busy || readiness?.readyForModel === false}
            onClick={runBaseline}
          >
            训练 P7 基线模型
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={checkFeatureCatalog}
          >
            检查 P2 特征覆盖
          </button>
          <button
            className="secondary"
            disabled={busy || !featureCatalog?.ready}
            onClick={runMultifeature}
          >
            训练 P7 多特征模型
          </button>
          <button
            className="secondary"
            disabled={busy || readiness?.readyForModel === false}
            onClick={runWalkForward}
          >
            运行 P7 Walk-forward
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={runDriftMonitor}
          >
            检查特征漂移
          </button>
          <button
            className="secondary"
            disabled={busy || readiness?.readyForModel === false}
            onClick={runPortfolio}
          >
            验证 P8 高分组合
          </button>
        </div>
      </section>
      {taskView && (
        <section
          id="task-progress"
          className="panel task-panel workflow-task"
          aria-label="任务进度"
        >
          <div className="section-title">
            <div>
              <span className="eyebrow">BACKGROUND TASK</span>
              <h2>{taskView.kind}</h2>
            </div>
            <span className="message">{taskStatusName(taskView.status)}</span>
          </div>
          <progress max={Math.max(1, taskView.total)} value={taskView.done} />
          <div className="task-facts">
            <strong>
              {taskView.done} / {taskView.total}
            </strong>
            <span>任务 ID {taskView.id}</span>
            {taskView.createdAt && (
              <span>
                创建 {new Date(taskView.createdAt).toLocaleString("zh-CN")}
              </span>
            )}
            {taskView.updatedAt && (
              <span>
                更新 {new Date(taskView.updatedAt).toLocaleString("zh-CN")}
              </span>
            )}
            {taskElapsedTime(taskView.createdAt, taskView.updatedAt) && (
              <span>
                历时 {taskElapsedTime(taskView.createdAt, taskView.updatedAt)}
              </span>
            )}
            {taskView.resumable && <span>支持中断续跑</span>}
            {taskView.rows != null && <span>生成 {taskView.rows} 行</span>}
            {taskView.current && <span>当前 {taskView.current}</span>}
            {taskView.speed ? (
              <span>
                {taskView.speed.toFixed(2)} 只/秒 · ETA{" "}
                {taskView.etaSeconds ?? "—"} 秒
              </span>
            ) : null}
            <span>错误 {taskView.errors}</span>
          </div>
          {taskView.errorItems.length > 0 && (
            <details className="task-error-details">
              <summary>查看全部 {taskView.errorItems.length} 条错误</summary>
              <button className="secondary" onClick={exportTaskErrors}>
                导出错误 CSV
              </button>
              <ul className="task-errors">
                {taskView.errorItems.map((error, index) => (
                  <li key={index}>{taskErrorText(error)}</li>
                ))}
              </ul>
            </details>
          )}
        </section>
      )}
      {taskHistory.length > 0 && (
        <section className="panel workflow-task-history">
          <div className="section-title">
            <div>
              <span className="eyebrow">TASK HISTORY</span>
              <h2>最近任务历史</h2>
            </div>
            <span className="message">
              显示 {filteredTaskHistory.length} / {taskHistory.length} 条
            </span>
          </div>
          <div className="task-history-controls">
            <label>
              任务类型
              <select
                aria-label="筛选任务类型"
                value={taskTypeFilter}
                onChange={(event) => setTaskTypeFilter(event.target.value)}
              >
                <option value="">全部类型</option>
                {Object.entries(taskKindNames).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              任务状态
              <select
                aria-label="筛选任务状态"
                value={taskStatusFilter}
                onChange={(event) => setTaskStatusFilter(event.target.value)}
              >
                <option value="">全部状态</option>
                {Object.entries(taskStatusNames).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="secondary"
              type="button"
              onClick={() => void refreshTaskHistory()}
            >
              刷新任务历史
            </button>
            <button
              className="secondary"
              type="button"
              onClick={exportTaskHistory}
            >
              导出任务历史 CSV
            </button>
          </div>
          <table className="task-history-table">
            <thead>
              <tr>
                <th>开始时间</th>
                <th>任务类型</th>
                <th>状态</th>
                <th>进度</th>
                <th>错误</th>
                <th>任务 ID</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredTaskHistory.map((task) => (
                <tr key={task.id}>
                  <td>
                    {task.createdAt
                      ? new Date(task.createdAt).toLocaleString("zh-CN")
                      : "—"}
                  </td>
                  <td>{taskKindNames[task.jobType] ?? task.jobType}</td>
                  <td>{taskStatusName(task.status)}</td>
                  <td>
                    {task.done ?? 0}/{task.total ?? 0}
                  </td>
                  <td>{task.errors?.length ?? 0}</td>
                  <td title={task.id}>{task.id}</td>
                  <td>
                    <div className="task-row-actions">
                      <button
                        className="link-button"
                        aria-label={`查看任务 ${task.id}`}
                        onClick={() => inspectTask(task)}
                      >
                        查看
                      </button>
                      {task.status === "interrupted" && task.resumable && (
                        <button
                          className="link-button resume-link"
                          aria-label={`续跑任务 ${task.id}`}
                          disabled={busy}
                          onClick={() => resumeHistoricalTask(task)}
                        >
                          续跑
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!filteredTaskHistory.length && (
            <p className="muted">当前筛选条件下没有任务。</p>
          )}
        </section>
      )}
      <section className="panel workflow-p7-walk">
        <div className="section-title">
          <div>
            <span className="eyebrow">P7 WALK-FORWARD</span>
            <h2>P7 多窗口验证</h2>
          </div>
          {walkForward && (
            <span className="message">{walkForward.version}</span>
          )}
        </div>
        {walkForward ? (
          <div className="validation-panel">
            <article>
              <span>平均 AUC</span>
              <strong>
                {walkForward.averageAuc == null
                  ? "—"
                  : walkForward.averageAuc.toFixed(3)}
              </strong>
              <small>
                平均准确率{" "}
                {walkForward.averageAccuracy == null
                  ? "—"
                  : `${(walkForward.averageAccuracy * 100).toFixed(1)}%`}
              </small>
            </article>
            <table>
              <thead>
                <tr>
                  <th>训练截止</th>
                  <th>测试截止</th>
                  <th>状态</th>
                  <th>训练</th>
                  <th>测试</th>
                  <th>AUC</th>
                  <th>准确率</th>
                </tr>
              </thead>
              <tbody>
                {walkForward.folds.map((fold) => (
                  <tr key={fold.trainUntil}>
                    <td>{fold.trainUntil}</td>
                    <td>{fold.testUntil}</td>
                    <td>{researchStatusName(fold.status)}</td>
                    <td>{fold.trainCount}</td>
                    <td>{fold.testCount}</td>
                    <td>{fold.auc == null ? "—" : fold.auc.toFixed(3)}</td>
                    <td>
                      {fold.accuracy == null
                        ? "—"
                        : `${(fold.accuracy * 100).toFixed(1)}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">
            使用多个训练截止日期滚动验证 P3 分数的样本外稳定性。
          </p>
        )}
      </section>
      <section className="panel workflow-p7-registry">
        <div className="section-title">
          <div>
            <span className="eyebrow">P7 MODEL REGISTRY</span>
            <h2>P7 模型注册表</h2>
          </div>
          {modelRegistry?.artifacts?.length ? (
            <button className="secondary" onClick={exportModelRegistry}>
              导出注册表 CSV
            </button>
          ) : null}
        </div>
        {modelRegistry?.artifacts?.length ? (
          <table className="model-registry-table">
            <thead>
              <tr>
                <th>模型类型</th>
                <th>使用状态</th>
                <th>创建时间</th>
                <th>状态</th>
                <th>标签口径</th>
                <th>模型版本</th>
                <th>模型 ID</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {modelRegistry.artifacts.map((artifact) => (
                <tr key={artifact.modelId}>
                  <td>{modelKindNames[artifact.kind] ?? artifact.kind}</td>
                  <td>
                    {artifact.active ? (
                      <span className="active-model-badge">当前模型</span>
                    ) : (
                      "候选"
                    )}
                  </td>
                  <td>
                    {new Date(artifact.createdAt).toLocaleString("zh-CN")}
                  </td>
                  <td>{researchStatusName(artifact.status)}</td>
                  <td>{resultLabelName(artifact.labelColumn)}</td>
                  <td>{artifact.version ?? "—"}</td>
                  <td title={artifact.modelId}>{artifact.modelId}</td>
                  <td>
                    <button
                      className="secondary compact-action"
                      disabled={busy || artifact.active || artifact.status !== "trained"}
                      onClick={() => promoteModel(artifact.modelId)}
                      title={
                        artifact.status !== "trained"
                          ? "只有训练通过的模型可以启用"
                          : artifact.active
                            ? "该模型已在使用"
                            : "将同类型的当前模型切换为此模型"
                      }
                    >
                      {artifact.active ? "使用中" : "设为当前"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">
            完成 P7 模型训练后，模型产物会在这里登记并可追溯。
          </p>
        )}
      </section>
      <section className="panel workflow-p7-multi">
        <div className="section-title">
          <div>
            <span className="eyebrow">P7 MULTI-FEATURE</span>
            <h2>P7 多特征基线</h2>
          </div>
          {multifeature && (
            <span className="message">{multifeature.version}</span>
          )}
        </div>
        {multifeature ? (
          <div className="validation-panel">
            <article>
              <span>训练 / 测试样本</span>
              <strong>
                {multifeature.trainCount} / {multifeature.testCount}
              </strong>
              <small>
                状态 {researchStatusName(multifeature.status)} · AUC{" "}
                {multifeature.auc == null ? "—" : multifeature.auc.toFixed(3)}
                {` · ${resultLabelName(multifeature.labelColumn)}`}
                {multifeature.isolation ? ` · 隔离 ${multifeature.isolation.embargoDays} 天` : ""}
              </small>
            </article>
            <article>
              <span>测试准确率</span>
              <strong>
                {multifeature.accuracy == null
                  ? "—"
                  : `${(multifeature.accuracy * 100).toFixed(1)}%`}
              </strong>
              <small>
                {multifeature.warnings.join("；") || "可用于基线比较"}
              </small>
            </article>
            <article>
              <span>特征权重</span>
              <strong>{Object.keys(multifeature.weights).length}</strong>
              <small>
                {Object.entries(multifeature.weights)
                  .map(
                    ([key, value]) =>
                      `${featureNames[key] ?? key}:${value.toFixed(2)}`,
                  )
                  .join(" · ") || "暂无权重"}
              </small>
            </article>
            <button className="secondary" onClick={exportMultifeature}>
              导出 CSV
            </button>
          </div>
        ) : (
          <p className="muted">
            通过 P7 特征 ready gate 后，训练 P2/P3 多特征基线模型。
          </p>
        )}
      </section>
      <section id="drift-monitor" className="panel workflow-drift">
        <div className="section-title">
          <div>
            <span className="eyebrow">DRIFT MONITOR</span>
            <h2>特征与评分漂移监控</h2>
          </div>
          {driftReport && (
            <span className={`drift-badge ${driftReport.status}`}>
              {driftReport.status === "stable"
                ? "稳定"
                : driftReport.status === "watch"
                  ? "需要观察"
                  : driftReport.status === "drift"
                    ? "发现漂移"
                    : "数据不足"}
            </span>
          )}
        </div>
        <div className="calibration-controls">
          <label>
            近期窗口
            <input
              type="number"
              min="10"
              max="250"
              value={driftRecentDays}
              onChange={(event) =>
                setDriftRecentDays(Number(event.target.value) || 60)
              }
            />
            个交易日
          </label>
          <label>
            基准窗口
            <input
              type="number"
              min="30"
              max="1000"
              value={driftReferenceDays}
              onChange={(event) =>
                setDriftReferenceDays(Number(event.target.value) || 250)
              }
            />
            个交易日
          </label>
          <button disabled={busy} onClick={runDriftMonitor}>
            开始检查
          </button>
        </div>
        {driftReport?.metrics.length ? (
          <div className="drift-results">
            <p className="muted">
              基准 {driftReport.referenceWindow?.startDate} 至{" "}
              {driftReport.referenceWindow?.endDate}（
              {driftReport.referenceWindow?.rows} 行）· 近期{" "}
              {driftReport.recentWindow?.startDate} 至{" "}
              {driftReport.recentWindow?.endDate}（
              {driftReport.recentWindow?.rows} 行）
            </p>
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>监控项目</th>
                    <th>状态</th>
                    <th>PSI</th>
                    <th>标准化均值偏移</th>
                    <th>缺失率变化</th>
                    <th>基准 / 近期样本</th>
                  </tr>
                </thead>
                <tbody>
                  {driftReport.metrics.map((metric) => (
                    <tr key={metric.column}>
                      <td>{featureNames[metric.column] ?? metric.column}</td>
                      <td>{
                        metric.status === "stable"
                          ? "稳定"
                          : metric.status === "watch"
                            ? "观察"
                            : "漂移"
                      }</td>
                      <td>
                        {metric.populationStabilityIndex == null
                          ? "—"
                          : metric.populationStabilityIndex.toFixed(3)}
                      </td>
                      <td>
                        {metric.standardizedMeanShift == null
                          ? "—"
                          : metric.standardizedMeanShift.toFixed(3)}
                      </td>
                      <td>{pct(metric.missingRateDelta)}</td>
                      <td>
                        {metric.referenceCount} / {metric.recentCount}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted">
              分市场：{driftReport.segments
                .map(
                  (segment) =>
                    `${segment.exchange === "sh" ? "上海" : "深圳"} ${segment.status === "stable" ? "稳定" : segment.status === "watch" ? "观察" : "漂移"}`,
                )
                .join(" · ") || "暂无分市场样本"}
            </p>
          </div>
        ) : (
          <p className="muted">
            对比近期窗口与历史基准窗口，检查 P3 评分和核心 P2 特征的分布、均值与缺失率变化。每次结果都会写入实验历史。
          </p>
        )}
      </section>
      <section id="p8-portfolio" className="panel workflow-p8">
        <div className="section-title">
          <div>
            <span className="eyebrow">P8 VALIDATION</span>
            <h2>P8 高分组合验证</h2>
          </div>
          {portfolio && <span className="message">{portfolio.version}</span>}
        </div>
        <div className="calibration-controls">
          <label>
            选取比例
            <input
              type="number"
              min="1"
              max="50"
              value={portfolioFraction}
              onChange={(e) =>
                setPortfolioFraction(
                  Math.max(1, Math.min(50, Number(e.target.value) || 10)),
                )
              }
            />
            %
          </label>
          <label>
            结果口径
            <select
              value={portfolioLabel}
              onChange={(e) => setPortfolioLabel(e.target.value)}
            >
              <ResultLabelOptions />
            </select>
          </label>
          <label>
            截至日期
            <input
              type="date"
              value={portfolioAsOfDate}
              onChange={(e) => setPortfolioAsOfDate(e.target.value)}
            />
          </label>
          <label>
            成本 bps
            <input
              type="number"
              min="0"
              max="1000"
              value={transactionCostBps}
              onChange={(e) =>
                setTransactionCostBps(
                  Math.max(0, Math.min(1000, Number(e.target.value) || 0)),
                )
              }
            />
          </label>
          <label>
            滑点 bps
            <input
              type="number"
              min="0"
              max="1000"
              value={slippageBps}
              onChange={(e) =>
                setSlippageBps(
                  Math.max(0, Math.min(1000, Number(e.target.value) || 0)),
                )
              }
            />
          </label>
          {portfolio ? (
            <button className="secondary" onClick={exportPortfolio}>
              导出 CSV
            </button>
          ) : null}
        </div>
        {portfolio ? (
          <>
            <div className="validation-panel">
              <article>
                <span>净组合 / 全样本收益</span>
                <strong>
                  {pct(portfolio.netAverageReturn)} /{" "}
                  {pct(portfolio.benchmarkReturn)}
                </strong>
                <small>
                  毛收益 {pct(portfolio.averageReturn)} · 成本{" "}
                  {portfolio.transactionCostBps + portfolio.slippageBps} bps ·
                  入选 {portfolio.selectedCount}
                </small>
              </article>
              <article>
                <span>净超额收益</span>
                <strong>{pct(portfolio.netExcessReturn)}</strong>
                <small>
                  胜率 {pct(portfolio.winRate)} · 最大回撤{" "}
                  {pct(portfolio.maxDrawdown)}
                </small>
              </article>
              <article>
                <span>年化收益 / 波动</span>
                <strong>
                  {pct(portfolio.annualizedReturn)} /{" "}
                  {pct(portfolio.annualizedVolatility)}
                </strong>
                <small>
                  Sharpe{" "}
                  {portfolio.sharpeRatio == null
                    ? "—"
                    : portfolio.sharpeRatio.toFixed(3)}{" "}
                  · Calmar{" "}
                  {portfolio.calmarRatio == null
                    ? "—"
                    : portfolio.calmarRatio.toFixed(3)}{" "}
                  · 净值点 {portfolio.equityCurve?.length ?? 0}
                </small>
              </article>
              <article>
                <span>回测口径</span>
                <strong>非重叠</strong>
                <small>
                  {resultLabelName(portfolio.labelColumn)}
                  {portfolio.warnings.length
                    ? ` · ${portfolio.warnings.join("；")}`
                    : ""}
                </small>
              </article>
            </div>
            <EquityCurveChart
              points={portfolio.equityCurve ?? []}
              benchmarkPoints={portfolio.benchmarkEquityCurve ?? []}
            />
          </>
        ) : (
          <p className="muted">
            按每日 P3
            评分最高的指定比例构建研究组合，与所选持有期的全样本收益比较。
          </p>
        )}
      </section>
      <section id="p1-auditor" className="panel workflow-p1">
        <div className="section-title">
          <div>
            <span className="eyebrow">P1 AUDITOR</span>
            <h2>P1 标签审计台</h2>
          </div>
          <span className="message">{message}</span>
        </div>
        <form onSubmit={runAudit}>
          <label>
            交易所
            <select
              value={exchange}
              onChange={(e) => setExchange(e.target.value)}
            >
              <option value="sh">上海</option>
              <option value="sz">深圳</option>
            </select>
          </label>
          <label>
            证券代码或名称
            <input
              aria-label="证券代码"
              list="security-suggestions"
              value={code}
              onChange={(e) => changeSecurityQuery(e.target.value)}
            />
            <datalist id="security-suggestions">
              {securitySuggestions.map((item) => (
                <option key={`${item.exchange}-${item.code}`} value={item.code}>
                  {item.name} · {item.exchange === "sh" ? "上海" : "深圳"}
                </option>
              ))}
            </datalist>
          </label>
          <label>
            信号日
            <input
              type="date"
              value={signalDate}
              onChange={(e) => setSignalDate(e.target.value)}
            />
          </label>
          <button
            type="button"
            className="secondary"
            disabled={busy}
            onClick={chooseLatestMatureSignalDate}
          >
            选择最近 P60 成熟日
          </button>
          <button disabled={busy}>计算并审计</button>
        </form>
        {audit && featureAudit && scoreAudit && (
          <div className="audit-actions">
            <span>当前报告包含 P1 标签、P2 特征、P3 评分及版本依赖</span>
            <button
              type="button"
              className="secondary"
              onClick={exportCurrentAuditReport}
            >
              导出当前审计报告 JSON
            </button>
          </div>
        )}
        {bars.length > 0 && (
          <KlineChart
            bars={bars}
            events={{
              signalDate,
              entryDate: audit?.entry.entry_date,
              plannedExitDate: audit?.labels["20"]?.planned_exit_date,
              actualExitDate: audit?.exits?.["20"]?.exit_date,
              pathHitDate: audit?.path?.hit_date,
              pathFailDate: audit?.path?.fail_date,
              drawdownPeakDate: audit?.drawdown?.peak_date,
              drawdownTroughDate: audit?.drawdown?.hit_date,
            }}
          />
        )}
        {audit && (
          <div className="audit-grid">
            <article>
              <span>样本资格</span>
              <strong>{p1TermName(audit.eligibility.status)}</strong>
              <small>
                {audit.eligibility.reasons.map(p1TermName).join(" · ") ||
                  "检查通过"}
              </small>
            </article>
            <article>
              <span>交易状态</span>
              <strong>
                {audit.securityStatus
                  ? audit.securityStatus.is_st
                    ? "ST"
                    : "普通"
                  : "—"}
              </strong>
              <small>
                {audit.securityStatus?.is_approx
                  ? `近似：${p1TermName(audit.securityStatus.reason)}`
                  : "正式规则"}
              </small>
            </article>
            <article>
              <span>可执行入口</span>
              <strong>{p1TermName(audit.entry.status)}</strong>
              <small>
                {audit.entry.entry_date
                  ? `${audit.entry.entry_date}${audit.entry.entry_price ? ` @ ${audit.entry.entry_price}` : ""} · 顺延 ${audit.entry.entry_delay ?? 0} 日`
                  : audit.entry.entry_reason
                    ? p1TermName(audit.entry.entry_reason)
                    : "无入口"}
              </small>
            </article>
            {([5, 10, 20, 60] as const).map((horizon) => (
              <article key={horizon}>
                <span>P{horizon} 计划 / 顺延卖出</span>
                <strong>
                  {pct(audit.labels[String(horizon)]?.executable_return)} /{" "}
                  {pct(
                    audit.labels[String(horizon)]?.delayed_executable_return,
                  )}
                </strong>
                <small>
                  {audit.exits?.[String(horizon)]
                    ? `${audit.labels[String(horizon)]?.planned_exit_date ?? "无计划卖出日"} → ${audit.exits[String(horizon)].exit_date ?? "无可执行卖出日"} · ${p1TermName(audit.exits[String(horizon)].status)} · 顺延 ${audit.exits[String(horizon)].exit_delay ?? "—"} 日`
                    : "等待卖出审计"}
                </small>
              </article>
            ))}
            <article>
              <span>P20 最大回撤</span>
              <strong>{pct(audit.drawdown?.max_drawdown)}</strong>
              <small>
                {audit.drawdown?.hit_risk ? "触发 8% 风险线" : "未触发风险线"}
              </small>
            </article>
            <article>
              <span>路径标签</span>
              <strong>{audit.path?.success ? "成功" : "失败"}</strong>
              <small>{p1TermName(audit.path?.reason)}</small>
            </article>
            <article>
              <span>标签成熟日</span>
              <strong>{audit.maturityDate ?? "—"}</strong>
              <small>只允许成熟标签进入校准池</small>
            </article>
            <article>
              <span>数据与因子版本</span>
              <strong>{audit.factorVersion?.slice(0, 18) ?? "—"}</strong>
              <small>{audit.dataSnapshotVersion ?? "—"}</small>
            </article>
          </div>
        )}
      </section>
      <section id="p4-validation" className="panel workflow-p4">
        <div className="section-title">
          <div>
            <span className="eyebrow">P4 VALIDATION</span>
            <h2>P4 单因子验证</h2>
          </div>
          {validation && <span className="message">{validation.version}</span>}
        </div>
        <div className="calibration-controls">
          <label>
            结果口径
            <select
              value={validationLabel}
              onChange={(e) => setValidationLabel(e.target.value)}
            >
              <ResultLabelOptions />
            </select>
          </label>
        </div>
        {validation ? (
          <div className="validation-panel">
            <article>
              <span>样本 / 独立时段</span>
              <strong>
                {validation.sampleCount} / {validation.independentPeriodCount}
              </strong>
              <small>
                {resultLabelName(validation.labelColumn)} · 七个自然日两步聚类 ·
                秩相关{" "}
                {validation.rankCorrelation == null
                  ? "—"
                  : validation.rankCorrelation.toFixed(4)}{" "}
                · 95% CI{" "}
                {validation.rankCorrelationInterval
                  ? `${validation.rankCorrelationInterval.lower.toFixed(3)}～${validation.rankCorrelationInterval.upper.toFixed(3)}`
                  : "—"}
              </small>
            </article>
            {validation.stability && (
              <article>
                <span>跨时期稳定性</span>
                <strong>{validation.stability.status === "stable" ? "方向稳定" : "需要复核"}</strong>
                <small>三个时间段 · Benjamini-Hochberg 控制假发现率</small>
              </article>
            )}
            {validation.stability?.periods?.length ? (
              <table>
                <thead><tr><th>时期</th><th>日期</th><th>样本</th><th>秩相关</th><th>p 值</th><th>校正 q 值</th></tr></thead>
                <tbody>{validation.stability.periods.map((period) => <tr key={period.period}><td>{period.period}</td><td>{period.startDate}～{period.endDate}</td><td>{period.sampleCount}</td><td>{period.rankCorrelation?.toFixed(4) ?? "—"}</td><td>{period.pValue?.toFixed(4) ?? "—"}</td><td>{period.qValue?.toFixed(4) ?? "—"}</td></tr>)}</tbody>
              </table>
            ) : null}
            <table>
              <thead>
                <tr>
                  <th>分桶</th>
                  <th>样本</th>
                  <th>平均分</th>
                  <th>所选口径收益</th>
                  <th>收益 95% CI</th>
                  <th>胜率</th>
                  <th>胜率 95% CI</th>
                  <th>路径成功</th>
                </tr>
              </thead>
              <tbody>
                {validation.buckets.map((bucket) => (
                  <tr key={bucket.bucket}>
                    <td>{bucket.bucket}</td>
                    <td>{bucket.count}</td>
                    <td>{bucket.avgFactor.toFixed(2)}</td>
                    <td>{pct(bucket.avgLabel)}</td>
                    <td>{intervalPct(bucket.avgLabelInterval)}</td>
                    <td>{pct(bucket.winRate)}</td>
                    <td>{intervalPct(bucket.winRateInterval)}</td>
                    <td>{pct(bucket.pathSuccessRate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">
            生成 P1 标签和 P3 评分后，可验证 score 对所选收益口径的分桶效果。
          </p>
        )}
      </section>
      <section id="p6-scanner" className="panel workflow-p6">
        <div className="section-title">
          <div>
            <span className="eyebrow">P6 SCANNER</span>
            <h2>P6 高分扫描</h2>
          </div>
          {scan && (
            <span className="message">
              最低分 {scan.minScore} · {scan.scannedCount} 条
            </span>
          )}
        </div>
        <div className="calibration-controls">
          <label>
            市场
            <select
              value={scanExchange}
              onChange={(e) => setScanExchange(e.target.value)}
            >
              <option value="">全部</option>
              <option value="sh">上海</option>
              <option value="sz">深圳</option>
            </select>
          </label>
          <label>
            最低分
            <input
              type="number"
              min="0"
              max="100"
              value={scanMinScore}
              onChange={(e) =>
                setScanMinScore(
                  Math.max(0, Math.min(100, Number(e.target.value) || 0)),
                )
              }
            />
          </label>
          <label>
            截至日期
            <input
              type="date"
              value={scanAsOfDate}
              onChange={(e) => setScanAsOfDate(e.target.value)}
            />
          </label>
          {scan?.rows.length ? (
            <button className="secondary" onClick={exportScan}>
              导出 CSV
            </button>
          ) : null}
        </div>
        {scan ? (
          <table className="scan-table">
            <thead>
              <tr>
                <th>市场</th>
                <th>代码</th>
                <th>评分日期</th>
                <th>分数</th>
                <th>等级</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {scan.rows.map((row) => (
                <tr key={`${row.exchange}-${row.code}`}>
                  <td>{row.exchange === "sh" ? "上海" : "深圳"}</td>
                  <td>{row.code}</td>
                  <td>{row.date}</td>
                  <td>{row.score.toFixed(1)}</td>
                  <td>{row.grade ?? "—"}</td>
                  <td>
                    <button
                      className="link-button"
                      onClick={() => {
                        setExchange(row.exchange);
                        setCode(row.code);
                        setSignalDate(row.date);
                        setMessage(
                          `已带入 ${row.exchange === "sh" ? "上海" : "深圳"} ${row.code}，点击上方审计`,
                        );
                        window.scrollTo({ top: 0, behavior: "smooth" });
                      }}
                    >
                      审计
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">
            扫描每只证券最新可用 P3 评分，默认返回分数不低于 70 的前 50 个样本。
          </p>
        )}
      </section>
      <section id="p5-calibration" className="panel workflow-p5">
        <div className="section-title">
          <div>
            <span className="eyebrow">P5 CALIBRATION</span>
            <h2>P5 概率校准</h2>
          </div>
          {calibration && (
            <span className="message">{calibration.version}</span>
          )}
        </div>
        <div className="calibration-controls">
          <label>
            结果口径
            <select
              value={calibrationLabel}
              onChange={(e) => setCalibrationLabel(e.target.value)}
            >
              <ResultLabelOptions />
            </select>
          </label>
          <label>
            分桶数
            <input
              type="number"
              min="2"
              max="20"
              value={calibrationBuckets}
              onChange={(e) =>
                setCalibrationBuckets(
                  Math.max(2, Math.min(20, Number(e.target.value) || 10)),
                )
              }
            />
          </label>
        </div>
        {calibration ? (
          <div className="validation-panel">
            <article>
              <span>成熟样本</span>
              <strong>{calibration.sampleCount}</strong>
              <small>
                {resultLabelName(calibration.labelColumn)} · 按 P3 分数分桶
              </small>
              <small
                className={
                  calibration.reliability.status === "usable"
                    ? "reliability-ok"
                    : "reliability-review"
                }
              >
                {calibration.reliability.status === "usable"
                  ? "可用于研究"
                  : "需要复核"}
                {calibration.reliability.warnings.length
                  ? ` · ${calibration.reliability.warnings.join("；")}`
                  : ""}
              </small>
            </article>
            <article>
              <span>概率质量</span>
              <strong>
                ECE{" "}
                {calibration.quality?.expectedCalibrationError == null
                  ? "—"
                  : calibration.quality.expectedCalibrationError.toFixed(4)}
              </strong>
              <small>
                Brier{" "}
                {calibration.quality?.brierScore == null
                  ? "—"
                  : calibration.quality.brierScore.toFixed(4)}{" "}
                · Log Loss{" "}
                {calibration.quality?.logLoss == null
                  ? "—"
                  : calibration.quality.logLoss.toFixed(4)}
              </small>
            </article>
            <table>
              <thead>
                <tr>
                  <th>分桶</th>
                  <th>样本</th>
                  <th>平均分</th>
                  <th>观察胜率</th>
                  <th>胜率 95% CI</th>
                  <th>平均收益</th>
                  <th>收益 95% CI</th>
                </tr>
              </thead>
              <tbody>
                {calibration.buckets.map((bucket) => (
                  <tr key={bucket.bucket}>
                    <td>{bucket.bucket}</td>
                    <td>{bucket.count}</td>
                    <td>{bucket.avgScore.toFixed(1)}</td>
                    <td>{pct(bucket.observedProbability)}</td>
                    <td>{intervalPct(bucket.observedProbabilityInterval)}</td>
                    <td>{pct(bucket.avgLabel)}</td>
                    <td>{intervalPct(bucket.avgLabelInterval)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">
            生成 P1 标签和 P3
            评分后，运行概率校准查看分数与所选结果口径的对应关系。
          </p>
        )}
      </section>
      <section className="panel workflow-p7-baseline">
        <div className="section-title">
          <div>
            <span className="eyebrow">P7 BASELINE</span>
            <h2>P7 轻量基线模型</h2>
          </div>
          {baseline && <span className="message">{baseline.version}</span>}
        </div>
        <div className="calibration-controls">
          <label>
            结果口径
            <select
              value={baselineLabel}
              onChange={(e) => setBaselineLabel(e.target.value)}
            >
              <ResultLabelOptions />
            </select>
          </label>
          <label>
            训练截止日期
            <input
              type="date"
              value={baselineTrainUntil}
              onChange={(e) => setBaselineTrainUntil(e.target.value)}
            />
          </label>
          {baseline ? (
            <button className="secondary" onClick={exportBaseline}>
              导出 CSV
            </button>
          ) : null}
        </div>
        {baseline ? (
          <div className="validation-panel">
            <article>
              <span>训练 / 测试样本</span>
              <strong>
                {baseline.trainCount} / {baseline.testCount}
              </strong>
              <small>
                时间切分，标签：{resultLabelName(baseline.labelColumn)}
                {baseline.trainUntil ? ` · 截止 ${baseline.trainUntil}` : ""}
                {baseline.isolation ? ` · 隔离 ${baseline.isolation.embargoDays} 天` : ""}
              </small>
            </article>
            <article>
              <span>测试准确率</span>
              <strong>
                {baseline.accuracy == null
                  ? "—"
                  : `${(baseline.accuracy * 100).toFixed(1)}%`}
              </strong>
              <small>
                ROC AUC {baseline.auc == null ? "—" : baseline.auc.toFixed(3)} ·
                正样本率{" "}
                {baseline.testPositiveRate == null
                  ? "—"
                  : `${(baseline.testPositiveRate * 100).toFixed(1)}%`}
              </small>
            </article>
            <article>
              <span>模型系数</span>
              <strong>
                {baseline.coefficient == null
                  ? "—"
                  : baseline.coefficient.toFixed(4)}
              </strong>
              <small>
                训练正样本率{" "}
                {baseline.positiveRate == null
                  ? "—"
                  : `${(baseline.positiveRate * 100).toFixed(1)}%`}{" "}
                · {baseline.warnings.join("；") || "可用于基线比较"}
              </small>
            </article>
          </div>
        ) : (
          <p className="muted">
            使用 P3 分数预测所选持有期的正收益，按时间切分输出样本外基线指标。
          </p>
        )}
      </section>
      <section id="p3-score" className="panel workflow-p3">
        <div className="section-title">
          <div>
            <span className="eyebrow">P3 SCORE</span>
            <h2>P3 结构评分</h2>
          </div>
          {scoreAudit && (
            <span className="message">{scoreAudit.score.version}</span>
          )}
        </div>
        {scoreAudit ? (
          <div className="score-panel">
            <article
              className={`score-card grade-${scoreAudit.score.grade.toLowerCase()}`}
            >
              <span>结构分数</span>
              <strong>{scoreAudit.score.score.toFixed(1)}</strong>
              <small>
                {scoreAudit.score.grade} ·{" "}
                {scoreAudit.score.usable ? "可用" : "需审计"}{" "}
                {scoreAudit.score.reasons.map(p1TermName).join(" · ")}
              </small>
            </article>
            <div className="score-components">
              {(Object.keys(groupNames) as Array<keyof typeof groupNames>).map(
                (group) => {
                  const item = scoreAudit.score.components[group];
                  return (
                    <article key={group}>
                      <h3>{groupNames[group]}</h3>
                      <strong>
                        {item.score.toFixed(1)} / {item.weight}
                      </strong>
                      <small>
                        {item.reasons.map(p1TermName).join(" · ") ||
                          "无可用特征"}
                      </small>
                    </article>
                  );
                },
              )}
            </div>
          </div>
        ) : (
          <p className="muted">
            执行上方审计后，展示 P2 特征驱动的可解释 P3 分数。
          </p>
        )}
      </section>
      <section id="p7-models" className="panel workflow-p7-gate">
        <div className="section-title">
          <div>
            <span className="eyebrow">P7 FEATURE GATE</span>
            <h2>P7 多特征数据门槛</h2>
          </div>
          {featureCatalog && (
            <span className="message">
              {featureCatalog.ready ? "可进入训练" : "暂不可训练"} ·{" "}
              {featureCatalog.version ?? "状态刷新中"}
            </span>
          )}
        </div>
        {featureCatalog ? (
          <div className="validation-panel">
            <article>
              <span>证券覆盖</span>
              <strong>{featureCatalog.securityCount ?? 0}</strong>
              <small>
                {featureCatalog.rowCount ?? 0} 行特征数据 · 不可读{" "}
                {featureCatalog.unreadableFiles ?? 0}
              </small>
            </article>
            <article>
              <span>可用特征</span>
              <strong>{featureCatalog.featureColumns?.length ?? 0}</strong>
              <small>
                {featureCatalog.featureColumns
                  ?.slice(0, 5)
                  .map((name) => featureNames[name] ?? name)
                  .join("、") || "暂无特征"}
                {featureCatalog.missingColumns?.length
                  ? ` · 缺失 ${featureCatalog.missingColumns.map((name) => featureNames[name] ?? name).join("、")}`
                  : ""}
              </small>
            </article>
          </div>
        ) : (
          <p className="muted">
            检查 P2 特征文件覆盖后，再进入多特征模型训练。
          </p>
        )}
      </section>
      <section id="research-history" className="panel research-history-panel">
        <div className="section-title">
          <div>
            <span className="eyebrow">REPRODUCIBLE RESEARCH</span>
            <h2>研究实验历史</h2>
          </div>
          <span className="message">{researchRuns?.total ?? 0} 次永久记录</span>
        </div>
        <div className="research-history-controls">
          <label>
            实验类型
            <select
              value={researchKindFilter}
              onChange={(event) => {
                const kind = event.target.value;
                setResearchKindFilter(kind);
                void refreshResearchRunHistory(kind);
              }}
            >
              <option value="">全部类型</option>
              {Object.entries(researchKindNames).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          <button className="secondary" onClick={() => void refreshResearchRunHistory()}>
            刷新实验历史
          </button>
        </div>
        {researchRuns?.runs?.length ? (
          <div className="gate-table-wrap">
            <table className="gate-table research-run-table">
              <thead><tr><th>运行时间</th><th>类型</th><th>主要结果</th><th>数据快照</th><th>代码版本</th><th>操作</th></tr></thead>
              <tbody>
                {researchRuns.runs.map((run) => (
                  <tr key={run.runId}>
                    <td>{new Date(run.createdAt).toLocaleString("zh-CN")}</td>
                    <td>{researchKindNames[run.kind] ?? run.kind}</td>
                    <td><code>{JSON.stringify(run.summary)}</code></td>
                    <td title={run.dataSnapshot?.manifestHash}>{run.dataSnapshot?.securityCount ?? 0} 只 · {run.dataSnapshot?.manifestHash?.slice(0, 8) ?? "—"}</td>
                    <td>{run.codeVersion}</td>
                    <td><button className="link-button" onClick={() => void reloadResearchRun(run.runId)}>重新载入</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="muted">运行任意 P4–P8 研究后，系统会在这里永久保存输入参数、数据快照、版本依赖和完整结果。</p>
        )}
        {(researchRuns?.runs?.length ?? 0) >= 2 && (
          <details className="quality-details research-compare">
            <summary><span>对比两个同类实验</span><strong>{comparison ? researchKindNames[comparison.kind] ?? comparison.kind : "未选择"}</strong></summary>
            <div className="research-history-controls">
              <label>左侧实验<select value={compareLeft} onChange={(event) => { setCompareLeft(event.target.value); setCompareRight(""); setComparison(null); }}><option value="">请选择</option>{researchRuns?.runs.map((run) => <option key={run.runId} value={run.runId}>{researchKindNames[run.kind] ?? run.kind} · {new Date(run.createdAt).toLocaleString("zh-CN")}</option>)}</select></label>
              <label>右侧实验<select value={compareRight} onChange={(event) => setCompareRight(event.target.value)}><option value="">请选择</option>{researchRuns?.runs.filter((run) => run.runId !== compareLeft && (!compareLeft || run.kind === researchRuns.runs.find((item) => item.runId === compareLeft)?.kind)).map((run) => <option key={run.runId} value={run.runId}>{new Date(run.createdAt).toLocaleString("zh-CN")}</option>)}</select></label>
              <button className="secondary" disabled={!compareLeft || !compareRight} onClick={() => void compareSelectedResearchRuns()}>生成对比</button>
            </div>
            {comparison && <div className="gate-table-wrap"><table className="gate-table"><thead><tr><th>指标</th><th>左侧</th><th>右侧</th><th>变化</th></tr></thead><tbody>{comparison.metrics.map((metric) => <tr key={metric.metric}><td>{metric.metric}</td><td>{String(metric.left ?? "—")}</td><td>{String(metric.right ?? "—")}</td><td>{metric.delta == null ? "—" : metric.delta.toFixed(6)}</td></tr>)}</tbody></table></div>}
          </details>
        )}
      </section>
      <section id="p2-auditor" className="panel workflow-p2">
        <div className="section-title">
          <div>
            <span className="eyebrow">P2 AUDITOR</span>
            <h2>P2 特征审计</h2>
          </div>
          {featureAudit && (
            <span className="message">
              历史 {featureAudit.availableHistory} 日 ·{" "}
              {priceBasisNames[featureAudit.priceBasis] ??
                featureAudit.priceBasis}
            </span>
          )}
        </div>
        {featureAudit ? (
          <>
            <div className="feature-groups">
              {(Object.keys(groupNames) as Array<keyof typeof groupNames>).map(
                (group) => (
                  <article key={group}>
                    <h3>{groupNames[group]}</h3>
                    <dl>
                      {Object.entries(featureAudit.groups[group]).map(
                        ([key, value]) => (
                          <div key={key}>
                            <dt>{featureNames[key] ?? key}</dt>
                            <dd>{featureValue(value)}</dd>
                          </div>
                        ),
                      )}
                    </dl>
                  </article>
                ),
              )}
            </div>
            <div className="feature-audit-meta">
              <article>
                <span>审计说明</span>
                <strong>
                  {featureAudit.reasons.map(p1TermName).join("；") ||
                    "时点特征计算完成"}
                </strong>
              </article>
              <article>
                <span>版本依赖</span>
                <strong>
                  {Object.entries(featureAudit.versions)
                    .map(
                      ([name, value]) =>
                        `${versionNames[name] ?? name}：${value ?? "缺失"}`,
                    )
                    .join(" · ")}
                </strong>
              </article>
            </div>
          </>
        ) : (
          <p className="muted">
            使用上方证券与日期执行审计后，展示五组时间点特征。
          </p>
        )}
      </section>
    </main>
  );
}
