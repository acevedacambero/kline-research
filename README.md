# K 线结构概率研究台

通过 AkShare 获取 A 股证券列表、未复权日线、复权因子与指数数据，以 raw OHLCV 为事实源，在系统内派生 QFQ/HFQ/total-return，并提供 P1 标签审计 API 与 React 工作台。正式概率口径仅支持日线。

## 启动

```powershell
# 后端
.\.venv\Scripts\python.exe -m uvicorn kline.api:app --host 127.0.0.1 --port 8000

# 前端（另一个终端）
pnpm dev
```

浏览器打开 `http://127.0.0.1:5173`。

数据快照默认输出到项目的 `data/data-foundation-v1/snapshots`，可通过 `KLINE_DATA_PATH` 覆盖。首次查询或导入需要联网访问 AkShare 上游接口。

## 验证与导入

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests
pnpm test:web
pnpm build

# 导入沪深北各两个代表文件
.\.venv\Scripts\python.exe scripts\import_representative.py
```

## 当前边界

- 已实现 AkShare 证券列表、raw 日线、复权因子、指数、不可变内容快照、质量事件及 DuckDB 清单。
- QFQ/HFQ/total-return 由 raw + factor 在系统内派生；涨跌停和可执行入口只使用 raw。
- 已实现资格、交易规则、T+1～T+3 入口、收益/超额、路径、回撤、成熟度和独立时段。
- 已实现缓存全集的异步 P1 批量标签任务；默认按 5 个交易日采样，输出 P5/P10/P20/P60、路径、回撤、成熟日及完整版本键。
- `POST /api/labels/build` 启动任务，`GET /api/labels/tasks/{taskId}` 查询进度；标签保存在 `data/data-foundation-v1/labels/<snapshot>/`。
- 已实现 P2 日频离线特征：趋势、位置、动量、量价和交易行为五组。趋势/形态使用 QFQ，收益/波动使用 total-return，涨停/一字板/缺口使用 raw。
- `POST /api/features/build` 异步生成本地缓存证券的特征，`GET /api/features/tasks/{taskId}` 查询进度，`POST /api/p2/audit` 按证券与日期解释五组时间点特征。
- 特征保存在 `data/data-foundation-v1/features/daily-features-v1/`，路径和清单绑定快照、因子、交易规则及特征定义版本；窗口不足保留空值，不使用未来数据填补。
- 全市场下载优先使用东方财富 HTTP；不可用时自动熔断到 AkShare/Sina。默认跳过已有本地快照，仅下载缺失证券；传入 `refresh: true` 才强制刷新。
- 历史 ST 缺少可靠逐日来源，当前使用证券现名近似并显式标记 `st_status_approx`；注册制 IPO noLimit 窗口按上市交易序号处理。
- 历史 ST 状态采用近似规则并返回 `isApprox`；后续可通过版本化状态表修正。
- 卖出执行、成本滑点、P2 特征评分/筛选、概率校准和回测不在当前范围。
