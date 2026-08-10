/**
 * Chat statistics: the totals, a bar chart of daily activity, and the top posters.
 *
 * DECISION: the chart is inline SVG rather than a charting library. It is one
 * series of at most 90 bars, and the smallest chart bundle is larger than this
 * whole app — in a webview opened over mobile data, that is the wrong trade.
 */
import React, { useState } from "react";
import type { StatPoint, StatsOverview } from "../api/client";
import {
  Card,
  EmptyState,
  ErrorState,
  Header,
  Row,
  Screen,
  SectionTitle,
  SkeletonRows,
} from "../components/ui";
import { useT } from "../i18n/I18nProvider";
import { useStats } from "../hooks/queries";

const RANGES = [7, 30, 90] as const;

/**
 * The four headline figures.
 *
 * DECISION: a figure with its caption underneath, not a row with a trailing
 * value. These four numbers are the reason the screen exists, and a grouped list
 * gives them the same weight as a setting — the eye runs down the labels and the
 * numbers arrive second. Inverting that (number at display size, label dropped to
 * hint) is what makes the screen answer its question at a glance.
 */
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
        <Card key={key} className="px-4 py-3">
          <div className="text-display font-semibold tabular-nums">{value}</div>
          <div className="mt-0.5 text-label text-hint">{t(key)}</div>
        </Card>
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

/**
 * The shape of this screen while it loads.
 *
 * DECISION: not the shared `SkeletonRows` on its own. Most of what arrives here
 * is a grid of figures and a chart, and a placeholder made only of rows would
 * describe a layout that never comes — the page would jump the moment it
 * resolved, which is the one thing a skeleton exists to prevent.
 */
function StatsSkeleton(): React.JSX.Element {
  return (
    <>
      <div className="mt-3 grid grid-cols-2 gap-2">
        {[0, 1, 2, 3].map((index) => (
          <Card key={index} className="px-4 py-3">
            <span className="tg-skeleton block h-[22px] w-1/2" />
            <span className="tg-skeleton mt-2 block h-[13px] w-3/4" />
          </Card>
        ))}
      </div>
      <div className="mt-4">
        <Card className="px-3 py-4">
          <span className="tg-skeleton block h-24 w-full" />
        </Card>
      </div>
      <div className="mt-4">
        <SkeletonRows count={3} />
      </div>
    </>
  );
}

export function StatsScreen({ chatId }: { chatId: number }): React.JSX.Element {
  const t = useT();
  const [days, setDays] = useState<number>(7);
  const stats = useStats(chatId, days);

  return (
    <Screen>
      <Header title={t("stats-screen-title")} icon="chart" />

      <SectionTitle>{t("stats-range")}</SectionTitle>
      {/*
       * DECISION: one tinted track with the chosen range raised out of it, rather
       * than three separate buttons. Three equal pills never read as one choice —
       * the two unselected ones looked like further actions you could also take —
       * and a segmented control says "pick exactly one of these" without a word.
       */}
      <div className="flex gap-1 rounded-control bg-hint-tint p-1">
        {RANGES.map((range) => (
          <button
            key={range}
            type="button"
            aria-pressed={range === days}
            onClick={() => setDays(range)}
            className={`flex-1 rounded-[7px] px-3 py-1.5 text-label font-medium transition-colors duration-[--panel-motion] ease-panel ${
              range === days ? "bg-card text-text shadow-card" : "text-hint"
            }`}
          >
            {t(`stats-range-${range}`)}
          </button>
        ))}
      </div>

      {stats.isPending && <StatsSkeleton />}
      {stats.isError && (
        <ErrorState message={stats.error.message} onRetry={() => void stats.refetch()} />
      )}
      {stats.isSuccess && (
        <>
          {/*
           * The API clamps `days` to the plan's retention; say so when it did.
           *
           * DECISION: a left-aligned footnote in hint text, not a centred notice.
           * It explains the control immediately above it and nothing has gone
           * wrong, so it takes Telegram's group-footer treatment — the same one
           * every explanatory sentence in the panel gets.
           */}
          {stats.data.period_days < days && (
            <p className="px-1 pt-2 text-label text-hint">
              {t("stats-retention-capped", { days: stats.data.period_days })}
            </p>
          )}

          <div className="mt-3">
            <Totals stats={stats.data} />
          </div>

          <SectionTitle>{t("stats-metric-messages")}</SectionTitle>
          <Card className="px-3 py-4">
            {(stats.data.series ?? []).length === 0 ? (
              <EmptyState text={t("stats-no-data")} icon="chart" />
            ) : (
              <Chart series={stats.data.series ?? []} />
            )}
          </Card>

          <SectionTitle>{t("stats-top-users")}</SectionTitle>
          <Card>
            {(stats.data.top_users ?? []).length === 0 ? (
              <EmptyState text={t("stats-no-data")} icon="chat" />
            ) : (
              (stats.data.top_users ?? []).map((user) => (
                <Row
                  key={user.tg_user_id}
                  title={
                    user.display_name ??
                    (user.username != null ? `@${user.username}` : String(user.tg_user_id))
                  }
                  right={
                    <span className="text-label tabular-nums text-hint">
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
