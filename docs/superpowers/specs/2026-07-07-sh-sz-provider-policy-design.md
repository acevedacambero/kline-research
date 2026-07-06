# 沪深生产 Provider 策略与 G2 修复设计

## 目标

解除 `v0.2-private-tunnel` 的 G2 阻断，同时将产品市场范围明确收窄为上海和深圳。
生产服务器不再依赖已实测不可达的东方财富接口，也不再包含北交所数据、入口或正式
计算结果。

## 市场范围

正式支持：上海证券交易所、深圳证券交易所，包括主板、科创板和创业板。

不支持：北京证券交易所。北交所证券不进入证券主数据、下载任务、P1 标签、P2 特征、
指数基准或上线 gate。代码中可保留通用交易规则实现，但产品入口和生产数据链不得返回
北交所证券。

## 生产数据链

```text
沪深股票 raw 日线      -> TencentHttpSource
上证指数/深证成指 raw  -> TencentHttpSource
QFQ/HFQ 复权因子      -> AkShare 新浪 stock_zh_a_daily
交易日历               -> AkShare 新浪 tool_trade_date_hist_sina
沪深 raw 备用          -> AkShare 新浪 stock_zh_a_daily
东方财富                -> 诊断源；默认生产策略不调用
```

腾讯和新浪只提供各自明确的数据事实。正式前复权、后复权和 total-return 继续由系统
根据 raw 与因子派生；禁止使用腾讯返回的调整行情补齐新浪因子，也禁止把不同 provider
的调整行情拼接。

生产版本标识新增 `providerPolicyVersion=sh-sz-tencent-sina-v1`。数据快照继续记录实际
raw provider 和 factor provider，使同一证券的来源可审计。

## 运行时路由

沪深股票下载首先调用腾讯 raw。单票腾讯失败时，允许调用新浪 raw 备用路径；备用结果
必须带 provider 标记和质量事件。复权因子始终由新浪独立获取，因子缺失或覆盖不完整时
该证券导入失败，不生成正式标签或特征。

指数由腾讯明确请求 `sh000001` 和 `sz399001` raw day 数据。任一基准指数不可用时，
对应市场禁止生成超额收益标签。交易日历不可用时禁止新下载和增量任务，只允许读取既有
缓存进行离线审计。

东方财富保留在诊断探针中并产生告警，但不参与生产下载优先级、自动 fallback 或 G2
通过判断，避免每只证券重复等待已知不可达接口。

## 北交所缓存清理

实现专用市场清理器，只接受显式 exchange 参数并支持 dry-run。北交所清理范围：

- DuckDB `dataset_manifest` 中 `stock:bj:*` 记录；
- 清单引用的 raw、因子和 derived Parquet；
- P1 标签目录中的北交所文件；
- P2 特征目录中的北交所文件；
- security master 中 exchange=`bj` 的记录；
- 删除后产生的空目录。

清理分两步：先生成包含证券、路径、文件数和字节数的 dry-run 回执；确认范围后执行同一
计划。删除快照目录前必须查询清单引用，仅当目录不再被沪深或其他数据集引用时才可删除。
执行回执记录删除成功、跳过、缺失和错误项，并保存在 Git 忽略的 `artifacts/`。

清理后硬验收：缓存市场统计中 `bj=0`；security master 无北交所；标签和特征无北交所
文件；沪深清单行数、文件指纹和代表证券查询结果与清理前一致。不得使用通配符递归删除
未经过清单验证的快照根目录。

## 产品与 API

- 证券列表过滤北交所；
- 代表样本只含沪深；
- 全市场导入只含沪深；
- 前端交易所选择移除“北京”；
- 手工请求 `exchange=bj` 返回 `422 MARKET_NOT_SUPPORTED`，不触发 provider 请求；
- 质量报告继续显示 `bj: 0`，并展示 provider policy 版本。

## 新 G2 Gate

Gate 必须从目标服务器执行，使用沪深样本，不包含北交所：

1. 腾讯沪深股票 10 只，成功率至少 90%，OHLCV 完整；
2. 腾讯上证指数与深证成指 2/2 成功；
3. 新浪 QFQ/HFQ 因子至少 6 只沪深代表证券全部成功，覆盖 raw 历史且数值有效；
4. 新浪 raw 备用路径至少验证沪深各一只成功；
5. 独立交易日历必须成功；
6. 东方财富结果只进入 warnings，不影响 passed；
7. 报告分别输出 required checks 和 diagnostic checks，避免告警被误算为阻断。

任一 required check 失败时 G2 为 BLOCKED。通过后仍需用户确认，才能恢复 Phase 2 的
Access、Tunnel、发布脚本和用户服务实施。

## 测试与验收

- Golden tests 验证腾讯股票与指数 raw 响应；
- Provider policy tests 验证腾讯主源、新浪 raw fallback、东财不被生产路径调用；
- 因子 gate 测试覆盖空表、覆盖不足、非法值和成功路径；
- 市场范围 API/前端测试验证北交所不可选、不可请求；
- 清理器测试使用临时 DuckDB/Parquet，验证 dry-run、引用保护、执行回执和沪深不变；
- 在本机完成全套回归后，从服务器运行新 G2，并保存 exact-SHA 证据。

## 非目标

本阶段不部署生产服务、不配置 Cloudflare Access/Tunnel、不改 Nginx、不上传本机沪深
历史缓存，也不删除服务器其他目录。北交所清理仅作用于本项目本地数据根目录。
