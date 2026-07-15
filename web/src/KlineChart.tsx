import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  createChart,
  createSeriesMarkers,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import type { Bar } from "./api";

export type ChartEvents = {
  signalDate?: string;
  entryDate?: string | null;
  plannedExitDate?: string | null;
  actualExitDate?: string | null;
  pathHitDate?: string | null;
  pathFailDate?: string | null;
  drawdownPeakDate?: string | null;
  drawdownTroughDate?: string | null;
};

export function KlineChart({
  bars,
  events = {},
}: {
  bars: Bar[];
  events?: ChartEvents;
}) {
  const host = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!host.current || !bars.length) return;
    const chart = createChart(host.current, {
      height: 430,
      layout: {
        background: { type: ColorType.Solid, color: "#10161f" },
        textColor: "#93a4b8",
      },
      grid: {
        vertLines: { color: "#1d2835" },
        horzLines: { color: "#1d2835" },
      },
      rightPriceScale: { borderColor: "#263446" },
      timeScale: { borderColor: "#263446" },
    });
    const candles = chart.addSeries(CandlestickSeries, {
      upColor: "#ef5350",
      downColor: "#26a69a",
      borderVisible: false,
      wickUpColor: "#ef5350",
      wickDownColor: "#26a69a",
    });
    candles.setData(
      bars.map((b) => ({
        time: b.date,
        open: b.open_qfq,
        high: b.high_qfq,
        low: b.low_qfq,
        close: b.close_qfq,
      })),
    );
    const markers: SeriesMarker<Time>[] = [];
    const addMarker = (
      time: string | null | undefined,
      position: "aboveBar" | "belowBar" | "inBar",
      color: string,
      shape: "circle" | "square" | "arrowUp" | "arrowDown",
      text: string,
    ) => {
      if (time && bars.some((bar) => bar.date === time))
        markers.push({ time: time as Time, position, color, shape, text });
    };
    addMarker(events.signalDate, "aboveBar", "#ffd166", "circle", "信号");
    addMarker(events.entryDate, "belowBar", "#55d6be", "arrowUp", "买入");
    addMarker(
      events.plannedExitDate,
      "aboveBar",
      "#82aaff",
      "square",
      "计划卖出",
    );
    addMarker(
      events.actualExitDate,
      "aboveBar",
      "#ef5350",
      "arrowDown",
      "实际卖出",
    );
    addMarker(events.pathHitDate, "aboveBar", "#55d6be", "circle", "路径成功");
    addMarker(events.pathFailDate, "belowBar", "#ef5350", "circle", "路径失败");
    addMarker(
      events.drawdownPeakDate,
      "aboveBar",
      "#c792ea",
      "circle",
      "回撤峰值",
    );
    addMarker(
      events.drawdownTroughDate,
      "belowBar",
      "#f78c6c",
      "circle",
      "回撤谷值",
    );
    markers.sort((left, right) =>
      String(left.time).localeCompare(String(right.time)),
    );
    createSeriesMarkers(candles, markers);
    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: "volume" },
      priceScaleId: "volume",
      color: "#506178",
    });
    volume
      .priceScale()
      .applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volume.setData(
      bars.map((b) => ({
        time: b.date,
        value: b.volume,
        color: b.close_qfq >= b.open_qfq ? "#ef535080" : "#26a69a80",
      })),
    );
    const colors = ["#ffd166", "#f78c6c", "#82aaff", "#c792ea"];
    ([5, 10, 20, 60] as const).forEach((period, index) => {
      const line = chart.addSeries(LineSeries, {
        color: colors[index],
        lineWidth: 1,
        title: `MA${period}`,
      });
      line.setData(
        bars
          .filter((b) => b[`ma${period}`] != null)
          .map((b) => ({ time: b.date, value: b[`ma${period}`] as number })),
      );
    });
    const signalIndex = events.signalDate
      ? bars.findIndex((bar) => bar.date === events.signalDate)
      : -1;
    if (signalIndex >= 0) {
      chart.timeScale().setVisibleLogicalRange({
        from: Math.max(0, signalIndex - 80),
        to: Math.min(bars.length - 1, signalIndex + 80),
      });
    } else {
      chart.timeScale().fitContent();
    }
    const observer = new ResizeObserver((entries) =>
      chart.applyOptions({ width: entries[0].contentRect.width }),
    );
    observer.observe(host.current);
    return () => {
      observer.disconnect();
      chart.remove();
    };
  }, [
    bars,
    events.signalDate,
    events.entryDate,
    events.plannedExitDate,
    events.actualExitDate,
    events.pathHitDate,
    events.pathFailDate,
    events.drawdownPeakDate,
    events.drawdownTroughDate,
  ]);
  const eventLegend = [
    { date: events.signalDate, kind: "signal", label: "信号日" },
    { date: events.entryDate, kind: "entry", label: "实际买入" },
    { date: events.plannedExitDate, kind: "planned-exit", label: "计划卖出" },
    { date: events.actualExitDate, kind: "actual-exit", label: "实际卖出" },
    { date: events.pathHitDate, kind: "path-hit", label: "路径成功" },
    { date: events.pathFailDate, kind: "path-fail", label: "路径失败" },
    { date: events.drawdownPeakDate, kind: "drawdown-peak", label: "回撤峰值" },
    {
      date: events.drawdownTroughDate,
      kind: "drawdown-trough",
      label: "回撤谷值",
    },
  ].filter((item) => Boolean(item.date));
  return (
    <figure className="kline-figure" aria-label="前复权 K 线审计图">
      <figcaption className="kline-caption">
        <div>
          <span>前复权 K 线与成交量</span>
          <strong>{bars.length} 个交易日</strong>
          <small>
            {bars.at(0)?.date ?? "—"} → {bars.at(-1)?.date ?? "—"}
          </small>
        </div>
        <div className="kline-legend" aria-label="K线图例">
          {([5, 10, 20, 60] as const).map((period) => (
            <span key={period}>
              <i className={`ma-key ma-${period}`} />
              MA{period}
            </span>
          ))}
          {eventLegend.map((item) => (
            <span key={`${item.kind}-${item.date}`} title={String(item.date)}>
              <i className={`event-key event-${item.kind}`} />
              {item.label}
            </span>
          ))}
        </div>
      </figcaption>
      <div className="chart" ref={host} aria-label="前复权K线图" />
    </figure>
  );
}
