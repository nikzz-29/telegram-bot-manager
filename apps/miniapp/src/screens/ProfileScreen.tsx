import React, { useState } from "react";
import {
  Badge,
  Card,
  ErrorState,
  Header,
  Row,
  Screen,
  SectionTitle,
  SegmentedControl,
  SkeletonRows,
  Toggle,
} from "../components/ui";
import { useI18n, useT } from "../i18n/I18nProvider";
import { useChats, useUserProfile } from "../hooks/queries";
import { useNavigation } from "../navigation";
import {
  isSoundEnabled,
  playClick,
  setSoundEnabled as persistSoundEnabled,
} from "../telegram/sdk";

function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

export function ProfileScreen(): React.JSX.Element {
  const t = useT();
  const { locale, setLocale, available } = useI18n();
  const { reset } = useNavigation();
  const profile = useUserProfile();
  const chats = useChats();
  const [soundEnabled, setSoundEnabled] = useState(isSoundEnabled);

  if (profile.isPending || chats.isPending) {
    return (
      <Screen>
        <Header title={t("profile-title")} icon="user" />
        <div className="mt-3">
          <SkeletonRows count={6} />
        </div>
      </Screen>
    );
  }
  if (profile.isError || chats.isError) {
    const message = profile.error?.message ?? chats.error?.message ?? t("panel-auth-failed");
    return (
      <Screen>
        <Header title={t("profile-title")} icon="user" />
        <ErrorState
          message={message}
          onRetry={() => {
            void profile.refetch();
            void chats.refetch();
          }}
        />
      </Screen>
    );
  }

  const data = profile.data;
  const plans = chats.data.reduce<Record<string, number>>((counts, chat) => {
    counts[chat.plan] = (counts[chat.plan] ?? 0) + 1;
    return counts;
  }, {});
  return (
    <Screen>
      <Header title={t("profile-title")} subtitle={t("profile-subtitle")} icon="user" />

      <div className="flex items-center gap-4 px-1 py-4">
        {data.user.photo_url ? (
          <img
            src={data.user.photo_url}
            alt=""
            className="h-16 w-16 shrink-0 rounded-full object-cover"
          />
        ) : (
          <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-accent text-title font-semibold text-accent-text">
            {initials(data.display_name) || "?"}
          </span>
        )}
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-display font-semibold">{data.display_name}</h2>
          <p className="mt-0.5 truncate text-row text-hint">
            {data.user.username ? `@${data.user.username}` : t("profile-no-username")}
          </p>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {data.user.is_premium && <Badge tone="accent">Telegram Premium</Badge>}
            {data.user.is_superadmin && <Badge tone="warning">{t("profile-operator")}</Badge>}
          </div>
        </div>
      </div>

      <SectionTitle>{t("profile-account")}</SectionTitle>
      <Card>
        <Row
          title={t("profile-telegram-id")}
          right={<code className="text-label text-hint">{data.user.tg_user_id}</code>}
        />
        <Row title={t("profile-language-code")} right={<span className="text-label text-hint">{data.user.language_code.toUpperCase()}</span>} />
        <Row
          title={t("profile-first-seen")}
          right={
            <span className="text-label text-hint">
              {data.first_seen_at
                ? new Date(data.first_seen_at).toLocaleDateString(locale, { dateStyle: "medium" })
                : t("profile-date-unknown")}
            </span>
          }
        />
      </Card>

      <SectionTitle>{t("profile-management")}</SectionTitle>
      <Card>
        <Row
          title={t("profile-chats-total")}
          subtitle={t("profile-chat-roles", {
            owned: data.chats_owned,
            admin: data.chats_admin,
          })}
          right={<Badge tone="accent">{data.chats_total}</Badge>}
          chevron
          onClick={() => reset({ name: "chats" })}
        />
        <Row
          title={t("profile-members-total")}
          right={<span className="text-row tabular-nums">{data.total_members}</span>}
        />
        <Row
          title={t("profile-paid-chats")}
          right={<span className="text-row tabular-nums">{data.paid_chats}</span>}
          chevron
          onClick={() => reset({ name: "plans" })}
        />
        {Object.entries(plans).map(([plan, count]) => (
          <Row
            key={plan}
            title={t(`plan-${plan}`)}
            right={<span className="text-label tabular-nums text-hint">{count}</span>}
          />
        ))}
      </Card>

      <SectionTitle>{t("profile-preferences")}</SectionTitle>
      <Card>
        <Row
          title={t("profile-click-sound")}
          subtitle={t("profile-click-sound-hint")}
          icon="spark"
          right={
            <Toggle
              checked={soundEnabled}
              label={t("profile-click-sound")}
              onChange={(enabled) => {
                persistSoundEnabled(enabled);
                setSoundEnabled(enabled);
                if (enabled) {
                  playClick();
                }
              }}
            />
          }
        />
      </Card>
      <div className="mt-2">
        <SegmentedControl
          value={locale}
          onChange={setLocale}
          options={available.map((item) => ({ value: item, label: t(`locale-${item}`) }))}
        />
      </div>
    </Screen>
  );
}
