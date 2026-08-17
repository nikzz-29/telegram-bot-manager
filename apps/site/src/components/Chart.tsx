import { useMemo } from "react";
import type { Point } from "../types";

type Metric = "messages" | "active_users" | "joins" | "moderation_actions";
const labels: Record<Metric, string> = { messages: "Messages", active_users: "Active users", joins: "Joins", moderation_actions: "Moderation" };

export function Chart({ series, metric }: { series: Point[]; metric: Metric }): React.JSX.Element {
  const width = 760, height = 250, pad = { l: 18, r: 18, t: 22, b: 34 };
  const values = series.map((point) => point[metric]);
  const max = Math.max(1, ...values);
  const points = useMemo(() => series.map((point, index) => {
    const x = pad.l + (series.length <= 1 ? (width - pad.l - pad.r) / 2 : index / (series.length - 1) * (width - pad.l - pad.r));
    const y = pad.t + (height - pad.t - pad.b) * (1 - point[metric] / max);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }), [series, metric, max]);
  const line = points.join(" ");
  const area = points.length ? `${pad.l},${height-pad.b} ${line} ${width-pad.r},${height-pad.b}` : "";
  return <div className="chart-wrap" aria-label={labels[metric]}>
    <div className="chart-caption"><span>{labels[metric]}</span><strong>{values.reduce((a, b) => a + b, 0).toLocaleString()}</strong></div>
    {series.length ? <svg viewBox={`0 0 ${width} ${height}`} role="img" className="line-chart" preserveAspectRatio="none">
      <g className="chart-grid">{[0, .5, 1].map((step) => <line key={step} x1={pad.l} x2={width-pad.r} y1={pad.t+(height-pad.t-pad.b)*step} y2={pad.t+(height-pad.t-pad.b)*step} />)}</g>
      <polygon points={area} className="chart-area" />
      <polyline points={line} className="chart-line" pathLength="1" />
      {points.map((point, index) => <circle key={`${point}-${index}`} cx={point.split(",")[0]} cy={point.split(",")[1]} r="3" className="chart-point" style={{ animationDelay: `${index * 22}ms` }} />)}
      <text x={pad.l} y={height-10}>{series[0]?.date}</text><text x={width-pad.r} y={height-10} textAnchor="end">{series.at(-1)?.date}</text>
    </svg> : <div className="chart-empty">No activity for this period</div>}
  </div>;
}
