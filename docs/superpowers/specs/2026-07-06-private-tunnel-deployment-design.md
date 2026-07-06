# K 线结构概率系统 v0.2-private-tunnel 上线设计

## 目标与边界

将现有 FastAPI、React、DuckDB、Parquet 和 AkShare 数据链完整部署到
`154.53.75.101`，通过 Cloudflare Tunnel 暴露为 `skyland.us.ci`，并使用
Cloudflare Access 限制为授权邮箱访问。源站不开放新公网端口，不修改现有
Nginx 对 80/443 的占用。

上线采用 gate 驱动：provider 可达性和 DuckDB 单写者未通过前，不创建生产
release、不安装 systemd 服务、不切换域名流量。

## 最终拓扑

```text
授权用户
  -> Cloudflare Access
  -> skyland.us.ci
  -> Cloudflare Tunnel
  -> 127.0.0.1:8800
  -> 单进程 FastAPI + 内嵌 JobRunner
  -> DuckDB + Parquet shared 持久目录
```

FastAPI 同域提供 React 构建产物与 `/api/*`，避免跨域配置。`/healthz` 仅供
本机健康检查，不经公网路由。

## 上线硬门槛

以下条件必须全部通过：

1. DuckDB 只有一个写进程，Uvicorn 固定单 worker。
2. 在目标服务器完成东财、腾讯、新浪、指数和交易日历 provider 实测。
3. 测试和 migration 预检使用临时目录，禁止连接 production shared 数据。
4. schema migration 只允许向后兼容变更，并记录版本和日志。
5. Cloudflare Access JWT 验证签名、issuer、AUD、有效期和邮箱 allowlist。
6. `.env`、Tunnel 凭据和密钥权限为 600，凭据目录权限为 700。
7. 用户服务固定资源上限，DuckDB 固定 `memory_limit=2GB`、`threads=2`。
8. 交易日、新鲜度、任务日期和展示明确使用 `Asia/Shanghai`。
9. 磁盘阈值、重任务互斥和任务恢复进入应用代码。
10. releases/current 原子切换、健康检查和 rollback 可实际演练。
11. 用户级 systemd 与 linger 生效，服务器重启后自动恢复。
12. Nginx、80/443 与服务器其他服务不受影响。

## 目录与发布模型

```text
/home/guagua/apps/kline/
  repo/
  releases/<timestamp>_<commit>/
  current -> releases/<active-release>
  shared/
    data/
    duckdb/kline.duckdb
    duckdb/jobs.duckdb
    parquet/
    jobs/
    logs/
    tmp/
    .env
  scripts/deploy.sh
  scripts/rollback.sh
  scripts/healthcheck.sh
```

代码只写入 release，运行期数据只写入 shared。部署失败不切换 current；回滚只
切换 current，不覆盖 shared。每个 release 保存 commit、依赖版本、迁移版本、
cloudflared 版本和构建时间。

## DuckDB 与任务模型

生产运行固定为一个 Uvicorn worker。FastAPI 进程内包含持久化 JobRunner：网络
请求可使用 2～3 个线程，但所有 DuckDB 写入、Parquet 合并和特征生成经过同一
串行写通道。下载、标签、特征等重任务全局互斥。

