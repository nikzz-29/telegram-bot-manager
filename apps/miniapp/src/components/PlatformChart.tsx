import React, { useId, useMemo } from "react";
import type { PlatformSeriesPoint } from "../api/client";

export type PlatformMetric =
  | "messages"
  | "new_chats"
  | "active_chats"
  | "moderation_actions"
  | "subscriptions"
  | "revenue_stars";

const COLORS: Record<PlatformMetric, string> = {
  messages: "#3390ec",
  new_chats: "#14b8a6",
  active_chats: "#22c55e",
  moderation_actions: "#f59e0b",
  subscriptions: "#8b5cf6",
  revenue_stars: "#ec4899",
};

function valueOf(point: PlatformSeriesPoint, metric: PlatformMetric): number {
  const value = Number(point[metric] ?? 0);
  return Number.isFinite(value) ? Math.max(0, value) : 0;
}

function dateLabel(value: string, locale: string): string {
  const parsed = new Date(`${value}T00:00:00`);
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleDateString(locale, { day: "numeric", month: "short" });
}

export function PlatformChart({
  series,
  metric,
  locale,
  emptyLabel,
  ariaLabel,
}: {
  series: readonly PlatformSeriesPoint[];
  metric: PlatformMetric;
  locale: string;
  emptyLabel: string;
  ariaLabel: string;
}): React.JSX.Element {
  const gradientId = `platform-chart-${useId().replace(/:/g, "")}`;
  const values = useMemo(() => series.map((point) => valueOf(point, metric)), [metric, series]);
  const peak = Math.max(1, ...values);
  const width = 640;
  const height = 220;
  const left = 20;
  const right = 12;
  const top = 18;
  const bottom = 34;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;
  const points = useMemo(
    () =>
      series.map((point, index) => ({
        x: left + (series.length < 2 ? plotWidth / 2 : (index / (series.length - 1)) * plotWidth),
        y: top + plotHeight - (valueOf(point, metric) / peak) * plotHeight,
        value: valueOf(point, metric),
        day: point.day,
      })),
    [metric, peak, plotHeight, plotWidth, series],
  );
  const path = points
    .map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(" ");
  const baseline = top + plotHeight;
  const area =
    points.length === 0
      ? ""
      : `M${points[0]!.x.toFixed(2)} ${baseline} ${path.replace(/^M/, "L")} L${points[points.length - 1]!.x.toFixed(2)} ${baseline} Z`;
  const signature = `${metric}:${series.map((point) => `${point.day}-${valueOf(point, metric)}`).join("|")}`;

  if (series.length === 0 || values.every((value) => value === 0)) {
    return <div className="platform-chart-empty">{emptyLabel}</div>;
  }

  return (
    <svg
      key={signature}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={ariaLabel}
      className="platform-chart h-[220px] w-full"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={COLORS[metric]} stopOpacity="0.3" />
          <stop offset="100%" stopColor={COLORS[metric]} stopOpacity="0.015" />
        </linearGradient>
      </defs>
      {[0, 0.25, 0.5, 0.75, 1].map((position) => (
        <line
          key={position}
          x1={left}
          x2={width - right}
          y1={top + plotHeight * position}
          y2={top + plotHeight * position}
          className="chart-grid-line"
        />
      ))}
      <path d={area} fill={`url(#${gradientId})`} className="chart-area" />
      <path
        d={path}
        fill="none"
        stroke={COLORS[metric]}
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        pathLength="1"
        className="chart-line"
      />
      {points.map((point, index) => {
        const show = points.length <= 31 || index === 0 || index === points.length - 1;
        return show ? (
          <circle
            key={`${point.day}-${index}`}
            cx={point.x}
            cy={point.y}
            r="4"
            fill="var(--panel-card)"
            stroke={COLORS[metric]}
            strokeWidth="2.5"
            className="chart-point"
            style={{ animationDelay: `${120 + Math.min(index, 20) * 16}ms` }}
          >
            <title>{`${dateLabel(point.day, locale)}: ${point.value.toLocaleString(locale)}`}</title>
          </circle>
        ) : null;
      })}
      <text x={left} y={height - 8} textAnchor="start" className="chart-axis-label">
        {dateLabel(series[0]!.day, locale)}
      </text>
      <text x={width - right} y={height - 8} textAnchor="end" className="chart-axis-label">
        {dateLabel(series[series.length - 1]!.day, locale)}
      </text>
    </svg>
  );
}
