# K 线结构概率研究台

本地 Web 研究应用，提供沪深日线数据、P1 标签和 P2 特征审计。正式价格计算以未复权行情为事实源，在本地派生前复权、后复权和总回报序列。

## 生产站点

- 地址：`https://skyland.us.ci/`，整个站点由 Cloudflare Access 保护，仅授权邮箱可登录。
- 源站仅监听 `127.0.0.1:8800`；公网不开放应用端口，Cloudflare Tunnel 是唯一入口。
- FastAPI 会再次验证 Access JWT 的签名、issuer、AUD、有效期和邮箱白名单。
- 应用与隧道均以用户级 systemd 服务运行；生产 Uvicorn 固定为单 worker。
- 发布目录位于 `~/apps/kline/releases/`，`current` 指向当前版本，`previous` 指向可回滚版本；运行数据始终保留在 `shared/data`。

常用运维命令见 [`deploy/README.md`](deploy/README.md)。回滚执行
`~/apps/kline/scripts/rollback.sh`，脚本会等待健康检查通过，且不会修改共享数据。

## 市场与数据源

- 产品范围仅包含上海、深圳市场；北交所请求返回 `422 MARKET_NOT_SUPPORTED`。
- 生产原始股票行情：腾讯 HTTP；失败时显式回退到新浪原始日线。
- 指数行情：腾讯上证指数 `sh000001`、深证成指 `sz399001`。
- 复权因子和交易日历：AKShare 封装的新浪接口。
- 东方财富仅保留为上线诊断项，不参与生产路由，也不阻塞上线。
- 当前供应商策略版本：`sh-sz-tencent-sina-v1`。

## 短历史补全

“补全短历史”只扫描沪深规范缓存中少于 250 个有效交易日的证券，使用新浪/AKShare
长历史接口从 1990 年开始重拉，明确绕过腾讯近期窗口。下载、因子和派生全部成功后才
更新当前快照；失败时旧快照继续可用。

完整上市历史仍少于 250 日且数据更新至近期的证券会标记为新股历史不足，后续任务不再
重复下载。任务逐票隔离错误并展示补全、新股和错误数量。任务完成后不会自动生成标签或
特征；检查错误和质量报告后，再手动点击“生成 P1 标签”和“生成 P2 特征”。

## 本地启动

```powershell
# 后端
.\.venv\Scripts\python.exe -m uvicorn kline.api:app --host 127.0.0.1 --port 8000

# 前端（另一个终端）
cd web
pnpm dev
```

浏览器打开 `http://127.0.0.1:5173`。数据默认存放在 `data/`，可通过 `KLINE_DATA_PATH` 修改。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
cd web
pnpm test
pnpm build
```

GitHub Actions 对每次 push 和 Pull Request 执行相同的后端、前端和生产构建检查，
并重新生成 OpenAPI 契约；生成文件与仓库不一致时 CI 直接失败。生产数据和 DuckDB
不会进入 CI，线上发布仍必须通过独立供应商 Gate、单写者 Gate和人工数据验收。

## 北交所缓存清理

清理命令默认只生成不可变预览，不修改数据：

```powershell
.\.venv\Scripts\python.exe scripts\cleanup_market.py `
  --exchange bj `
  --output artifacts\bj-cleanup-plan.json
```

核对清单后，必须同时提供精确市场、执行开关和原清单文件：

```powershell
.\.venv\Scripts\python.exe scripts\cleanup_market.py `
  --execute `
  --exchange bj `
  --plan artifacts\bj-cleanup-plan.json `
  --output artifacts\bj-cleanup-receipt.json
```

执行器只删除清单中经过指纹验证的北交所文件和元数据；共享文件受保护，不会递归删除快照根目录。清理回执与 Gate 报告位于已忽略的 `artifacts/`，不得提交到 Git。

## 证券身份一致性检查

行情、P1、P2 和 P3 接口会校验交易所与六位证券代码，阻止把 `301377` 按上海或把 `601100` 按深圳写入缓存。历史身份异常先生成只读计划：

```bash
python scripts/audit_security_identities.py \
  --data-root /home/guagua/apps/kline/shared/data \
  --output artifacts/security-identity-audit.json
