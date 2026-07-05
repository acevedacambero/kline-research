# K 线结构概率分析系统产品规划书 v1.2-data-foundation

## 冻结原则

- Raw OHLCV 是唯一行情事实源；跨 provider 只允许合并 raw。
- Corporate actions / adjustment factors 是复权桥梁，必须独立版本化。
- QFQ、HFQ、total-return 是可重建派生视图，禁止跨源逐日拼接。
- 涨跌停、不可买、不可卖和涨停特征只使用 raw 价格。
- 收益、路径和回撤标签使用系统派生 total-return，结构展示默认使用派生 QFQ。
- 每份结果同时绑定 `dataSnapshotVersion`、`factorVersion` 和标签/规则版本。

## P0.5：Raw Fact Source

- AkShare 东方财富为主源，新浪为受控备用源；按时间分段、有限重试和失败隔离。
- Raw 行保留 provider 与字段完整性标记；备用源缺字段时生成质量事件。
- Raw 与 factor 分表保存到内容寻址、不可变快照；DuckDB 仅维护当前版本指针和事件目录。
- 指数优先使用 AkShare 主接口，失败时使用新浪指数日线，不以个股自身替代基准。

## P0.6：复权与权益事件验证

- 因子表独立保存并生成 `factorVersion`。
- 派生引擎按交易日匹配有效因子，构建 QFQ/HFQ/total-return。
- 因子覆盖不足直接阻断派生，并写入 `factor-coverage-error`。
- Provider QFQ 只用于对照验证，不进入事实表或跨源合并。

## 后续顺序

P0.5 Raw Fact Source → P0.6 复权验证 → P1 标签 → P2 特征 → P3 评分 → P4 单因子验证 → P5 概率校准 → P6 扫描 → P7 轻量模型 → P8 策略验证。
