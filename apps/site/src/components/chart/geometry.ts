import type { Point } from "../../types";

export type ChartMetric = "messages" | "active_users" | "joins" | "moderation_actions";
export type SeriesValue = { date: string; value: number };
export type GeometryPoint = { x: number; y: number; value: number; date: string };

export function getPointRadii(radius: number, width: number, height: number, viewBoxWidth = 100, viewBoxHeight = 88): { rx: number; ry: number } {
  if (width <= 0 || height <= 0 || viewBoxWidth <= 0 || viewBoxHeight <= 0) return { rx: radius, ry: radius };
  const rx = radius * (height / viewBoxHeight) / (width / viewBoxWidth);
  return { rx: Number(rx.toFixed(2)), ry: radius };
}

export function resampleSeries(series: Point[], metric: ChartMetric, count = Math.max(1, series.length)): SeriesValue[] {
  if (!series.length || count <= 0) return [];
  if (series.length === 1) return Array.from({ length: count }, () => ({ date: series[0].date, value: series[0][metric] }));
  const result: SeriesValue[] = [];
  for (let index = 0; index < count; index += 1) {
    const position = index / (count - 1) * (series.length - 1);
    const left = Math.floor(position);
    const right = Math.min(series.length - 1, left + 1);
    const fraction = position - left;
    const value = series[left][metric] + (series[right][metric] - series[left][metric]) * fraction;
    result.push({ date: fraction < 0.5 ? series[left].date : series[right].date, value });
  }
  return result;
}

export function toGeometry(series: Point[], metric: ChartMetric, count = Math.max(1, series.length)): GeometryPoint[] {
  const values = resampleSeries(series, metric, count);
  if (!values.length) return [];
  const max = Math.max(1, ...values.map((point) => point.value));
  return values.map((point, index) => ({
    x: values.length === 1 ? 50 : index / (values.length - 1) * 100,
    y: 100 - point.value / max * 100,
    value: point.value,
    date: point.date,
  }));
}

export function interpolateGeometry(from: GeometryPoint[], to: GeometryPoint[], progress: number): GeometryPoint[] {
  const amount = Math.max(0, Math.min(1, progress));
  const count = Math.max(from.length, to.length);
  return Array.from({ length: count }, (_, index) => {
    const start = from[index] ?? from.at(-1) ?? { x: index, y: 100, value: 0, date: "" };
    const end = to[index] ?? to.at(-1) ?? start;
    return {
      x: start.x + (end.x - start.x) * amount,
      y: start.y + (end.y - start.y) * amount,
      value: start.value + (end.value - start.value) * amount,
      date: amount < 1 ? start.date : end.date,
    };
  });
}
