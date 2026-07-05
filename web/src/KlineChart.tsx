import { useEffect, useRef } from 'react'
import { CandlestickSeries, ColorType, HistogramSeries, LineSeries, createChart } from 'lightweight-charts'
import type { Bar } from './api'

export function KlineChart({ bars }: { bars: Bar[] }) {
  const host = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!host.current || !bars.length) return
    const chart = createChart(host.current, {
      height: 430, layout: { background: { type: ColorType.Solid, color: '#10161f' }, textColor: '#93a4b8' },
      grid: { vertLines: { color: '#1d2835' }, horzLines: { color: '#1d2835' } },
      rightPriceScale: { borderColor: '#263446' }, timeScale: { borderColor: '#263446' },
    })
    const candles = chart.addSeries(CandlestickSeries, { upColor: '#ef5350', downColor: '#26a69a', borderVisible: false, wickUpColor: '#ef5350', wickDownColor: '#26a69a' })
    candles.setData(bars.map(b => ({ time: b.date, open: b.open_qfq, high: b.high_qfq, low: b.low_qfq, close: b.close_qfq })))
    const volume = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: 'volume', color: '#506178' })
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } })
    volume.setData(bars.map(b => ({ time: b.date, value: b.volume, color: b.close_qfq >= b.open_qfq ? '#ef535080' : '#26a69a80' })))
    const colors = ['#ffd166', '#f78c6c', '#82aaff', '#c792ea']
    ;([5, 10, 20, 60] as const).forEach((period, index) => {
      const line = chart.addSeries(LineSeries, { color: colors[index], lineWidth: 1, title: `MA${period}` })
      line.setData(bars.filter(b => b[`ma${period}`] != null).map(b => ({ time: b.date, value: b[`ma${period}`] as number })))
    })
    chart.timeScale().fitContent()
    const observer = new ResizeObserver(entries => chart.applyOptions({ width: entries[0].contentRect.width }))
    observer.observe(host.current)
    return () => { observer.disconnect(); chart.remove() }
  }, [bars])
  return <div className="chart" ref={host} aria-label="前复权K线图" />
}
