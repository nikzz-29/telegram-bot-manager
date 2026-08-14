import React, { useEffect, useState } from "react";
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

const METRIC_CLASS: Record<DashboardMetric, string> = {
  messages: "fill-accent",
  active_users: "fill-emerald-500",
  joins: "fill-emerald-500",
  leaves: "fill-amber-500",
  moderation_actions: "fill-destructive",
};

export function metricValue(point: StatPoint, metric: DashboardMetric): number {
  return point[metric] ?? 0;
}

export function totalValue(totals: DashboardTotals, metric: DashboardMetric): number {
  return totals[metric] ?? 0;
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
    const duration = 260;
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

export function ActivityChart({
  series,
  metric,
}: {
  series: readonly StatPoint[];
  metric: DashboardMetric;
}): React.JSX.Element {
  const t = useT();
  const { locale } = useI18n();
  const width = 360;
  const height = 132;
  const values = series.map((point) => metricValue(point, metric));
  const peak = Math.max(1, ...values);
  const slot = width / Math.max(1, series.length);
  const barWidth = Math.max(1.5, Math.min(18, slot * 0.68));

  if (series.length === 0 || values.every((value) => value === 0)) {
    return (
      <div className="flex h-[132px] items-center justify-center text-label text-hint">
        {t("stats-no-data")}
      </div>
    );
  }

  return (
    <svg
      key={metric}
      viewBox={`0 0 ${width} ${height}`}
      className="dashboard-chart h-[132px] w-full"
      preserveAspectRatio="none"
      role="img"
      aria-label={t(`dashboard-metric-${metric.replace(/_/g, "-")}`)}
    >
      <line x1="0" y1={height - 1} x2={width} y2={height - 1} className="stroke-separator" />
      {series.map((point, index) => {
        const value = metricValue(point, metric);
        const barHeight = value === 0 ? 1 : Math.max(3, (value / peak) * (height - 8));
        return (
          <rect
            key={point.date}
            x={index * slot + (slot - barWidth) / 2}
            y={height - barHeight}
            width={barWidth}
            height={barHeight}
            rx={Math.min(3, barWidth / 2)}
            className={`dashboard-chart-bar ${METRIC_CLASS[metric]}`}
          >
            <title>
              {new Date(`${point.date}T00:00:00`).toLocaleDateString(locale, {
                day: "numeric",
                month: "short",
              })}
              {`: ${value.toLocaleString(locale)}`}
            </title>
          </rect>
        );
      })}
    </svg>
  );
}
