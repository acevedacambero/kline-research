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

## 当前边界

- 仅提供日线正式标签和特征；周线、月线尚未纳入版本体系。
- P1 包含资格、交易规则、T+1 至 T+3 可执行入口、P5/P10/P20/P60 收益、路径、回撤和成熟度。
- P2 提供趋势、位置、动量、量价和交易行为五组时点特征。
- 历史 ST 状态仍可能使用近似规则并保留审计标记。
- P3 结构评分、P4 单因子验证、P5 分数概率校准和 P6 高分扫描已上线；校准结果会提示样本量与单调性风险。
- P6 支持市场、最低分、截至日期筛选，结果可导出 CSV 并一键带入 P1 审计台。
- P7 提供基于 P3 分数的轻量逻辑回归基线，可指定训练截止日期并输出样本外指标。
- P7 多特征模型训练前必须通过特征目录 ready gate；缺失关键 P2 特征时不会进入训练阶段。
- P8 提供按评分排序的高分组合验证，可切换持有期、选取比例和截至日期；结果暂不计成本与滑点。
- P8 会对小于 20 个入选样本的结果增加探索性提示。
- P7/P8 结果支持 CSV 导出，并保留可靠性警告字段。
- 实时行情、交易执行、策略回测、成本和滑点不在当前范围。
