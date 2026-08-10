/**
 * Chat statistics: the totals, a bar chart of daily activity, and the top posters.
 *
 * DECISION: the chart is inline SVG rather than a charting library. It is one
 * series of at most 90 bars, and the smallest chart bundle is larger than this
 * whole app — in a webview opened over mobile data, that is the wrong trade.
 */
import React, { useState } from "react";
import type { StatPoint, StatsOverview } from "../api/client";
import { Card, EmptyState, ErrorState, Row, Screen, SectionTitle, Spinner } from "../components/ui";
import { useT } from "../i18n/I18nProvider";
import { useStats } from "../hooks/queries";

const RANGES = [7, 30, 90] as const;

function Totals({ stats }: { stats: StatsOverview }): React.JSX.Element {
  const t = useT();
  const cells: [string, number][] = [
    ["stats-metric-messages", stats.total_messages],
    ["stats-active-users", stats.total_active_users],
    ["stats-metric-joins", stats.total_joins],
    ["stats-metric-leaves", stats.total_leaves],
  ];
  return (
    <div className="grid grid-cols-2 gap-2">
      {cells.map(([key, value]) => (
        <div key={key} className="tg-card px-4 py-3">
          <div className="text-[22px] font-semibold tabular-nums">{value}</div>
          <div className="text-[13px] text-hint">{t(key)}</div>
        </div>
      ))}
    </div>
  );
}

function Chart({ series }: { series: readonly StatPoint[] }): React.JSX.Element {
  const width = 320;
  const height = 96;
  const peak = Math.max(1, ...series.map((point) => point.messages));
  const slot = width / Math.max(1, series.length);
  const barWidth = Math.max(1, slot * 0.7);
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      className="h-24 w-full"
      preserveAspectRatio="none"
      role="img"
    >
      {series.map((point, index) => {
        // Every day gets at least a sliver, so a quiet day reads as "no messages"
        // rather than as a gap in the data.
        const barHeight = point.messages === 0 ? 1 : (point.messages / peak) * height;
        return (
          <rect
            key={point.date}
            x={index * slot + (slot - barWidth) / 2}
            y={height - barHeight}
            width={barWidth}
            height={barHeight}
            rx={1}
            className="fill-accent"
          />
        );
      })}
    </svg>
  );
}

export function StatsScreen({ chatId }: { chatId: number }): React.JSX.Element {
  const t = useT();
  const [days, setDays] = useState<number>(7);
  const stats = useStats(chatId, days);

  return (
    <Screen>
      <SectionTitle>{t("stats-range")}</SectionTitle>
      <div className="flex gap-2">
        {RANGES.map((range) => (
          <button
            key={range}
            type="button"
            onClick={() => setDays(range)}
            className={`flex-1 rounded-lg px-3 py-2 text-[14px] ${
              range === days ? "bg-accent text-accent-text" : "bg-surface text-link"
            }`}
          >
            {t(`stats-range-${range}`)}
          </button>
        ))}
      </div>

      {stats.isPending && <Spinner />}
      {stats.isError && (
        <ErrorState message={stats.error.message} onRetry={() => void stats.refetch()} />
      )}
      {stats.isSuccess && (
        <>
          {/* The API clamps `days` to the plan's retention; say so when it did. */}
          {stats.data.period_days < days && (
            <p className="mt-3 text-center text-[13px] text-hint">
              {t("stats-retention-capped", { days: stats.data.period_days })}
            </p>
          )}

          <div className="mt-3">
            <Totals stats={stats.data} />
          </div>

          <SectionTitle>{t("stats-metric-messages")}</SectionTitle>
          <Card className="px-3 py-4">
            {(stats.data.series ?? []).length === 0 ? (
              <EmptyState text={t("stats-no-data")} />
            ) : (
              <Chart series={stats.data.series ?? []} />
            )}
          </Card>

          <SectionTitle>{t("stats-top-users")}</SectionTitle>
          <Card>
            {(stats.data.top_users ?? []).length === 0 ? (
              <EmptyState text={t("stats-no-data")} />
            ) : (
              (stats.data.top_users ?? []).map((user) => (
                <Row
                  key={user.tg_user_id}
                  title={
                    user.display_name ??
                    (user.username != null ? `@${user.username}` : String(user.tg_user_id))
                  }
                  right={
                    <span className="tabular-nums text-hint">
                      {t("field-messages-count", { count: user.messages })}
                    </span>
                  }
                />
              ))
            )}
          </Card>
        </>
      )}
    </Screen>
  );
}