```

只有计划确认不存在错误行情清单或证券主数据时，才允许按原计划精确删除错误质量事件：

```bash
python scripts/audit_security_identities.py \
  --data-root /home/guagua/apps/kline/shared/data \
  --execute-event-cleanup \
  --plan artifacts/security-identity-audit.json \
  --output artifacts/security-identity-cleanup-receipt.json
```

如果计划发现错误行情清单但证券主数据正常，应先停止应用，再按同一份计划把无有效引用的错误快照移入隔离区，并精确删除目录指针和对应质量事件：

```bash
systemctl --user stop kline.service
python scripts/audit_security_identities.py \
  --data-root /home/guagua/apps/kline/shared/data \
  --execute-quarantine \
  --plan artifacts/security-identity-audit.json \
  --output artifacts/security-identity-quarantine-receipt.json
systemctl --user start kline.service
```

执行器会拒绝隔离仍被正常证券引用的共享快照，事务失败时会把已经移动的目录放回原位。隔离目录位于数据根目录的 `quarantine/security-identity/<plan-id>`，确认业务数据正常前不做物理删除。证券主数据本身错配时仍会主动阻断，必须先人工修复主数据。

## 生产部署 Gate

目标服务器必须同时通过供应商可达性 Gate 和 DuckDB 单写者 Gate，才能进入部署阶段。

```bash
python scripts/probe_providers.py --output provider-gate.json
```

供应商 Gate 版本为 `sh-sz-provider-g2-v2`，必需检查包括：

- 腾讯沪深股票代表样本 10 个，成功率不低于 80%，OHLCV 完整且非空；
- 腾讯沪深指数 2 个全部成功；
- 新浪复权因子 6 个全部成功，覆盖和值有效；
- 新浪原始行情回退 2 个全部成功；
- 新浪交易日历成功。

东方财富结果记录在 `diagnosticChecks`，失败只产生警告。`--quick` 仅供诊断，固定返回退出码 2，不能作为上线凭证。

DuckDB 单写者验证：

```bash
python -m pytest tests/test_job_store.py tests/test_job_coordinator.py \
  tests/test_single_writer.py tests/test_api.py -q
