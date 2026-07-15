type EquityPoint = { date: string; value: number };

export function EquityCurveChart({ points }: { points: EquityPoint[] }) {
  const valid = points.filter(
    (point) => point.date && Number.isFinite(point.value) && point.value > 0,
  );
  if (!valid.length) return null;

  const width = 1000;
  const height = 260;
  const padding = 24;
  const values = valid.map((point) => point.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || Math.max(max * 0.02, 0.01);
  const x = (index: number) =>
    padding + (index / Math.max(1, valid.length - 1)) * (width - padding * 2);
  const y = (value: number) =>
    height - padding - ((value - min) / range) * (height - padding * 2);
  const line = valid
    .map((point, index) => `${x(index)},${y(point.value)}`)
    .join(" ");
  const area = `${padding},${height - padding} ${line} ${width - padding},${height - padding}`;
  const last = valid.at(-1)!;

  return (
    <figure className="equity-chart" aria-label="P8 组合净值曲线">
      <div className="equity-chart-title">
        <div>
          <span>组合净值走势</span>
          <strong>{last.value.toFixed(3)}</strong>
        </div>
        <small>
          {valid[0].date} → {last.date} · 区间 {min.toFixed(3)}–{max.toFixed(3)}
        </small>
      </div>
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label={`净值从 ${valid[0].value.toFixed(3)} 变化到 ${last.value.toFixed(3)}`}
      >
        <line
          x1={padding}
          y1={height - padding}
          x2={width - padding}
          y2={height - padding}
          className="equity-axis"
        />
        <polygon points={area} className="equity-area" />
        <polyline points={line} className="equity-line" />
        <circle
          cx={x(valid.length - 1)}
          cy={y(last.value)}
          r="5"
          className="equity-dot"
        />
      </svg>
    </figure>
  );
}
