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
  afterEach(() => cleanup());
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
                tradingBehavior: {},
              },
              availableHistory: 20,
              versions: {},
              priceBasis: "raw+qfq+total-return",
              reasons: [],
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
                  reasons: [],
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
                  eligibility: { eligible: true, status: "ok", reasons: [] },
                  entry: { status: "normal" },
                  labels: {},
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
    expect(screen.getByText("72.5")).toBeInTheDocument();
    expect(screen.getByText(/p3-rule-score-v1/)).toBeInTheDocument();
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
