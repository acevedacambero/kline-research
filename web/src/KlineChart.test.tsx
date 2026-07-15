import { render, screen } from "@testing-library/react";
import { beforeAll, expect, it, vi } from "vitest";

const { markerSpy, visibleRangeSpy } = vi.hoisted(() => ({
  markerSpy: vi.fn(),
  visibleRangeSpy: vi.fn(),
}));

vi.mock("lightweight-charts", () => ({
  CandlestickSeries: {},
  HistogramSeries: {},
  LineSeries: {},
  ColorType: { Solid: "solid" },
  createSeriesMarkers: (_series: unknown, markers: unknown[]) =>
    markerSpy(markers),
  createChart: () => ({
    addSeries: () => ({
      setData: vi.fn(),
      priceScale: () => ({ applyOptions: vi.fn() }),
    }),
    timeScale: () => ({
      fitContent: vi.fn(),
      setVisibleLogicalRange: visibleRangeSpy,
    }),
    applyOptions: vi.fn(),
    remove: vi.fn(),
  }),
}));

import { KlineChart } from "./KlineChart";

beforeAll(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
});

it("marks signal, entry, planned exit and delayed actual exit", () => {
  const bars = Array.from({ length: 4 }, (_, index) => ({
    date: `2024-01-0${index + 2}`,
    open: 10,
    high: 11,
    low: 9,
    close: 10,
    open_qfq: 10,
    high_qfq: 11,
    low_qfq: 9,
    close_qfq: 10,
    volume: 100,
  }));

  render(
    <KlineChart
      bars={bars}
      events={{
        signalDate: "2024-01-02",
        entryDate: "2024-01-03",
        plannedExitDate: "2024-01-04",
        actualExitDate: "2024-01-05",
      }}
    />,
  );

  expect(markerSpy).toHaveBeenCalledWith(
    expect.arrayContaining([
      expect.objectContaining({ time: "2024-01-02", text: "信号" }),
      expect.objectContaining({ time: "2024-01-03", text: "买入" }),
      expect.objectContaining({ time: "2024-01-04", text: "计划卖出" }),
      expect.objectContaining({ time: "2024-01-05", text: "实际卖出" }),
    ]),
  );
  expect(visibleRangeSpy).toHaveBeenCalledWith({ from: 0, to: 3 });
  expect(screen.getByLabelText("前复权 K 线审计图")).toBeInTheDocument();
  expect(screen.getByText("4 个交易日")).toBeInTheDocument();
  expect(screen.getByText("MA60")).toBeInTheDocument();
  expect(screen.getByText("实际买入")).toBeInTheDocument();
  expect(screen.getByText("实际卖出")).toBeInTheDocument();
});
