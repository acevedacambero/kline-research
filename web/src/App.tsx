import { FormEvent, useEffect, useState } from 'react'
import { api, type Audit, type Bar, type FeatureAudit, type FeatureValue, type Health, type LabelStatus, type ScoreAudit, type SingleFactorValidation, type ScoreCalibration, type ScanResult, type BaselineModel, type PortfolioValidation, type FeatureCatalog, type MultiFeatureModel, type WalkForwardResult } from './api'
import { KlineChart } from './KlineChart'
import './styles.css'

const pct = (value?: number | null) => value == null ? '—' : `${(value * 100).toFixed(2)}%`
const groupNames = { trend: '趋势', position: '位置', momentum: '动量', volumePrice: '量价', tradingBehavior: '交易行为' }
const featureNames: Record<string, string> = {
  ma5: 'MA5', ma10: 'MA10', ma20: 'MA20', ma60: 'MA60', bullish_alignment: '多头排列',
  range_position_20: '20 日位置', drawdown_from_high_20: '距 20 日高点', return_20: '20 日动量',
  volume_ratio_5: '5 日量比', volatility_20: '20 日波动', is_limit_up: '当日涨停',
  limit_up_count_20: '20 日涨停数', locked_limit_up_streak: '连续一字板', gap_open: '开盘缺口',
  suspension_gap_days: '停牌间隔',
}
const featureValue = (value: FeatureValue) => value == null ? '历史不足' : typeof value === 'boolean' ? (value ? '是' : '否') : typeof value === 'number' ? value.toFixed(4) : value
const ResultLabelOptions = () => <>
  <option value="p5_executable_return">P5 计划收盘卖出</option>
  <option value="p5_delayed_executable_return">P5 可执行顺延卖出</option>
  <option value="p10_executable_return">P10 计划收盘卖出</option>
  <option value="p10_delayed_executable_return">P10 可执行顺延卖出</option>
  <option value="p20_executable_return">P20 计划收盘卖出</option>
  <option value="p20_delayed_executable_return">P20 可执行顺延卖出</option>
  <option value="p60_executable_return">P60 计划收盘卖出</option>
  <option value="p60_delayed_executable_return">P60 可执行顺延卖出</option>
</>

