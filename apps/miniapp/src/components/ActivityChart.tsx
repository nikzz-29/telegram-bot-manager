import React, { useEffect, useId, useMemo, useState } from "react";
import type { DashboardTotals, StatPoint } from "../api/client";
import { useI18n, useT } from "../i18n/I18nProvider";

export type DashboardMetric =
  | "messages"
  | "active_users"
  | "joins"
  | "leaves"
  | "moderation_actions";

export const DASHBOARD_METRICS: readonly DashboardMetric[] = [
  "messages",
  "active_users",
  "joins",
  "leaves",
  "moderation_actions",
];

const METRIC_COLOR: Record<DashboardMetric, string> = {
  messages: "var(--tg-accent)",
  active_users: "#10b981",
  joins: "#10b981",
  leaves: "#f59e0b",
  moderation_actions: "var(--tg-destructive)",
};

export function metricValue(point: StatPoint, metric: DashboardMetric): number {
  const value = point[metric] ?? 0;
  return Number.isFinite(value) ? Math.max(0, value) : 0;
}

export function totalValue(totals: DashboardTotals, metric: DashboardMetric): number {
  const value = totals[metric] ?? 0;
  return Number.isFinite(value) ? value : 0;
}

export function AnimatedNumber({ value }: { value: number }): React.JSX.Element {
  const [shown, setShown] = useState(value);
  useEffect(() => {
    const start = shown;
    const distance = value - start;
    if (distance === 0 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setShown(value);
      return undefined;
    }
    const started = performance.now();
    const duration = 360;
    let frame = 0;
    const tick = (now: number): void => {
      const progress = Math.min(1, (now - started) / duration);
      const eased = 1 - Math.pow(1 - progress, 3);
      setShown(Math.round(start + distance * eased));
      if (progress < 1) {
        frame = requestAnimationFrame(tick);
      }
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);
  return <>{shown.toLocaleString()}</>;
}

interface ChartPoint {
  x: number;
  y: number;
  value: number;
  date: string;
}

function linePath(points: readonly ChartPoint[]): string {
  if (points.length === 0) {
    return "";
  }
  return points
    .map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(" ");
}

function formatDate(value: string, locale: string): string {
  const date = new Date(`${value}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleDateString(locale, { day: "numeric", month: "short" });
}

export function ActivityChart({
  series,
  metric,
}: {
  series: readonly StatPoint[];
  metric: DashboardMetric;
}): React.JSX.Element {
  const t = useT();
  const { locale } = useI18n();
  const gradientId = `chart-fill-${useId().replace(/:/g, "")}`;
  const width = 360;
  const height = 164;
  const left = 14;
  const right = 8;
  const top = 12;
  const bottom = 30;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const values = useMemo(() => series.map((point) => metricValue(point, metric)), [series, metric]);
  const peak = Math.max(1, ...values);
  const points = useMemo<ChartPoint[]>(
    () =>
      series.map((point, index) => ({
        x: left + (series.length === 1 ? plotWidth / 2 : (index / (series.length - 1)) * plotWidth),
        y: top + plotHeight - (metricValue(point, metric) / peak) * plotHeight,
        value: metricValue(point, metric),
        date: point.date,
      })),
    [metric, peak, plotHeight, plotWidth, series],
  );
  const strokePath = linePath(points);
  const baseline = top + plotHeight;
  const areaPath =
    points.length === 0
      ? ""
      : `M${points[0]!.x.toFixed(2)} ${baseline} ${strokePath.replace(/^M/, "L")} L${points[points.length - 1]!.x.toFixed(2)} ${baseline} Z`;
  const signature = `${metric}:${series.map((point) => `${point.date}-${metricValue(point, metric)}`).join("|")}`;

  if (series.length === 0 || values.every((value) => value === 0)) {
    return (
      <div className="chart-empty flex h-[164px] items-center justify-center text-label text-hint">
        {t("stats-no-data")}
      </div>
    );
  }

  return (
    <svg
      key={signature}
      viewBox={`0 0 ${width} ${height}`}
      className="dashboard-chart h-[164px] w-full"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label={t(`dashboard-metric-${metric.replace(/_/g, "-")}`)}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={METRIC_COLOR[metric]} stopOpacity="0.28" />
          <stop offset="100%" stopColor={METRIC_COLOR[metric]} stopOpacity="0.015" />
        </linearGradient>
      </defs>
      {[0, 0.5, 1].map((position) => {
        const y = top + plotHeight * position;
        return (
          <line
            key={position}
            x1={left}
            y1={y}
            x2={width - right}
            y2={y}
            className="chart-grid-line"
          />
        );
      })}
      <path d={areaPath} fill={`url(#${gradientId})`} className="chart-area" />
      <path
        d={strokePath}
        fill="none"
        stroke={METRIC_COLOR[metric]}
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        pathLength="1"
        className="chart-line"
      />
      {points.map((point, index) => {
        const showPoint = points.length <= 31 || index === points.length - 1;
        return showPoint ? (
          <circle
            key={`${point.date}-${index}`}
            cx={point.x}
            cy={point.y}
            r="3.25"
            fill="var(--panel-card)"
            stroke={METRIC_COLOR[metric]}
            strokeWidth="2"
            className="chart-point"
            style={{ animationDelay: `${180 + Math.min(index, 20) * 18}ms` }}
          >
            <title>{`${formatDate(point.date, locale)}: ${point.value.toLocaleString(locale)}`}</title>
          </circle>
        ) : null;
      })}
      <text x={left} y={height - 7} className="chart-axis-label" textAnchor="start">
        {formatDate(series[0]!.date, locale)}
      </text>
      {series.length > 1 ? (
        <text x={width - right} y={height - 7} className="chart-axis-label" textAnchor="end">
          {formatDate(series[series.length - 1]!.date, locale)}
        </text>
      ) : null}
    </svg>
  );
}