```

生产 Uvicorn 只允许一个 worker。任一必需 Gate 失败都必须阻断部署。

重任务状态持久化在 `jobs.duckdb`。服务被强制终止时，运行中的任务会标记为可恢复；页面显示可恢复任务数量，再次点击同类任务会使用原任务 ID 和原始任务载荷续跑。各数据写入保持幂等，已完成文件会复用或按内容指纹跳过。

## 可复现研究实验

P4 单因子验证、P5 概率校准、P6 扫描、P7 三类模型运行和 P8 组合验证现在都会生成不可变实验记录。每条记录保存：

- 完整输入参数与计算结果；
- 行情目录清单哈希及证券数量；
- 标签、特征、评分和算法版本；
- 生产发布版本与运行时间。

网页“研究实验历史”支持按类型筛选、重新载入旧结果，并对两个同类实验的参数和核心指标进行并排比较。接口为 `/api/research/runs`、`/api/research/runs/{runId}` 和 `/api/research/runs/compare`。

网页“特征与评分漂移监控”使用互不重叠的近期/基准交易日窗口，检查 P3 评分以及多头排列、20 日动量、5 日量比、20 日波动率。报告同时给出总体和沪深分市场的 PSI、标准化均值偏移、缺失率变化；PSI 达到 0.10/0.25 或均值偏移达到 0.25/0.50 时分别进入观察/漂移状态。每次检查会作为 `drift-monitor` 实验永久登记，便于比较不同时间的漂移程度。接口为 `POST /api/monitoring/drift`。

P7 的训练/测试切分默认使用七个自然日 embargo，并按标签成熟日 purge 训练样本；结果和实验记录都会保存隔离数量与规则版本。P4 同时报告三个时间段的秩相关稳定性、置换检验 p 值，以及 Benjamini-Hochberg 校正后的 q 值。

P7 模型注册表支持显式选择“当前模型”。只有状态为 `trained` 且评分、特征、标签依赖版本仍兼容的模型才能启用；同类型模型切换会保存前一模型 ID 和完整启用历史，因此可以审计并重新选择旧版本。设为当前模型只管理研究产物生命周期，不会连接券商、自动下单或触发交易。

`GET /api/system/research-acceptance` 汇总数据新鲜度、身份一致性、P4-P8 正式实验覆盖、模型注册和当前模型状态。网页“研究运行 Gate 明细”可以生成并导出验收报告；任一必需实验缺失、行情过期、身份错配或尚未选择当前模型时，报告保持“待完善”。

## 当前边界

- 仅提供日线正式标签和特征；周线、月线尚未纳入版本体系。
- P1 包含资格、交易规则、T+1 至 T+3 可执行入口、P5/P10/P20/P60 收益、路径、回撤、成熟度，以及计划卖出日至最多三个交易日的可执行卖出顺延。
- P2 提供趋势、位置、动量、量价和交易行为五组时点特征。
- 历史 ST 状态仍可能使用近似规则并保留审计标记。
- P3 结构评分、P4 单因子验证、P5 分数概率校准和 P6 高分扫描已上线；校准结果会提示样本量与单调性风险。
- P6 支持市场、最低分、截至日期筛选，结果可导出 CSV 并一键带入 P1 审计台。
- P7 提供基于 P3 分数的轻量逻辑回归基线，可指定训练截止日期并输出样本外指标。
- P7 多特征模型训练前必须通过特征目录 ready gate；缺失关键 P2 特征时不会进入训练阶段。
- P7 多特征基线已提供 P3 分数与核心 P2 特征权重、样本外 AUC/准确率和 CSV 导出。
- P8 提供按评分排序的高分组合验证，可切换持有期、计划收盘/可执行顺延卖出口径、选取比例和截至日期，并支持配置成本与滑点。
- P8 会对小于 20 个入选样本的结果增加探索性提示。
- P7/P8 结果支持 CSV 导出，并保留可靠性警告字段。
- 线上研究接口默认抽取每只证券最近 100 条成熟样本；模型输入保留 250 条日线以覆盖长周期标签的成熟窗口，Walk-forward 保留 500 条，避免在小内存 VPS 上触发代理超时或内存重启；结果中的样本数即实际研究口径。
- 实时行情和交易执行不在当前范围；P8 仅为日线研究组合验证，尚不包含逐笔撮合、税费模型、冲击成本或真实交易级回测。
## 全市场覆盖、自动维护与备份

数据状态页提供全市场覆盖台账，按证券记录缓存状态、首末日期、日线行数、长区间间隔、复权近似状态和可修复原因。长间隔可能来自停牌或节假日，因此只作观察项，不会单独判为数据缺口或触发全市场重下载；缺失、不可读、历史不足、过期和近似复权证券才进入修复队列。覆盖检查通过后台任务生成，不阻塞网页请求。

日常维护支持手动“更新今日行情”和工作日定时增量更新。增量任务只请求最近行情窗口，再与不可变历史事实合并生成新快照。

服务器可从网页创建并校验备份。离线恢复必须先停止应用服务：

```bash
python scripts/backup_data.py --data /home/guagua/apps/kline/shared/data --output /home/guagua/backups
systemctl --user stop kline.service
python scripts/restore_data.py /home/guagua/backups/kline-data-YYYYMMDDTHHMMSSZ.tar.gz --data /home/guagua/apps/kline/shared/data --confirm
systemctl --user start kline.service
```

恢复时旧数据会保留为同目录下的 `data.before-restore-*`，确认成功后再人工清理。
运行中的 `jobs.duckdb` 属于瞬时任务历史，网页备份会排除该锁定文件；行情目录、目录清单、特征、标签、评分、模型和 Gate 报告均纳入备份。