export function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [labelStatus, setLabelStatus] = useState<LabelStatus | null>(null)
  const [exchange, setExchange] = useState('sh')
  const [code, setCode] = useState('600000')
  const [signalDate, setSignalDate] = useState('2024-01-02')
  const [bars, setBars] = useState<Bar[]>([])
  const [audit, setAudit] = useState<Audit | null>(null)
  const [featureAudit, setFeatureAudit] = useState<FeatureAudit | null>(null)
  const [scoreAudit, setScoreAudit] = useState<ScoreAudit | null>(null)
  const [validation, setValidation] = useState<SingleFactorValidation | null>(null)
  const [validationLabel, setValidationLabel] = useState('p20_executable_return')
  const [calibration, setCalibration] = useState<ScoreCalibration | null>(null)
  const [calibrationLabel, setCalibrationLabel] = useState('p20_executable_return')
  const [calibrationBuckets, setCalibrationBuckets] = useState(10)
  const [scan, setScan] = useState<ScanResult | null>(null)
  const [scanExchange, setScanExchange] = useState('')
  const [scanMinScore, setScanMinScore] = useState(70)
  const [scanAsOfDate, setScanAsOfDate] = useState('')
  const [baseline, setBaseline] = useState<BaselineModel | null>(null)
  const [baselineTrainUntil, setBaselineTrainUntil] = useState('')
  const [baselineLabel, setBaselineLabel] = useState('p20_executable_return')
  const [featureCatalog, setFeatureCatalog] = useState<FeatureCatalog | null>(null)
  const [multifeature, setMultifeature] = useState<MultiFeatureModel | null>(null)
  const [walkForward, setWalkForward] = useState<WalkForwardResult | null>(null)
  const [portfolio, setPortfolio] = useState<PortfolioValidation | null>(null)
  const [portfolioFraction, setPortfolioFraction] = useState(10)
  const [portfolioLabel, setPortfolioLabel] = useState('p20_executable_return')
  const [portfolioAsOfDate, setPortfolioAsOfDate] = useState('')
  const [transactionCostBps, setTransactionCostBps] = useState(10)
  const [slippageBps, setSlippageBps] = useState(5)
  const [message, setMessage] = useState('等待检查')
  const [busy, setBusy] = useState(false)
  const [cachedCount, setCachedCount] = useState<number | null>(null)
  const [approximateRuleRatio, setApproximateRuleRatio] = useState<number | null>(null)

  useEffect(() => {
    api.health().then(setHealth).catch(e => setMessage(e.message))
    api.labelStatus().then(setLabelStatus).catch(() => undefined)
    const refresh = () => api.quality().then(q => { setCachedCount(q.totalCached); setApproximateRuleRatio(q.approximateRuleRatio ?? null) }).catch(() => undefined)
    refresh(); const timer = window.setInterval(refresh, 5000)
    return () => window.clearInterval(timer)
  }, [])

  async function runAudit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setMessage('正在读取本地行情并计算…')
    try {
      const [nextBars, nextAudit, nextFeatures, nextScore] = await Promise.all([api.bars(exchange, code), api.audit(exchange, code, signalDate), api.featureAudit(exchange, code, signalDate), api.scoreAudit(exchange, code, signalDate)])
      setBars(nextBars); setAudit(nextAudit); setFeatureAudit(nextFeatures); setScoreAudit(nextScore); setMessage(`已载入 ${nextBars.length} 个交易日`)
    } catch (error) { setMessage(error instanceof Error ? error.message : '计算失败') }
    finally { setBusy(false) }
  }

  async function startImport(scope: 'representative' | 'all') {
    setBusy(true)
    try {
      const result = await api.importData(scope)
      setMessage(`任务 ${result.taskId} 已启动：待下载 ${result.total}，已跳过缓存 ${result.skipped}`)
      const poll = async () => {
        const task = await api.importTask(result.taskId)
        const current = task.currentSecurity ? `，最近 ${task.currentSecurity}` : ''
        const speed = task.speed ? `，${task.speed.toFixed(2)} 只/秒，ETA ${task.etaSeconds ?? '—'} 秒` : ''
        const provider = task.directAvailable === false ? '，已切换 AkShare/Sina' : ''
        setMessage(`任务 ${result.taskId}：${task.status} ${task.done}/${task.total}，错误 ${task.errors.length}${speed}${current}${provider}`)
        if (task.status === 'queued' || task.status === 'running') window.setTimeout(poll, 1000)
        else { setBusy(false); setMessage(`任务${task.errors.length ? '完成但有错误' : '已完成'}：${task.done}/${task.total}，错误 ${task.errors.length}`) }
      }
      await poll()
    }
    catch (error) { setMessage(error instanceof Error ? error.message : '启动失败'); setBusy(false) }
    finally { /* polling releases busy when the task reaches a terminal state */ }
  }

  async function startLabels() {
    setBusy(true)
    try {
      const result = await api.buildLabels('all')
      setMessage(`P1 标签任务 ${result.taskId.slice(0, 8)} 已启动`)
      const poll = async () => {
        const task = await api.labelTask(result.taskId)
        setMessage(`P1 标签：${task.done}/${task.total}，已生成 ${task.rows} 条`)
        if (task.status === 'queued' || task.status === 'running') window.setTimeout(poll, 1000)
        else {
          setBusy(false)
          if (task.errors.length) setMessage(`标签完成，但有 ${task.errors.length} 个错误`)
          api.labelStatus().then(setLabelStatus).catch(() => undefined)
        }
      }
      await poll()
    } catch (error) { setMessage(error instanceof Error ? error.message : '标签任务启动失败'); setBusy(false) }
  }

  async function startHistoryBackfill() {
    setBusy(true)
    try {
      const result = await api.startHistoryBackfill()
      setMessage(`历史补全任务 ${result.taskId.slice(0, 8)} 已启动：候选 ${result.total} 只`)
      const poll = async () => {
        const task = await api.historyBackfillTask(result.taskId)
        const current = task.currentSecurity ? ` · 当前 ${task.currentSecurity}` : ''
        const speed = task.speed ? ` · ${task.speed.toFixed(2)} 只/秒 · ETA ${task.etaSeconds ?? '—'} 秒` : ''
        setMessage(`历史补全 ${task.done}/${task.total} · 已补全 ${task.completed} · 新股 ${task.listingHistoryShort} · 错误 ${task.errors.length}${current}${speed}`)
        if (task.status === 'queued' || task.status === 'running') window.setTimeout(poll, 1000)
        else {
          setBusy(false)
          setMessage(`历史补全完成：已补全 ${task.completed} · 新股 ${task.listingHistoryShort} · 错误 ${task.errors.length}；检查错误后，再手动生成 P1 和 P2`)
        }
      }
      await poll()
    } catch (error) { setMessage(error instanceof Error ? error.message : '历史补全启动失败'); setBusy(false) }
  }

  async function startFeatures() {
    setBusy(true)
    try {
      const result = await api.buildFeatures('all')
      setMessage(`P2 特征任务 ${result.taskId.slice(0, 8)} 已启动`)
      const poll = async () => {
        const task = await api.featureTask(result.taskId)
        setMessage(`P2 特征：${task.done}/${task.total}，已生成 ${task.rows} 行`)
        if (task.status === 'queued' || task.status === 'running') window.setTimeout(poll, 1000)
        else { setBusy(false); if (task.errors.length) setMessage(`特征完成，但有 ${task.errors.length} 个错误`) }
      }
      await poll()
    } catch (error) { setMessage(error instanceof Error ? error.message : '特征任务启动失败'); setBusy(false) }
  }

  async function startScores() {
    setBusy(true)
    try {
      const result = await api.buildScores('all')
      setMessage(`P3 评分任务 ${result.taskId.slice(0, 8)} 已启动`)
      const poll = async () => {
        const task = await api.scoreTask(result.taskId)
        setMessage(`P3 评分：${task.done}/${task.total}，已生成 ${task.rows} 行`)
        if (task.status === 'queued' || task.status === 'running') window.setTimeout(poll, 1000)
        else { setBusy(false); if (task.errors.length) setMessage(`评分完成，但有 ${task.errors.length} 个错误`) }
      }
      await poll()
    } catch (error) { setMessage(error instanceof Error ? error.message : '评分任务启动失败'); setBusy(false) }
  }

  async function runValidation() {
    setBusy(true)
    try {
      const result = await api.validateSingleFactor(validationLabel)
      setValidation(result)
      setMessage(`P4 单因子验证：${result.sampleCount} 个成熟样本`)
    } catch (error) { setMessage(error instanceof Error ? error.message : '验证失败') }
    finally { setBusy(false) }
  }

  async function runCalibration() {
    setBusy(true)
    try { const result = await api.calibrateScore(calibrationLabel, calibrationBuckets); setCalibration(result); setMessage(`P5 校准：${result.sampleCount} 个成熟样本`) }
    catch (error) { setMessage(error instanceof Error ? error.message : '校准失败') }
    finally { setBusy(false) }
  }

  async function runScan() {
    setBusy(true)
    try { const result = await api.scanP3(scanMinScore, scanExchange || undefined, scanAsOfDate); setScan(result); setMessage(`P6 扫描：${result.rows.length} 个高分样本${result.truncated ? '（已达返回上限）' : ''}`) }
    catch (error) { setMessage(error instanceof Error ? error.message : '扫描失败') }
    finally { setBusy(false) }
  }

  async function runBaseline() {
    setBusy(true)
    try { const result = await api.trainBaseline(baselineTrainUntil, baselineLabel); setBaseline(result); setMessage(`P7 基线模型：${result.status}`) }
    catch (error) { setMessage(error instanceof Error ? error.message : '模型训练失败') }
    finally { setBusy(false) }
  }

  async function checkFeatureCatalog() {
    setBusy(true)
    try { const result = await api.featureCatalog(); setFeatureCatalog(result); setMessage(`P7 特征门槛：${result.securityCount} 只证券`) }
    catch (error) { setMessage(error instanceof Error ? error.message : '特征检查失败') }
    finally { setBusy(false) }
  }

  async function runMultifeature() {
    setBusy(true)
    try { const result = await api.trainMultifeature(baselineTrainUntil, baselineLabel); setMultifeature(result); setMessage(`P7 多特征模型：${result.status}`) }
    catch (error) { setMessage(error instanceof Error ? error.message : '多特征训练失败') }
    finally { setBusy(false) }
  }

  async function runWalkForward() {
    setBusy(true)
    try { const result = await api.walkForward(baselineLabel, 3); setWalkForward(result); setMessage(`P7 walk-forward：${result.folds.length} 折`) }
    catch (error) { setMessage(error instanceof Error ? error.message : 'walk-forward 失败') }
    finally { setBusy(false) }
  }

  function exportMultifeature() {
    if (!multifeature) return
    const csv = ['version,labelColumn,status,trainCount,testCount,accuracy,auc,feature,weight,warnings', ...Object.entries(multifeature.weights).map(([feature, weight]) => [multifeature.version, multifeature.labelColumn, multifeature.status, multifeature.trainCount, multifeature.testCount, multifeature.accuracy ?? '', multifeature.auc ?? '', feature, weight, `"${multifeature.warnings.join(';')}"`].join(','))].join('\n')
    const url = URL.createObjectURL(new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' })); const link = document.createElement('a'); link.href = url; link.download = 'p7-multifeature-model.csv'; link.click(); URL.revokeObjectURL(url)
  }

  function exportBaseline() {
    if (!baseline) return
    const csv = ['version,labelColumn,status,trainUntil,trainCount,testCount,positiveRate,testPositiveRate,accuracy,auc,coefficient,warnings', [baseline.version, baseline.labelColumn, baseline.status, baseline.trainUntil ?? '', baseline.trainCount, baseline.testCount, baseline.positiveRate ?? '', baseline.testPositiveRate ?? '', baseline.accuracy ?? '', baseline.auc ?? '', baseline.coefficient ?? '', `"${baseline.warnings.join(';')}"`].join(',')].join('\n')
    const url = URL.createObjectURL(new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' })); const link = document.createElement('a'); link.href = url; link.download = 'p7-baseline-model.csv'; link.click(); URL.revokeObjectURL(url)
  }

  async function runPortfolio() {
    setBusy(true)
    try { const result = await api.validatePortfolio(portfolioFraction / 100, portfolioLabel, portfolioAsOfDate, transactionCostBps, slippageBps); setPortfolio(result); setMessage(`P8 组合验证：${result.selectedCount} 个入选样本`) }
    catch (error) { setMessage(error instanceof Error ? error.message : '组合验证失败') }
    finally { setBusy(false) }
  }

  function exportPortfolio() {
    if (!portfolio) return
    const csv = ['version,labelColumn,topFraction,tradingDayCount,sampleCount,selectedCount,grossReturn,netReturn,benchmarkReturn,netExcessReturn,winRate,maxDrawdown,transactionCostBps,slippageBps,warnings', [portfolio.version, portfolio.labelColumn, portfolio.topFraction, portfolio.tradingDayCount, portfolio.sampleCount, portfolio.selectedCount, portfolio.averageReturn ?? '', portfolio.netAverageReturn ?? '', portfolio.benchmarkReturn ?? '', portfolio.netExcessReturn ?? '', portfolio.winRate ?? '', portfolio.maxDrawdown ?? '', portfolio.transactionCostBps, portfolio.slippageBps, `"${portfolio.warnings.join(';')}"`].join(',')].join('\n')
    const url = URL.createObjectURL(new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' })); const link = document.createElement('a'); link.href = url; link.download = 'p8-portfolio-validation.csv'; link.click(); URL.revokeObjectURL(url)
  }

  function exportScan() {
    if (!scan?.rows.length) return
    const csv = ['exchange,code,date,score,grade', ...scan.rows.map(row => [row.exchange, row.code, row.date, row.score, row.grade ?? ''].join(','))].join('\n')
    const url = URL.createObjectURL(new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8' }))
    const link = document.createElement('a'); link.href = url; link.download = `p6-scan-${scan.asOfDate ?? 'latest'}.csv`; link.click(); URL.revokeObjectURL(url)
  }

  return <main>
    <header><div><span className="eyebrow">LOCAL RESEARCH SYSTEM</span><h1>K 线结构概率研究台</h1></div><span className={`health ${health?.status === 'ok' ? 'ok' : ''}`}>{health?.status === 'ok' ? '本地服务正常' : '正在连接'}</span></header>
    <section className="panel status-panel">
      <div><h2>数据状态</h2><p className="muted">{health ? `${health.dataSource} · 缓存 ${health.cachePath} · ${cachedCount ?? '—'} 只证券 · 近似规则 ${approximateRuleRatio == null ? '—' : `${(approximateRuleRatio * 100).toFixed(2)}%`}` : '正在读取配置…'}</p></div>
      <div className="version"><span>标签版本</span><strong>{health?.versions.labelDefinitionVersion ?? '—'}</strong></div>
      <div className="version"><span>标签数据兼容</span><strong>{labelStatus && Number.isFinite(labelStatus.files) ? `${labelStatus.compatibleFiles}/${labelStatus.files}` : '—'}</strong><small>{labelStatus?.staleFiles ? `${labelStatus.staleFiles} 个文件待重建` : labelStatus?.delayedExitReady ? '顺延卖出口径就绪' : '暂无标签数据'}</small></div>
      <div className="version"><span>可恢复任务</span><strong>{health?.recoverableTasks ?? 0}</strong><small>再次点击对应任务即可续跑</small></div>
      <div className="version"><span>交易规则</span><strong>{health?.versions.limitRuleVersion ?? '—'}</strong></div>
      <div className="version"><span>特征版本</span><strong>{health?.versions.featureDefinitionVersion ?? '—'}</strong></div>
      <div className="version"><span>评分版本</span><strong>{health?.versions.scoreDefinitionVersion ?? '—'}</strong></div>
      <div className="version"><span>模型版本</span><strong>{health?.versions.modelDefinitionVersion ?? '—'}</strong></div>
      <div className="version"><span>多特征模型</span><strong>{health?.versions.multiFeatureModelDefinitionVersion ?? '—'}</strong></div>
      <div className="version"><span>滚动验证</span><strong>{health?.versions.walkForwardModelDefinitionVersion ?? '—'}</strong></div>
      <div className="version"><span>组合验证版本</span><strong>{health?.versions.portfolioValidationVersion ?? '—'}</strong></div>
      <div className="version"><span>行情策略</span><strong>{health?.versions.providerPolicyVersion ?? '—'}</strong></div>
      <button disabled={busy} onClick={() => startImport('representative')}>拉取代表样本</button>
      <button className="secondary" disabled={busy} onClick={() => startImport('all')}>高速下载全市场</button>
      <button className="secondary" disabled={busy} onClick={startHistoryBackfill}>补全短历史</button>
      <button className="secondary" disabled={busy} onClick={startLabels}>生成 P1 标签</button>
      <button className="secondary" disabled={busy} onClick={startFeatures}>生成 P2 特征</button>
      <button className="secondary" disabled={busy} onClick={startScores}>生成 P3 评分</button>
      <button className="secondary" disabled={busy} onClick={runValidation}>验证 P4 单因子</button>
      <button className="secondary" disabled={busy} onClick={runCalibration}>运行 P5 概率校准</button>
      <button className="secondary" disabled={busy} onClick={runScan}>扫描 P6 高分样本</button>
      <button className="secondary" disabled={busy} onClick={runBaseline}>训练 P7 基线模型</button>
      <button className="secondary" disabled={busy} onClick={checkFeatureCatalog}>检查 P2 特征覆盖</button>
      <button className="secondary" disabled={busy || !featureCatalog?.ready} onClick={runMultifeature}>训练 P7 多特征模型</button>
      <button className="secondary" disabled={busy} onClick={runWalkForward}>运行 P7 Walk-forward</button>
      <button className="secondary" disabled={busy} onClick={runPortfolio}>验证 P8 高分组合</button>
    </section>
    <section className="panel"><div className="section-title"><div><span className="eyebrow">P7 WALK-FORWARD</span><h2>P7 多窗口验证</h2></div>{walkForward && <span className="message">{walkForward.version}</span>}</div>{walkForward ? <div className="validation-panel"><article><span>平均 AUC</span><strong>{walkForward.averageAuc == null ? '—' : walkForward.averageAuc.toFixed(3)}</strong><small>平均准确率 {walkForward.averageAccuracy == null ? '—' : `${(walkForward.averageAccuracy * 100).toFixed(1)}%`}</small></article><table><thead><tr><th>训练截止</th><th>测试截止</th><th>状态</th><th>训练</th><th>测试</th><th>AUC</th><th>准确率</th></tr></thead><tbody>{walkForward.folds.map(fold => <tr key={fold.trainUntil}><td>{fold.trainUntil}</td><td>{fold.testUntil}</td><td>{fold.status}</td><td>{fold.trainCount}</td><td>{fold.testCount}</td><td>{fold.auc == null ? '—' : fold.auc.toFixed(3)}</td><td>{fold.accuracy == null ? '—' : `${(fold.accuracy * 100).toFixed(1)}%`}</td></tr>)}</tbody></table></div> : <p className="muted">使用多个训练截止日期滚动验证 P3 分数的样本外稳定性。</p>}</section>
    <section className="panel"><div className="section-title"><div><span className="eyebrow">P7 MULTI-FEATURE</span><h2>P7 多特征基线</h2></div>{multifeature && <span className="message">{multifeature.version}</span>}</div>{multifeature ? <div className="validation-panel"><article><span>训练 / 测试样本</span><strong>{multifeature.trainCount} / {multifeature.testCount}</strong><small>状态 {multifeature.status} · AUC {multifeature.auc == null ? '—' : multifeature.auc.toFixed(3)}</small></article><article><span>测试准确率</span><strong>{multifeature.accuracy == null ? '—' : `${(multifeature.accuracy * 100).toFixed(1)}%`}</strong><small>{multifeature.warnings.join('；') || '可用于基线比较'}</small></article><article><span>特征权重</span><strong>{Object.keys(multifeature.weights).length}</strong><small>{Object.entries(multifeature.weights).map(([key, value]) => `${key}:${value.toFixed(2)}`).join(' · ') || '暂无权重'}</small></article><button className="secondary" onClick={exportMultifeature}>导出 CSV</button></div> : <p className="muted">通过 P7 特征 ready gate 后，训练 P2/P3 多特征基线模型。</p>}</section>
    <section className="panel"><div className="section-title"><div><span className="eyebrow">P8 VALIDATION</span><h2>P8 高分组合验证</h2></div>{portfolio && <span className="message">{portfolio.version}</span>}</div><div className="calibration-controls"><label>选取比例<input type="number" min="1" max="50" value={portfolioFraction} onChange={e => setPortfolioFraction(Math.max(1, Math.min(50, Number(e.target.value) || 10)))} />%</label><label>结果口径<select value={portfolioLabel} onChange={e => setPortfolioLabel(e.target.value)}><ResultLabelOptions /></select></label><label>截至日期<input type="date" value={portfolioAsOfDate} onChange={e => setPortfolioAsOfDate(e.target.value)} /></label><label>成本 bps<input type="number" min="0" max="1000" value={transactionCostBps} onChange={e => setTransactionCostBps(Math.max(0, Math.min(1000, Number(e.target.value) || 0)))} /></label><label>滑点 bps<input type="number" min="0" max="1000" value={slippageBps} onChange={e => setSlippageBps(Math.max(0, Math.min(1000, Number(e.target.value) || 0)))} /></label>{portfolio ? <button className="secondary" onClick={exportPortfolio}>导出 CSV</button> : null}</div>{portfolio ? <div className="validation-panel"><article><span>净组合 / 全样本收益</span><strong>{pct(portfolio.netAverageReturn)} / {pct(portfolio.benchmarkReturn)}</strong><small>毛收益 {pct(portfolio.averageReturn)} · 成本 {portfolio.transactionCostBps + portfolio.slippageBps} bps · 入选 {portfolio.selectedCount}</small></article><article><span>净超额收益</span><strong>{pct(portfolio.netExcessReturn)}</strong><small>胜率 {pct(portfolio.winRate)} · 最大回撤 {pct(portfolio.maxDrawdown)}</small></article><article><span>回测口径</span><strong>非重叠</strong><small>{portfolio.warnings.join('；')}</small></article></div> : <p className="muted">按每日 P3 评分最高的指定比例构建研究组合，与所选持有期的全样本收益比较。</p>}</section>
    <section className="panel">
      <div className="section-title"><div><span className="eyebrow">P1 AUDITOR</span><h2>P1 标签审计台</h2></div><span className="message">{message}</span></div>
      <form onSubmit={runAudit}>
        <label>交易所<select value={exchange} onChange={e => setExchange(e.target.value)}><option value="sh">上海</option><option value="sz">深圳</option></select></label>
        <label>证券代码<input aria-label="证券代码" value={code} onChange={e => setCode(e.target.value)} /></label>
        <label>信号日<input type="date" value={signalDate} onChange={e => setSignalDate(e.target.value)} /></label>
        <button disabled={busy}>计算并审计</button>
      </form>
      {bars.length > 0 && <KlineChart bars={bars} events={{ signalDate, entryDate: audit?.entry.entry_date, plannedExitDate: audit?.labels['20']?.planned_exit_date, actualExitDate: audit?.exits?.['20']?.exit_date, pathHitDate: audit?.path?.hit_date, pathFailDate: audit?.path?.fail_date, drawdownPeakDate: audit?.drawdown?.peak_date, drawdownTroughDate: audit?.drawdown?.hit_date }} />}
      {audit && <div className="audit-grid">
        <article><span>样本资格</span><strong>{audit.eligibility.status}</strong><small>{audit.eligibility.reasons.join(' · ') || '检查通过'}</small></article>
        <article><span>交易状态</span><strong>{audit.securityStatus ? (audit.securityStatus.is_st ? 'ST' : '普通') : '—'}</strong><small>{audit.securityStatus?.is_approx ? `近似：${audit.securityStatus.reason}` : '正式规则'}</small></article>
        <article><span>可执行入口</span><strong>{audit.entry.status}</strong><small>{audit.entry.entry_date ?? '无入口'} {audit.entry.entry_price ? `@ ${audit.entry.entry_price}` : ''}</small></article>
        <article><span>P20 计划 / 顺延卖出</span><strong>{pct(audit.labels['20']?.executable_return)} / {pct(audit.labels['20']?.delayed_executable_return)}</strong><small>{audit.exits?.['20'] ? `${audit.exits['20'].status} · ${audit.exits['20'].exit_date ?? '无可执行卖出日'} · 顺延 ${audit.exits['20'].exit_delay ?? '—'} 日` : '等待卖出审计'}</small></article>
        <article><span>P20 最大回撤</span><strong>{pct(audit.drawdown?.max_drawdown)}</strong><small>{audit.drawdown?.hit_risk ? '触发 8% 风险线' : '未触发风险线'}</small></article>
        <article><span>路径标签</span><strong>{audit.path?.success ? '成功' : '失败'}</strong><small>{audit.path?.reason ?? '—'}</small></article>
        <article><span>标签成熟日</span><strong>{audit.maturityDate ?? '—'}</strong><small>只允许成熟标签进入校准池</small></article>
        <article><span>数据与因子版本</span><strong>{audit.factorVersion?.slice(0, 18) ?? '—'}</strong><small>{audit.dataSnapshotVersion ?? '—'}</small></article>
      </div>}
    </section>
    <section className="panel">
      <div className="section-title"><div><span className="eyebrow">P4 VALIDATION</span><h2>P4 单因子验证</h2></div>{validation && <span className="message">{validation.version}</span>}</div>
      <div className="calibration-controls"><label>结果口径<select value={validationLabel} onChange={e => setValidationLabel(e.target.value)}><ResultLabelOptions /></select></label></div>
      {validation ? <div className="validation-panel">
        <article><span>样本 / 独立时段</span><strong>{validation.sampleCount} / {validation.independentPeriodCount}</strong><small>七个自然日两步聚类 · 秩相关 {validation.rankCorrelation == null ? '—' : validation.rankCorrelation.toFixed(4)}</small></article>
        <table>
          <thead><tr><th>分桶</th><th>样本</th><th>平均分</th><th>所选口径收益</th><th>胜率</th><th>路径成功</th></tr></thead>
          <tbody>{validation.buckets.map(bucket => <tr key={bucket.bucket}>
            <td>{bucket.bucket}</td><td>{bucket.count}</td><td>{bucket.avgFactor.toFixed(2)}</td><td>{pct(bucket.avgLabel)}</td><td>{pct(bucket.winRate)}</td><td>{pct(bucket.pathSuccessRate)}</td>
          </tr>)}</tbody>
        </table>
      </div> : <p className="muted">生成 P1 标签和 P3 评分后，可验证 score 对所选收益口径的分桶效果。</p>}
    </section>
    <section className="panel"><div className="section-title"><div><span className="eyebrow">P6 SCANNER</span><h2>P6 高分扫描</h2></div>{scan && <span className="message">最低分 {scan.minScore} · {scan.scannedCount} 条</span>}</div><div className="calibration-controls"><label>市场<select value={scanExchange} onChange={e => setScanExchange(e.target.value)}><option value="">全部</option><option value="sh">上海</option><option value="sz">深圳</option></select></label><label>最低分<input type="number" min="0" max="100" value={scanMinScore} onChange={e => setScanMinScore(Math.max(0, Math.min(100, Number(e.target.value) || 0)))} /></label><label>截至日期<input type="date" value={scanAsOfDate} onChange={e => setScanAsOfDate(e.target.value)} /></label>{scan?.rows.length ? <button className="secondary" onClick={exportScan}>导出 CSV</button> : null}</div>{scan ? <table className="scan-table"><thead><tr><th>市场</th><th>代码</th><th>评分日期</th><th>分数</th><th>等级</th><th>操作</th></tr></thead><tbody>{scan.rows.map(row => <tr key={`${row.exchange}-${row.code}`}><td>{row.exchange === 'sh' ? '上海' : '深圳'}</td><td>{row.code}</td><td>{row.date}</td><td>{row.score.toFixed(1)}</td><td>{row.grade ?? '—'}</td><td><button className="link-button" onClick={() => { setExchange(row.exchange); setCode(row.code); setSignalDate(row.date); setMessage(`已带入 ${row.exchange === 'sh' ? '上海' : '深圳'} ${row.code}，点击上方审计`); window.scrollTo({ top: 0, behavior: 'smooth' }) }}>审计</button></td></tr>)}</tbody></table> : <p className="muted">扫描每只证券最新可用 P3 评分，默认返回分数不低于 70 的前 50 个样本。</p>}</section>
    <section className="panel">
      <div className="section-title"><div><span className="eyebrow">P5 CALIBRATION</span><h2>P5 概率校准</h2></div>{calibration && <span className="message">{calibration.version}</span>}</div>
      <div className="calibration-controls"><label>结果口径<select value={calibrationLabel} onChange={e => setCalibrationLabel(e.target.value)}><ResultLabelOptions /></select></label><label>分桶数<input type="number" min="2" max="20" value={calibrationBuckets} onChange={e => setCalibrationBuckets(Math.max(2, Math.min(20, Number(e.target.value) || 10)))} /></label></div>
      {calibration ? <div className="validation-panel"><article><span>成熟样本</span><strong>{calibration.sampleCount}</strong><small>{calibration.labelColumn} · 按 P3 分数分桶</small><small className={calibration.reliability.status === 'usable' ? 'reliability-ok' : 'reliability-review'}>{calibration.reliability.status === 'usable' ? '可用于研究' : '需要复核'}{calibration.reliability.warnings.length ? ` · ${calibration.reliability.warnings.join('；')}` : ''}</small></article><table><thead><tr><th>分桶</th><th>样本</th><th>平均分</th><th>观察胜率</th><th>平均收益</th></tr></thead><tbody>{calibration.buckets.map(bucket => <tr key={bucket.bucket}><td>{bucket.bucket}</td><td>{bucket.count}</td><td>{bucket.avgScore.toFixed(1)}</td><td>{pct(bucket.observedProbability)}</td><td>{pct(bucket.avgLabel)}</td></tr>)}</tbody></table></div> : <p className="muted">生成 P1 标签和 P3 评分后，运行概率校准查看分数与所选结果口径的对应关系。</p>}
    </section>
    <section className="panel"><div className="section-title"><div><span className="eyebrow">P7 BASELINE</span><h2>P7 轻量基线模型</h2></div>{baseline && <span className="message">{baseline.version}</span>}</div><div className="calibration-controls"><label>结果口径<select value={baselineLabel} onChange={e => setBaselineLabel(e.target.value)}><ResultLabelOptions /></select></label><label>训练截止日期<input type="date" value={baselineTrainUntil} onChange={e => setBaselineTrainUntil(e.target.value)} /></label>{baseline ? <button className="secondary" onClick={exportBaseline}>导出 CSV</button> : null}</div>{baseline ? <div className="validation-panel"><article><span>训练 / 测试样本</span><strong>{baseline.trainCount} / {baseline.testCount}</strong><small>时间切分，标签：{baseline.labelColumn}{baseline.trainUntil ? ` · 截止 ${baseline.trainUntil}` : ''}</small></article><article><span>测试准确率</span><strong>{baseline.accuracy == null ? '—' : `${(baseline.accuracy * 100).toFixed(1)}%`}</strong><small>ROC AUC {baseline.auc == null ? '—' : baseline.auc.toFixed(3)} · 正样本率 {baseline.testPositiveRate == null ? '—' : `${(baseline.testPositiveRate * 100).toFixed(1)}%`}</small></article><article><span>模型系数</span><strong>{baseline.coefficient == null ? '—' : baseline.coefficient.toFixed(4)}</strong><small>训练正样本率 {baseline.positiveRate == null ? '—' : `${(baseline.positiveRate * 100).toFixed(1)}%`} · {baseline.warnings.join('；') || '可用于基线比较'}</small></article></div> : <p className="muted">使用 P3 分数预测所选持有期的正收益，按时间切分输出样本外基线指标。</p>}</section>
    <section className="panel">
      <div className="section-title"><div><span className="eyebrow">P3 SCORE</span><h2>P3 结构评分</h2></div>{scoreAudit && <span className="message">{scoreAudit.score.version}</span>}</div>
      {scoreAudit ? <div className="score-panel">
        <article className={`score-card grade-${scoreAudit.score.grade.toLowerCase()}`}>
          <span>结构分数</span>
          <strong>{scoreAudit.score.score.toFixed(1)}</strong>
          <small>{scoreAudit.score.grade} · {scoreAudit.score.usable ? '可用' : '需审计'} {scoreAudit.score.reasons.join(' · ')}</small>
        </article>
        <div className="score-components">
          {(Object.keys(groupNames) as Array<keyof typeof groupNames>).map(group => {
            const item = scoreAudit.score.components[group]
            return <article key={group}>
              <h3>{groupNames[group]}</h3>
              <strong>{item.score.toFixed(1)} / {item.weight}</strong>
              <small>{item.reasons.join(' · ') || '无可用特征'}</small>
            </article>
          })}
        </div>
      </div> : <p className="muted">执行上方审计后，展示 P2 特征驱动的可解释 P3 分数。</p>}
    </section>
    <section className="panel"><div className="section-title"><div><span className="eyebrow">P7 FEATURE GATE</span><h2>P7 多特征数据门槛</h2></div>{featureCatalog && <span className="message">{featureCatalog.ready ? '可进入训练' : '暂不可训练'} · {featureCatalog.version}</span>}</div>{featureCatalog ? <div className="validation-panel"><article><span>证券覆盖</span><strong>{featureCatalog.securityCount}</strong><small>{featureCatalog.rowCount} 行特征数据</small></article><article><span>可用特征</span><strong>{featureCatalog.featureColumns.length}</strong><small>{featureCatalog.featureColumns.slice(0, 5).join('、') || '暂无特征'}{featureCatalog.missingColumns.length ? ` · 缺失 ${featureCatalog.missingColumns.join('、')}` : ''}</small></article></div> : <p className="muted">检查 P2 特征文件覆盖后，再进入多特征模型训练。</p>}</section>
    <section className="panel">
      <div className="section-title"><div><span className="eyebrow">P2 AUDITOR</span><h2>P2 特征审计</h2></div>{featureAudit && <span className="message">历史 {featureAudit.availableHistory} 日 · {featureAudit.priceBasis}</span>}</div>
      {featureAudit ? <div className="feature-groups">
        {(Object.keys(groupNames) as Array<keyof typeof groupNames>).map(group => <article key={group}>
          <h3>{groupNames[group]}</h3>
          <dl>{Object.entries(featureAudit.groups[group]).map(([key, value]) => <div key={key}><dt>{featureNames[key] ?? key}</dt><dd>{featureValue(value)}</dd></div>)}</dl>
        </article>)}
      </div> : <p className="muted">使用上方证券与日期执行审计后，展示五组时间点特征。</p>}
    </section>
  </main>
}