禁止 API 与独立 runner 同时写同一 native database，也禁止部署测试连接 shared
生产库。未来需要多进程时，API 只读，唯一独立 runner 承担全部写入；该模式不在
v0.2 范围内。该约束遵循 [DuckDB concurrency 文档](https://duckdb.org/docs/current/connect/concurrency.html)。

任务请求和阶段写入 `jobs.duckdb`。服务启动后将 `running` 任务标记为
`interrupted`，允许用户显式恢复可恢复步骤；不能安全恢复的任务必须重新启动，
不得假装继续。

## Provider 上线 gate

测试必须从目标服务器发起，覆盖：东财 10 只、腾讯 10 只、新浪 3 只、主要指数
和交易日历。记录成功率、平均/P95 耗时、失败分类、空数据、字段缺失和限流。

最低通过标准：东财成功率至少 90%，腾讯至少 80%，新浪可用，指数与交易日历
必须成功，OHLCV 完整。未通过时禁止全市场下载，只允许代表样本，并在降低并发、
本地生成 Parquet 后上传、国内侧采集器或离线 TDX provider 中选择备用方案。

交易日历以独立日历接口为主源；指数推断仅作离线降级并标记
`calendar-inferred`，不得形成循环新鲜度判断。

## Access 安全

Cloudflare Access 保护整个公网域名。FastAPI 不能只检查
`Cf-Access-Jwt-Assertion` 是否存在，而要从团队域 JWKS 验证签名，并校验 issuer、
application AUD、时间声明和邮箱 allowlist。验证方法遵循
[Cloudflare Access JWT 文档](https://developers.cloudflare.com/cloudflare-one/identity/authorization-cookie/validating-json/)。

生产环境拒绝未验证的 `/api/*` 请求。应用只监听 localhost；公网访问
`154.53.75.101:8800` 必须失败。源站直连即使伪造 Access 请求头也必须返回 403。

## schema 与测试隔离

数据库记录 `schemaVersion`、`migrationVersion` 和 `migrationLog`。自动迁移只允许
新增表、列、索引或 view；删除、重命名或改变字段语义必须人工确认并先备份。

部署测试目录固定为 `/tmp/kline_deploy_test_<timestamp>/`，设置独立的
`KLINE_ENV=test`、`KLINE_DATA_PATH` 和数据库路径。迁移先在临时数据库预检，确认
向后兼容后才能应用到 shared 数据库。

## 资源与磁盘保护

服务器现状为 Ubuntu 22.04、约 4GB 内存、36GB 可用磁盘，80/443 已由 Nginx
占用。应用和 Tunnel 使用 `guagua` 用户服务，设置 `NoNewPrivileges`、自动重启、
任务数限制和约 70% 内存上限。

磁盘规则：可用空间低于 12GB 告警；低于 8GB 禁止全市场下载；低于 5GB 禁止新
下载和派生任务。DiskGuard 在任务启动、分段下载、Parquet 写入和 DuckDB merge
前检查当前空间、任务预估、已预留空间和安全水位，失败返回
`409 DISK_SPACE_LOW`。

## 发布与回滚

发布顺序：检查 Git 与 secrets、检查 provider gate 缓存、确认无运行中重任务、
创建 release、安装依赖、构建前端、在临时库执行测试和迁移预检、执行兼容迁移、
写 release manifest、原子切换 current、重启单 worker 服务、检查 `/healthz`。

健康检查失败时立即切回上一 current 并重启。部署不自动回滚 shared schema；因此
只有向后兼容迁移允许进入自动流程。部署期间先关闭新任务入口，等待运行任务结束，
再依次构建、测试和切换，避免 npm build 与重查询争抢内存。

## 验收标准

- 未登录访问被 Cloudflare Access 拦截，授权邮箱可登录。
- 伪造头、错误 AUD 和无 JWT 请求均返回 403。
- FastAPI 只监听 `127.0.0.1:8800`，Uvicorn 只有一个 worker。
- Provider gate 达标；代表样本下载、P1 标签和 P2 特征成功。
- 重启服务后 shared 数据保留，中断任务状态可审计。
- 测试日志证明未连接生产 shared 数据库。
- 模拟低磁盘触发对应任务限制。
- release 回滚演练成功，旧代码能读取兼容 schema。
- Nginx 与原有端口、服务保持正常。

## 实施顺序

第一阶段只实施并运行 provider 可达性探针，以及单写者/任务模型测试。两项 gate
通过并经确认后，才实施 Access JWT、DiskGuard、持久任务、静态同域服务、原子
发布脚本、用户服务和 Cloudflare Tunnel。
