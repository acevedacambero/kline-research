import { FormEvent, useEffect, useState } from 'react'
import { api, type Audit, type Bar, type FeatureAudit, type FeatureValue, type Health } from './api'
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

export function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [exchange, setExchange] = useState('sh')
  const [code, setCode] = useState('600000')
  const [signalDate, setSignalDate] = useState('2024-01-02')
  const [bars, setBars] = useState<Bar[]>([])
  const [audit, setAudit] = useState<Audit | null>(null)
  const [featureAudit, setFeatureAudit] = useState<FeatureAudit | null>(null)
  const [message, setMessage] = useState('等待检查')
  const [busy, setBusy] = useState(false)
  const [cachedCount, setCachedCount] = useState<number | null>(null)

  useEffect(() => {
    api.health().then(setHealth).catch(e => setMessage(e.message))
    const refresh = () => api.quality().then(q => setCachedCount(q.totalCached)).catch(() => undefined)
    refresh(); const timer = window.setInterval(refresh, 5000)
    return () => window.clearInterval(timer)
  }, [])

  async function runAudit(event: FormEvent) {
    event.preventDefault(); setBusy(true); setMessage('正在读取本地行情并计算…')
    try {
      const [nextBars, nextAudit, nextFeatures] = await Promise.all([api.bars(exchange, code), api.audit(exchange, code, signalDate), api.featureAudit(exchange, code, signalDate)])
      setBars(nextBars); setAudit(nextAudit); setFeatureAudit(nextFeatures); setMessage(`已载入 ${nextBars.length} 个交易日`)
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
        else { setBusy(false); if (task.errors.length) setMessage(`标签完成，但有 ${task.errors.length} 个错误`) }
      }
      await poll()
    } catch (error) { setMessage(error instanceof Error ? error.message : '标签任务启动失败'); setBusy(false) }
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

  return <main>
    <header><div><span className="eyebrow">LOCAL RESEARCH SYSTEM</span><h1>K 线结构概率研究台</h1></div><span className={`health ${health?.status === 'ok' ? 'ok' : ''}`}>{health?.status === 'ok' ? '本地服务正常' : '正在连接'}</span></header>
    <section className="panel status-panel">
      <div><h2>数据状态</h2><p className="muted">{health ? `${health.dataSource} · 缓存 ${health.cachePath} · ${cachedCount ?? '—'} 只证券` : '正在读取配置…'}</p></div>
      <div className="version"><span>标签版本</span><strong>{health?.versions.labelDefinitionVersion ?? '—'}</strong></div>
      <div className="version"><span>交易规则</span><strong>{health?.versions.limitRuleVersion ?? '—'}</strong></div>
      <div className="version"><span>特征版本</span><strong>{health?.versions.featureDefinitionVersion ?? '—'}</strong></div>
      <div className="version"><span>行情策略</span><strong>{health?.versions.providerPolicyVersion ?? '—'}</strong></div>
      <button disabled={busy} onClick={() => startImport('representative')}>拉取代表样本</button>
      <button className="secondary" disabled={busy} onClick={() => startImport('all')}>高速下载全市场</button>
      <button className="secondary" disabled={busy} onClick={startLabels}>生成 P1 标签</button>
      <button className="secondary" disabled={busy} onClick={startFeatures}>生成 P2 特征</button>
    </section>
    <section className="panel">
      <div className="section-title"><div><span className="eyebrow">P1 AUDITOR</span><h2>P1 标签审计台</h2></div><span className="message">{message}</span></div>
      <form onSubmit={runAudit}>
        <label>交易所<select value={exchange} onChange={e => setExchange(e.target.value)}><option value="sh">上海</option><option value="sz">深圳</option></select></label>
        <label>证券代码<input aria-label="证券代码" value={code} onChange={e => setCode(e.target.value)} /></label>
        <label>信号日<input type="date" value={signalDate} onChange={e => setSignalDate(e.target.value)} /></label>
        <button disabled={busy}>计算并审计</button>
      </form>
      {bars.length > 0 && <KlineChart bars={bars} />}
      {audit && <div className="audit-grid">
        <article><span>样本资格</span><strong>{audit.eligibility.status}</strong><small>{audit.eligibility.reasons.join(' · ') || '检查通过'}</small></article>
        <article><span>可执行入口</span><strong>{audit.entry.status}</strong><small>{audit.entry.entry_date ?? '无入口'} {audit.entry.entry_price ? `@ ${audit.entry.entry_price}` : ''}</small></article>
        <article><span>P20 可执行收益</span><strong>{pct(audit.labels['20']?.executable_return)}</strong><small>超额 {pct(audit.labels['20']?.excess_executable_return)}</small></article>
        <article><span>P20 最大回撤</span><strong>{pct(audit.drawdown?.max_drawdown)}</strong><small>{audit.drawdown?.hit_risk ? '触发 8% 风险线' : '未触发风险线'}</small></article>
        <article><span>路径标签</span><strong>{audit.path?.success ? '成功' : '失败'}</strong><small>{audit.path?.reason ?? '—'}</small></article>
        <article><span>标签成熟日</span><strong>{audit.maturityDate ?? '—'}</strong><small>只允许成熟标签进入校准池</small></article>
        <article><span>数据与因子版本</span><strong>{audit.factorVersion?.slice(0, 18) ?? '—'}</strong><small>{audit.dataSnapshotVersion ?? '—'}</small></article>
      </div>}
    </section>
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
