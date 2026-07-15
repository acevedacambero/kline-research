import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";

describe("App", () => {
  afterEach(() => {
    cleanup();
    window.history.replaceState(null, "", "/");
  });
  it("shows data status and P1 audit workspace", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({
        ok: true,
        json: async () => ({
          status: "ok",
          dataSource: "AkShare",
          cachePath: "data",
          versions: {},
        }),
      })),
    );
    render(<App />);
    expect(await screen.findByText("数据状态")).toBeInTheDocument();
    expect(screen.getByText("P1 标签审计台")).toBeInTheDocument();
    expect(screen.getByLabelText("证券代码")).toBeInTheDocument();
    expect(screen.getByText("P2 特征审计")).toBeInTheDocument();
    expect(screen.getByText("P3 结构评分")).toBeInTheDocument();
    expect(
      screen.getAllByRole("option", { name: "P20 可执行顺延卖出" }),
    ).toHaveLength(4);
    expect(
      screen.getAllByRole("option", { name: "P5 可执行顺延卖出" }),
    ).toHaveLength(4);
  });

  it("restores audit inputs from a bookmarked URL", async () => {
    window.history.replaceState(
      null,
      "",
      "/?exchange=sz&code=000001&signalDate=2025-01-02#p1-auditor",
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => ({
        ok: true,
        json: async () =>
          String(input).startsWith("/api/tasks/recent")
            ? []
            : String(input).includes("/quality")
              ? { totalCached: 0 }
              : {
                  status: "ok",
                  dataSource: "AkShare",
                  cachePath: "data",
                  versions: {},
                },
      })),
    );

    render(<App />);

    expect(await screen.findByDisplayValue("000001")).toBeInTheDocument();
    expect(screen.getByDisplayValue("2025-01-02")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "交易所" })).toHaveValue("sz");
  });

  it("selects the latest signal date with a mature P60 window", async () => {
    const bars = Array.from({ length: 312 }, (_, index) => {
      const date = new Date(Date.UTC(2024, 0, 1 + index))
        .toISOString()
        .slice(0, 10);
      return {
        date,
        open: 10,
        high: 11,
        low: 9,
        close: 10,
        open_qfq: 10,
        high_qfq: 11,
        low_qfq: 9,
        close_qfq: 10,
        volume: 1000,
      };
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        const body =
          path === "/api/securities/sh/600000/bars"
            ? bars
            : path.startsWith("/api/tasks/recent")
              ? []
              : path.includes("/quality")
                ? { totalCached: 1 }
                : {
                    status: "ok",
                    dataSource: "AkShare",
                    cachePath: "data",
                    versions: {},
                  };
        return { ok: true, json: async () => body };
      }),
    );

    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "选择最近 P60 成熟日" }),
    );

    const expectedDate = bars[250].date;
    expect(await screen.findByDisplayValue(expectedDate)).toBeInTheDocument();
    expect(
      screen.getByText(
        `已选择最近 P60 成熟日 ${expectedDate}，可点击“计算并审计”`,
      ),
    ).toBeInTheDocument();
    expect(window.location.search).toContain(`signalDate=${expectedDate}`);
  });

  it("shows actionable data quality examples", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => ({
        ok: true,
        json: async () =>
          String(input).includes("/quality")
            ? {
                totalCached: 2,
                staleSecurities: 1,
                unreadableSecurities: 1,
                approximateFactorSecurities: 1,
                historyBackfillFailed: 1,
                shortHistoryCached: 2,
                listingHistoryShort: 1,
                staleExamples: [
                  { security: "sh600000", latestDate: "2026-07-01" },
                ],
                unreadableExamples: ["sz000001: broken parquet"],
                approximateFactorExamples: ["stock:sh:689009"],
                qualityEvents: [
                  {
                    dataset_key: "stock:sh:689009",
                    event_type: "factor-approximation",
                    severity: "warning",
                    message: "新浪复权因子不可用，已使用单位因子",
                    created_at: "2026-07-15T12:00:00Z",
                  },
                ],
              }
            : {
                status: "ok",
                dataSource: "AkShare",
                cachePath: "data",
                versions: {},
              },
      })),
    );

    render(<App />);

    expect(await screen.findByText("数据质量明细")).toBeInTheDocument();
    expect(screen.getByText(/sh600000\(2026-07-01\)/)).toBeInTheDocument();
    expect(screen.getByText(/sz000001: broken parquet/)).toBeInTheDocument();
    expect(screen.getAllByText(/stock:sh:689009/).length).toBeGreaterThan(0);
    expect(
      screen.getByText("新浪复权因子不可用，已使用单位因子"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "导出完整质量报告 JSON" }),
    ).toBeInTheDocument();
  });

  it("shows provider gate metrics and blocking reasons", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        let body: unknown = {
          status: "ok",
          dataSource: "AkShare",
          cachePath: "data",
          versions: {},
        };
        if (path === "/api/system/provider-gate")
          body = {
            available: true,
            maxAgeHours: 24,
            diagnosticAvailable: false,
            diagnostic: null,
            report: {
              gateVersion: "sh-sz-provider-g2-v2",
              passed: false,
              probedAt: "2026-07-16T08:00:00+08:00",
              reasons: ["Tencent stock checks did not meet the 80% threshold."],
              warnings: ["EastMoney diagnostics failed."],
              requiredChecks: { tencentStocks: false, tradingCalendar: true },
              diagnosticChecks: { eastmoney: false },
              providers: {
                tencent: {
                  observations: 10,
                  successes: 7,
                  success_rate: 0.7,
                  mean_latency_seconds: 0.42,
                  p95_latency_seconds: 1.25,
                  empty_response_count: 1,
                  missing_field_count: 0,
                  error_categories: { network: 2 },
                },
              },
            },
          };
        else if (path.startsWith("/api/tasks/recent")) body = [];
        else if (path.includes("/quality")) body = { totalCached: 0 };
        return { ok: true, json: async () => body };
      }),
    );

    render(<App />);

    fireEvent.click(await screen.findByText("数据源上线 Gate 明细"));
    expect(screen.getByText("腾讯股票")).toBeInTheDocument();
    expect(screen.getByText("70.00%")).toBeInTheDocument();
    expect(screen.getByText("1.25 秒")).toBeInTheDocument();
    expect(screen.getByText("× 腾讯沪深股票")).toBeInTheDocument();
    expect(screen.getByText(/阻断：Tencent stock checks/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "导出 Gate 完整报告 JSON" }),
    ).toBeInTheDocument();
  });

  it("shows every research readiness check and blocker", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        let body: unknown = {
          status: "ok",
          dataSource: "AkShare",
          cachePath: "data",
          versions: {},
        };
        if (path === "/api/system/readiness")
          body = {
            version: "research-readiness-v1",
            readyForRefresh: true,
            readyForAudit: true,
            readyForModel: false,
            freshnessCoverage: 0.98,
            freshnessMinCoverage: 0.95,
            providerGateAgeHours: 2.5,
            providerGateMaxAgeHours: 24,
            checks: {
              providerGate: true,
              marketDataFresh: true,
              labelsCurrent: false,
              featuresReady: false,
            },
            blockers: ["存在旧版本 P1 标签", "P2 特征覆盖尚未达到训练门槛"],
          };
        else if (path.startsWith("/api/tasks/recent")) body = [];
        else if (path.includes("/quality")) body = { totalCached: 0 };
        return { ok: true, json: async () => body };
      }),
    );

    render(<App />);

    fireEvent.click(await screen.findByText("研究运行 Gate 明细"));
    expect(screen.getByText("98.00%")).toBeInTheDocument();
    expect(screen.getByText("2.5 小时")).toBeInTheDocument();
    expect(screen.getByText("✓ 行情覆盖新鲜")).toBeInTheDocument();
    expect(screen.getByText("× P1 标签版本最新")).toBeInTheDocument();
    expect(screen.getByText("阻断：存在旧版本 P1 标签")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "导出研究 Gate 报告 JSON" }),
    ).toBeInTheDocument();
  });

  it("renders persisted P7 model registry artifacts", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => ({
        ok: true,
        json: async () =>
          String(input).includes("/api/model/p7/registry")
            ? {
                version: "p7-model-registry-v1",
                unreadableFiles: 0,
                artifacts: [
                  {
                    modelId: "model-20260715-a",
                    kind: "multifeature",
                    createdAt: "2026-07-15T12:00:00Z",
                    status: "ready",
                    labelColumn: "p20_executable_return",
                    version: "p7-multifeature-logistic-v1",
                    artifactPath: "/models/a.json",
                    dependencies: {},
                  },
                ],
              }
            : String(input).includes("/quality")
              ? { totalCached: 0 }
              : {
                  status: "ok",
                  dataSource: "AkShare",
                  cachePath: "data",
                  versions: {},
                },
      })),
    );

    render(<App />);

    expect(await screen.findByText("P2/P3 多特征基线")).toBeInTheDocument();
    expect(screen.getAllByText("P20 计划收盘卖出").length).toBeGreaterThan(4);
    expect(screen.getByText("model-20260715-a")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "导出注册表 CSV" }),
    ).toBeInTheDocument();
  });

  it("does not reuse an old provider gate result when a new probe fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input);
        let body: unknown = {
          status: "ok",
          dataSource: "AkShare",
          cachePath: "data",
          versions: {},
        };
        if (
          path === "/api/system/provider-gate/probe?quick=false" &&
          init?.method === "POST"
        )
          body = { taskId: "probe-failed", quick: false };
        else if (path === "/api/tasks/probe-failed")
          body = {
            id: "probe-failed",
            jobType: "provider_probe",
            status: "failed",
            done: 0,
            total: 1,
            errors: [{ message: "network timeout" }],
          };
        else if (path === "/api/system/provider-gate")
          body = {
            available: true,
            report: { passed: true, gateVersion: "old" },
            diagnosticAvailable: false,
            diagnostic: null,
            maxAgeHours: 24,
          };
        else if (path.includes("/quality")) body = { totalCached: 0 };
        return { ok: true, json: async () => body };
      }),
    );

    render(<App />);
    fireEvent.click(
      await screen.findByRole("button", { name: "执行数据源上线 Gate" }),
    );

    expect(
      await screen.findByText(/数据源探测失败：network timeout/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("数据源上线 Gate 已通过"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByText("查看全部 1 条错误"));
    expect(
      screen.getByRole("button", { name: "导出错误 CSV" }),
    ).toBeInTheDocument();
  });

  it("restores the most recent durable task after reload", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        const body = path.startsWith("/api/tasks/recent")
          ? [
              {
                id: "durable-1",
                jobType: "labels",
                status: "completed",
                done: 3,
                total: 3,
                rows: 900,
                errors: [],
              },
            ]
          : path === "/api/tasks/durable-1"
            ? {
                id: "durable-1",
                jobType: "labels",
                status: "completed_with_errors",
                done: 3,
                total: 3,
                rows: 901,
                createdAt: "2026-07-16T01:00:00Z",
                updatedAt: "2026-07-16T01:02:05Z",
                resumable: true,
                errors: [{ security: "sh600000", message: "detail failure" }],
              }
            : path.includes("/quality")
              ? { totalCached: 2 }
              : {
                  status: "ok",
                  dataSource: "AkShare",
                  cachePath: "data",
                  versions: {},
                };
        return { ok: true, json: async () => body };
      }),
    );

    render(<App />);

    expect(await screen.findByText("任务 ID durable-1")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "P1 标签" }),
    ).toBeInTheDocument();
    expect(screen.getByText("生成 900 行")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "最近任务历史" }),
    ).toBeInTheDocument();
    expect(screen.getByText("durable-1")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "查看任务 durable-1" }));
    expect(
      await screen.findByText("已载入任务 durable-1 的完整记录"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("完成（有错误）", { selector: "span.message" }),
    ).toBeInTheDocument();
    expect(screen.getByText("生成 901 行")).toBeInTheDocument();
    expect(screen.getByText("历时 2 分 5 秒")).toBeInTheDocument();
    expect(screen.getByText("支持中断续跑")).toBeInTheDocument();
    fireEvent.click(screen.getByText("查看全部 1 条错误"));
    expect(screen.getByText("sh600000：detail failure")).toBeInTheDocument();
  });

  it("resumes an interrupted task directly from task history", async () => {
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const path = String(input);
        let body: unknown = {
          status: "ok",
          dataSource: "AkShare",
          cachePath: "data",
          versions: {},
        };
        if (path.startsWith("/api/tasks/recent"))
          body = [
            {
              id: "resume-feature",
              jobType: "features",
              status: "interrupted",
              resumable: true,
              createdAt: "2026-07-16T01:00:00Z",
              updatedAt: "2026-07-16T01:01:00Z",
              done: 2,
              total: 10,
              rows: 40,
              errors: [],
            },
            {
              id: "completed-label",
              jobType: "labels",
              status: "completed",
              resumable: true,
              createdAt: "2026-07-15T01:00:00Z",
              updatedAt: "2026-07-15T01:10:00Z",
              done: 5,
              total: 5,
              rows: 80,
              errors: [],
            },
          ];
        else if (path === "/api/features/build" && init?.method === "POST")
          body = { taskId: "resume-feature", total: 10 };
        else if (path === "/api/features/tasks/resume-feature")
          body = {
            status: "completed",
            done: 10,
            total: 10,
            rows: 120,
            errors: [],
          };
        else if (path.includes("/quality")) body = { totalCached: 2 };
        return { ok: true, json: async () => body };
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    expect(await screen.findByText("completed-label")).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText("筛选任务类型"), {
      target: { value: "features" },
    });
    expect(screen.queryByText("completed-label")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "导出任务历史 CSV" }),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "续跑任务 resume-feature" }),
    );

    expect(await screen.findByText("生成 120 行")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/features/build",
      expect.objectContaining({ method: "POST" }),
    );
    expect(screen.getByText("任务 ID resume-feature")).toBeInTheDocument();
  });

  it("renders five P2 groups and explains unavailable history", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        const body = path.includes("/api/p2/audit")
          ? {
              groups: {
                trend: { ma60: null },
                position: {},
                momentum: {},
                volumePrice: {},
                tradingBehavior: {
                  is_approx: true,
                  rule_reason: "board/date rule",
                },
              },
              availableHistory: 20,
              versions: {
                snapshotVersion: "snapshot-1",
                factorVersion: "factor-1",
                limitRuleVersion: "rule-1",
                featureDefinitionVersion: "feature-1",
              },
              priceBasis: "raw+qfq+total-return",
              reasons: ["limit-rule-approx"],
            }
          : path.includes("/api/p3/audit")
            ? {
                availableHistory: 20,
                featureDefinitionVersion: "daily-features-v1",
                priceBasis: "raw+qfq+total-return",
                score: {
                  version: "p3-rule-score-v1",
                  score: 72.5,
                  grade: "B",
                  usable: true,
                  reasons: ["available_history<120"],
                  components: {
                    trend: {
                      score: 20,
                      weight: 25,
                      available: true,
                      reasons: ["多头均线排列"],
                    },
                    position: {
                      score: 15,
                      weight: 20,
                      available: true,
                      reasons: [],
                    },
                    momentum: {
                      score: 18,
                      weight: 25,
                      available: true,
                      reasons: [],
                    },
                    volumePrice: {
                      score: 10,
                      weight: 15,
                      available: true,
                      reasons: [],
                    },
                    tradingBehavior: {
                      score: 9.5,
                      weight: 15,
                      available: true,
                      reasons: [],
                    },
                  },
                },
                versions: {},
              }
            : path.includes("/api/p1/audit")
              ? {
                  eligibility: {
                    eligible: false,
                    status: "insufficient-history",
                    reasons: ["insufficient-history"],
                  },
                  entry: {
                    status: "abandoned",
                    entry_reason: "entry blocked through T+3",
                  },
                  labels: {},
                  path: { success: false, reason: "same-day-double-hit" },
                }
              : path.includes("/bars")
                ? []
                : path.includes("/quality")
                  ? { totalCached: 1 }
                  : {
                      status: "ok",
                      dataSource: "AkShare",
                      cachePath: "data",
                      versions: {},
                    };
        return { ok: true, json: async () => body };
      }),
    );
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "计算并审计" }));
    expect((await screen.findAllByText("趋势")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("位置").length).toBeGreaterThan(0);
    expect(screen.getAllByText("动量").length).toBeGreaterThan(0);
    expect(screen.getAllByText("量价").length).toBeGreaterThan(0);
    expect(screen.getAllByText("交易行为").length).toBeGreaterThan(0);
    expect(screen.getByText("历史不足")).toBeInTheDocument();
    expect(screen.getByText("交易规则是否近似")).toBeInTheDocument();
    expect(
      screen.getByText("按交易所、板块和日期适用正式涨跌幅规则"),
    ).toBeInTheDocument();
    expect(screen.getByText("交易规则使用了近似状态")).toBeInTheDocument();
    expect(screen.getByText(/有效历史不足 120 个交易日/)).toBeInTheDocument();
    expect(screen.getByText(/数据快照：snapshot-1/)).toBeInTheDocument();
    expect(screen.getByText("72.5")).toBeInTheDocument();
    expect(screen.getByText(/p3-rule-score-v1/)).toBeInTheDocument();
    expect(screen.getAllByText("历史不足 250 个交易日").length).toBeGreaterThan(
      0,
    );
    expect(screen.getByText("连续受阻，已放弃")).toBeInTheDocument();
    expect(screen.getByText("T+1 至 T+3 均无法买入")).toBeInTheDocument();
    expect(
      screen.getByText("同日同时触及止盈和止损，保守判失败"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "导出当前审计报告 JSON" }),
    ).toBeInTheDocument();
    expect(window.location.search).toContain("exchange=sh");
    expect(window.location.search).toContain("code=600000");
    expect(window.location.hash).toBe("#p1-auditor");
  });

  it("offers Shanghai and Shenzhen markets only", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => ({
        ok: true,
        json: async () =>
          String(input).includes("/quality")
            ? { totalCached: 0 }
            : {
                status: "ok",
                dataSource: "Tencent/Sina",
                cachePath: "data",
                versions: {},
              },
      })),
    );

    const { container } = render(<App />);
    await screen.findByRole("heading", { level: 1 });
    const exchangeSelect = screen.getByLabelText("交易所") as HTMLSelectElement;

    expect(
      Array.from(exchangeSelect.options).map((option) => option.value),
    ).toEqual(["sh", "sz"]);
    expect(container.querySelector('option[value="bj"]')).toBeNull();
    expect(
      screen.getByRole("button", { name: "重试下载错误" }),
    ).toBeInTheDocument();
    const workflow = screen.getByRole("navigation", { name: "研究流程导航" });
    expect(workflow.querySelector('a[href="#p1-auditor"]')).toHaveTextContent(
      "P1 标签",
    );
    expect(workflow.querySelector('a[href="#p8-portfolio"]')).toHaveTextContent(
      "P8 组合",
    );
  });

  it("starts history backfill and renders its terminal summary", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const body =
        path === "/api/datasets/import"
          ? { taskId: "task-1", total: 5, threshold: 250 }
          : path === "/api/datasets/backfill-history/task-1"
            ? {
                status: "completed_with_errors",
                done: 5,
                total: 5,
                completed: 3,
                listingHistoryShort: 1,
                errors: [{ security: "sh600000" }],
                currentSecurity: null,
                speed: 2,
                etaSeconds: 0,
              }
            : path.includes("/quality")
              ? { totalCached: 5 }
              : {
                  status: "ok",
                  dataSource: "AkShare",
                  cachePath: "data",
                  versions: {},
                };
      return { ok: true, json: async () => body };
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    fireEvent.click(await screen.findByRole("button", { name: "补全短历史" }));

    expect(
      await screen.findByText(/已补全 3 · 新股 1 · 错误 1/),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/检查错误后，再手动生成 P1 和 P2/),
    ).toBeInTheDocument();
    expect(screen.getByText("sh600000")).toBeInTheDocument();
  });

  it("searches securities by name and switches to the selected exchange", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        const body = path.startsWith("/api/securities?query=")
          ? [{ exchange: "sz", code: "000001", name: "平安银行" }]
          : path.includes("/quality")
            ? { totalCached: 1 }
            : {
                status: "ok",
                dataSource: "AkShare",
                cachePath: "data",
                versions: {},
              };
        return { ok: true, json: async () => body };
      }),
    );
    render(<App />);
    const input = screen.getByLabelText("证券代码");

    fireEvent.change(input, { target: { value: "平安" } });
    await waitFor(() =>
      expect(
        document.querySelector('option[value="000001"]'),
      ).toHaveTextContent("平安银行 · 深圳"),
    );
    fireEvent.change(input, { target: { value: "000001" } });

    expect(screen.getByLabelText("交易所")).toHaveValue("sz");
  });

  it("starts P3 score build and polls progress", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const body =
        path === "/api/scores/build"
          ? { taskId: "score-task-1", total: 2 }
          : path === "/api/scores/tasks/score-task-1"
            ? { status: "completed", done: 2, total: 2, rows: 520, errors: [] }
            : path.includes("/quality")
              ? { totalCached: 2 }
              : {
                  status: "ok",
                  dataSource: "AkShare",
                  cachePath: "data",
                  versions: {},
                };
      return { ok: true, json: async () => body };
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    fireEvent.click(
      await screen.findByRole("button", { name: "生成 P3 评分" }),
    );

    expect(
      await screen.findByText(/P3 评分：2\/2，已生成 520 行/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("任务进度")).toBeInTheDocument();
    expect(screen.getByText("任务 ID score-task-1")).toBeInTheDocument();
    expect(screen.getByText("生成 520 行")).toBeInTheDocument();
  });

  it("runs P4 single factor validation and renders bucket metrics", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const body =
        path === "/api/validation/single-factor"
          ? {
              version: "p4-single-factor-v2-independent",
              factorColumn: "score",
              labelColumn: "p20_executable_return",
              bucketCount: 2,
              sampleCount: 10,
              independentPeriodCount: 4,
              independenceGapDays: 7,
              rankCorrelation: 0.42,
              missingColumns: [],
              dropped: {},
              buckets: [
                {
                  bucket: 1,
                  count: 5,
                  minFactor: 1,
                  maxFactor: 50,
                  avgFactor: 25,
                  avgLabel: 0.01,
                  medianLabel: 0.01,
                  winRate: 0.6,
                  pathSuccessRate: 0.4,
                  avgMaxDrawdown: -0.08,
                },
                {
                  bucket: 2,
                  count: 5,
                  minFactor: 51,
                  maxFactor: 90,
                  avgFactor: 70,
                  avgLabel: 0.08,
                  medianLabel: 0.07,
                  winRate: 0.8,
                  pathSuccessRate: 0.7,
                  avgMaxDrawdown: -0.05,
                },
              ],
            }
          : path.includes("/quality")
            ? { totalCached: 2 }
            : {
                status: "ok",
                dataSource: "AkShare",
                cachePath: "data",
                versions: {},
              };
      return { ok: true, json: async () => body };
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<App />);

    fireEvent.click(
      await screen.findByRole("button", { name: "验证 P4 单因子" }),
    );

    expect(
      await screen.findByText("p4-single-factor-v2-independent"),
    ).toBeInTheDocument();
    expect(screen.getByText("10 / 4")).toBeInTheDocument();
    expect(screen.getByText("8.00%")).toBeInTheDocument();
  });
});
