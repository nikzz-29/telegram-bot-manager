/**
 * The root screen: the chats this admin can configure.
 *
 * This is also the panel's only real onboarding surface — an admin who opened it
 * before adding the bot anywhere sees the empty state, and that text is the
 * instruction rather than a placeholder.
 */
import React from "react";
import type { ChatSummary } from "../api/client";
import { Card, EmptyState, ErrorState, Row, Screen, SectionTitle, Spinner } from "../components/ui";
import { useI18n, useT } from "../i18n/I18nProvider";
import type { Args } from "../i18n/bundles";
import { useChats } from "../hooks/queries";
import { useNavigation } from "../navigation";
import { useUser } from "../session";

function PlanBadge({ plan }: { plan: ChatSummary["plan"] }): React.JSX.Element {
  const t = useT();
  const paid = plan !== "free";
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[12px] font-medium ${
        paid ? "bg-accent text-accent-text" : "bg-hint/15 text-hint"
      }`}
    >
      {t(`plan-${plan}`)}
    </span>
  );
}

function subtitleFor(chat: ChatSummary, t: (key: string, args?: Args) => string): string {
  const parts = [t(chat.role === "owner" ? "chats-role-owner" : "chats-role-admin")];
  if (chat.members_count != null) {
    parts.push(t("chats-members", { count: chat.members_count }));
  }
  if (chat.is_active === false) {
    parts.push(t("chats-inactive"));
  }
  return parts.join(" · ");
}

export function ChatListScreen(): React.JSX.Element {
  const t = useT();
  const { locale, setLocale, available } = useI18n();
  const navigation = useNavigation();
  const chats = useChats();
  const user = useUser();

  return (
    <Screen>
      <SectionTitle>{t("chats-title")}</SectionTitle>
      {chats.isPending && <Spinner />}
      {chats.isError && (
        <ErrorState message={chats.error.message} onRetry={() => void chats.refetch()} />
      )}
      {chats.isSuccess &&
        (chats.data.length === 0 ? (
          <Card>
            <EmptyState text={t("chats-empty")} />
          </Card>
        ) : (
          <Card>
            {chats.data.map((chat) => (
              <Row
                key={chat.id}
                title={chat.title}
                subtitle={subtitleFor(chat, t)}
                right={<PlanBadge plan={chat.plan} />}
                onClick={() => navigation.push({ name: "chat", chatId: chat.id })}
              />
            ))}
          </Card>
        ))}

      {user.is_superadmin && (
        <>
          <SectionTitle>{t("section-platform")}</SectionTitle>
          <Card>
            {/* Hiding this row is tidiness, not access control — every platform
                endpoint re-checks the flag server-side. */}
            <Row
              title={t("platform-title")}
              onClick={() => navigation.push({ name: "platform" })}
            />
          </Card>
        </>
      )}

      <SectionTitle>{t("panel-language")}</SectionTitle>
      <Card>
        {available.map((code) => (
          <Row
            key={code}
            title={t(`locale-${code}`)}
            right={code === locale ? <span className="text-accent">✓</span> : undefined}
            onClick={() => setLocale(code)}
          />
        ))}
      </Card>
    </Screen>
  );
}
