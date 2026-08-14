import React, { useMemo, useState } from "react";
import type { DashboardModeration, DashboardTotals } from "../api/client";
import {
  ActivityChart,
  AnimatedNumber,
  DASHBOARD_METRICS,
  type DashboardMetric,
  totalValue,
} from "../components/ActivityChart";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Header,
  PickerRow,
  Row,
  Screen,
  SectionTitle,
  SegmentedControl,
  SkeletonRows,
} from "../components/ui";
import { useT } from "../i18n/I18nProvider";
import { useUserDashboard } from "../hooks/queries";
import { pressFeedback } from "../telegram/sdk";

const RANGES = [1, 7, 30, 90] as const;

const ACTION_KEYS: Record<string, string> = {
  warn: "report-action-warn",
  mute: "report-action-mute",
  ban: "report-action-ban",
  kick: "report-action-kick",
  auto_delete: "report-action-delete",
  alert_admins: "report-action-alert",
  nothing: "report-action-flagged",
  unwarn: "report-action-unwarn",
  unmute: "report-action-unmute",
  unban: "report-action-unban",
  auto_unmute: "report-action-auto-lift",
  auto_unban: "report-action-auto-lift",
};

const EMPTY_TOTALS: DashboardTotals = {
  messages: 0,
  active_users: 0,
  joins: 0,
  leaves: 0,
  net_growth: 0,
  moderation_actions: 0,
};

const EMPTY_MODERATION: DashboardModeration = {
  total: 0,
  warns: 0,
  restrictions: 0,
  mine: 0,
  automated: 0,
  moderators: 0,
  breakdown: [],
};

export function UserStatsScreen(): React.JSX.Element {
  const t = useT();
  const [days, setDays] = useState<(typeof RANGES)[number]>(7);
  const [metric, setMetric] = useState<DashboardMetric>("messages");
  const [chat, setChat] = useState("all");
  const chatId = chat === "all" ? undefined : Number(chat);
  const dashboard = useUserDashboard(days, chatId);
  const totals = dashboard.data?.totals ?? EMPTY_TOTALS;
  const series = dashboard.data?.series ?? [];
  const moderation = dashboard.data?.moderation ?? EMPTY_MODERATION;
  const deltas = dashboard.data?.deltas_percent ?? {};
  const topUsers = dashboard.data?.top_users ?? [];
  const chatOptions = useMemo(
    () => [
      { value: "all", label: t("stats-all-chats") },
      ...(dashboard.data?.chats ?? []).map((item) => ({
        value: String(item.id),
        label: item.title || t("chat-untitled"),
      })),
    ],
    [dashboard.data?.chats, t],
  );

  return (
    <Screen>
      <Header title={t("user-stats-title")} subtitle={t("user-stats-subtitle")} icon="chart" />

      <SectionTitle>{t("stats-chat-filter")}</SectionTitle>
      <Card>
        <PickerRow
          title={t("stats-chat-filter")}
          value={chat}
          options={chatOptions}
          unsetLabel={t("stats-all-chats")}
          onPick={setChat}
        />
      </Card>

      <SectionTitle>{t("stats-range")}</SectionTitle>
      <SegmentedControl
        value={days}
        onChange={setDays}
        options={RANGES.map((range) => ({
          value: range,
          label: t(`stats-range-${range}`),
        }))}
      />

      {dashboard.isPending && (
        <div className="mt-3">
          <SkeletonRows count={6} />
        </div>
      )}
      {dashboard.isError && (
        <ErrorState message={dashboard.error.message} onRetry={() => void dashboard.refetch()} />
      )}
      {dashboard.isSuccess && (
        <>
          <div className="mt-3 grid grid-cols-2 gap-2">
            {DASHBOARD_METRICS.map((item) => {
              const selected = item === metric;
              return (
                <button
                  key={item}
                  type="button"
                  aria-pressed={selected}
                  className={`tg-metric-card text-left ${selected ? "tg-metric-card-active" : ""}`}
                  onClick={() => {
                    pressFeedback();
                    setMetric(item);
                  }}
                >
                  <span className="text-display font-semibold tabular-nums">
                    <AnimatedNumber value={totalValue(totals, item)} />
                  </span>
                  <span className="mt-0.5 block text-label text-hint">
                    {t(`dashboard-metric-${item.replace(/_/g, "-")}`)}
                  </span>
                </button>
              );
            })}
          </div>

          <SectionTitle>{t(`dashboard-metric-${metric.replace(/_/g, "-")}`)}</SectionTitle>
          <Card className="px-3 py-4">
            <div className="mb-3 flex items-center justify-between gap-3 px-1">
              <span className="text-label text-hint">
                {t("stats-period-summary", { days: dashboard.data.period_days })}
              </span>
              <Badge tone={dashboard.data.analytics_available ? "success" : "warning"}>
                {dashboard.data.analytics_available
                  ? t("dashboard-analytics-on")
                  : t("dashboard-analytics-locked")}
              </Badge>
            </div>
            <ActivityChart series={series} metric={metric} />
          </Card>

          <SectionTitle>{t("stats-growth-title")}</SectionTitle>
          <Card>
            <Row
              title={t("stats-growth-net")}
              subtitle={t("stats-growth-flow", {
                joins: totals.joins,
                leaves: totals.leaves,
              })}
              right={
                <Badge tone={totals.net_growth >= 0 ? "success" : "destructive"}>
                  {totals.net_growth > 0 ? "+" : ""}
                  {totals.net_growth}
                </Badge>
              }
            />
            <Row
              title={t("stats-change-vs-previous")}
              right={
                <span className="text-label tabular-nums text-hint">
                  {deltas[metric] == null
                    ? t("stats-change-new")
                    : `${deltas[metric]! > 0 ? "+" : ""}${deltas[metric]}%`}
                </span>
              }
            />
          </Card>

          <SectionTitle>{t("stats-moderation-title")}</SectionTitle>
          <Card>
            <Row
              title={t("stats-moderation-total")}
              right={<Badge tone="accent">{moderation.total}</Badge>}
            />
            <Row
              title={t("stats-moderation-mine")}
              right={<span className="text-row tabular-nums">{moderation.mine}</span>}
            />
            {(moderation.breakdown ?? []).slice(0, 5).map((entry) => (
              <Row
                key={entry.action}
                title={t(ACTION_KEYS[entry.action] ?? "report-action-other")}
                right={<span className="text-label tabular-nums text-hint">{entry.count}</span>}
              />
            ))}
          </Card>

          <SectionTitle>{t("stats-top-users")}</SectionTitle>
          <Card>
            {topUsers.length === 0 ? (
              <EmptyState text={t("stats-no-data")} icon="user" />
            ) : (
              topUsers.map((user, index) => (
                <Row
                  key={user.tg_user_id}
                  title={`${index + 1}. ${
                    user.display_name ??
                    (user.username != null ? `@${user.username}` : String(user.tg_user_id))
                  }`}
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
