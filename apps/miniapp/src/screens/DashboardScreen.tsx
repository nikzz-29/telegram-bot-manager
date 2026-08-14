import React from "react";
import type { DashboardTotals } from "../api/client";
import {
  ActivityChart,
  AnimatedNumber,
  type DashboardMetric,
  totalValue,
} from "../components/ActivityChart";
import {
  Badge,
  Card,
  ErrorState,
  Header,
  Row,
  Screen,
  SectionTitle,
  SkeletonRows,
} from "../components/ui";
import { useT } from "../i18n/I18nProvider";
import { useUserDashboard, useUserProfile } from "../hooks/queries";
import { useNavigation } from "../navigation";

const SUMMARY_METRICS: readonly DashboardMetric[] = [
  "messages",
  "active_users",
  "joins",
  "moderation_actions",
];

const EMPTY_TOTALS: DashboardTotals = {
  messages: 0,
  active_users: 0,
  joins: 0,
  leaves: 0,
  net_growth: 0,
  moderation_actions: 0,
};

export function DashboardScreen(): React.JSX.Element {
  const t = useT();
  const { push, reset } = useNavigation();
  const profile = useUserProfile();
  const dashboard = useUserDashboard(7);

  if (profile.isPending || dashboard.isPending) {
    return (
      <Screen>
        <Header title={t("dashboard-title")} icon="home" />
        <div className="mt-3">
          <SkeletonRows count={5} />
        </div>
      </Screen>
    );
  }
  if (profile.isError || dashboard.isError) {
    return (
      <Screen>
        <Header title={t("dashboard-title")} icon="home" />
        <ErrorState
          message={profile.error?.message ?? dashboard.error?.message ?? t("panel-auth-failed")}
          onRetry={() => {
            void profile.refetch();
            void dashboard.refetch();
          }}
        />
      </Screen>
    );
  }

  const stats = dashboard.data;
  const totals = stats.totals ?? EMPTY_TOTALS;
  const series = stats.series ?? [];
  const managedChats = stats.chats ?? [];
  return (
    <Screen>
      <Header
        title={t("dashboard-title")}
        subtitle={t("dashboard-greeting", { name: profile.data.display_name })}
        icon="home"
      />

      <Card className="mt-3 px-4 pb-3 pt-4">
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-label text-hint">{t("dashboard-week-activity")}</p>
            <p className="mt-0.5 text-display font-semibold tabular-nums">
              <AnimatedNumber value={totals.messages} />
            </p>
          </div>
          <Badge tone={stats.analytics_available ? "success" : "warning"}>
            {stats.analytics_available
              ? t("dashboard-analytics-on")
              : t("dashboard-analytics-locked")}
          </Badge>
        </div>
        <div className="mt-3">
          <ActivityChart series={series} metric="messages" />
        </div>
      </Card>

      <div className="mt-2 grid grid-cols-2 gap-2">
        {SUMMARY_METRICS.map((metric) => (
          <button
            key={metric}
            type="button"
            className="tg-metric-card text-left"
            onClick={() => reset({ name: "userStats" })}
          >
            <span className="text-display font-semibold tabular-nums">
              <AnimatedNumber value={totalValue(totals, metric)} />
            </span>
            <span className="mt-0.5 block text-label text-hint">
              {t(`dashboard-metric-${metric.replace(/_/g, "-")}`)}
            </span>
          </button>
        ))}
      </div>

      <SectionTitle>{t("dashboard-your-space")}</SectionTitle>
      <Card>
        <Row
          title={t("dashboard-chats", { count: profile.data.chats_total })}
          subtitle={t("dashboard-chat-roles", {
            owned: profile.data.chats_owned,
            admin: profile.data.chats_admin,
          })}
          icon="chat"
          onClick={() => reset({ name: "chats" })}
        />
        <Row
          title={t("dashboard-members", { count: profile.data.total_members })}
          subtitle={t("dashboard-paid-chats", { count: profile.data.paid_chats })}
          icon="user"
        />
        <Row
          title={t("dashboard-plans-action")}
          subtitle={t("dashboard-plans-hint")}
          icon="star"
          onClick={() => reset({ name: "plans" })}
        />
      </Card>

      <SectionTitle>{t("dashboard-quick-actions")}</SectionTitle>
      <Card>
        <Row
          title={t("dashboard-open-stats")}
          icon="chart"
          onClick={() => reset({ name: "userStats" })}
        />
        {managedChats.slice(0, 2).map((chat) => (
          <Row
            key={chat.id}
            title={chat.title || t("chat-untitled")}
            subtitle={t(`plan-${chat.plan}`)}
            icon="settings"
            onClick={() => push({ name: "chat", chatId: chat.id })}
          />
        ))}
      </Card>
    </Screen>
  );
}
