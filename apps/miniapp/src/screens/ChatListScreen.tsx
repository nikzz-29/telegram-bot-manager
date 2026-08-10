/**
 * The root screen: the chats this admin can configure.
 *
 * This is also the panel's only real onboarding surface — an admin who opened it
 * before adding the bot anywhere sees the empty state, and that text is the
 * instruction rather than a placeholder.
 */
import React from "react";
import type { ChatSummary } from "../api/client";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Header,
  Icon,
  Row,
  Screen,
  SectionTitle,
  SkeletonRows,
} from "../components/ui";
import { useI18n, useT } from "../i18n/I18nProvider";
import type { Args } from "../i18n/bundles";
import { useChats } from "../hooks/queries";
import { useNavigation } from "../navigation";
import { useUser } from "../session";

/**
 * Role, size and liveness, in one line under the chat's name.
 *
 * DECISION: "bot removed" stays a clause of this sentence rather than becoming a
 * warning badge. The right-hand slot already carries the plan, and a second pill
 * beside it turns the one column an admin scans down — which chats are paid —
 * into two competing ones. Here it reads as what it is: one more fact about the
 * chat, in the same breath as the role and the member count.
 */
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
      <Header title={t("chats-title")} icon="chat" />
      {chats.isPending && <SkeletonRows />}
      {chats.isError && (
        <ErrorState message={chats.error.message} onRetry={() => void chats.refetch()} />
      )}
      {chats.isSuccess &&
        (chats.data.length === 0 ? (
          <Card>
            <EmptyState text={t("chats-empty")} icon="plus" />
          </Card>
        ) : (
          <Card>
            {chats.data.map((chat) => (
              <Row
                key={chat.id}
                title={chat.title}
                subtitle={subtitleFor(chat, t)}
                // DECISION: the chevron is forced on. Every row here opens a
                // chat, but the plan pill fills `right` and would suppress the
                // automatic one — and a plan is status, never a promise that
                // tapping does something. Without this the panel's most
                // important list is the one list that looks inert. Telegram's
                // own rows pair a trailing value with a chevron for this reason.
                chevron
                right={
                  <Badge tone={chat.plan !== "free" ? "accent" : "neutral"}>
                    {t(`plan-${chat.plan}`)}
                  </Badge>
                }
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
              icon="globe"
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
            // DECISION: the unselected rows keep an invisible checkmark instead
            // of an empty `right`. An empty one earns the automatic chevron,
            // which would promise a screen that does not exist — picking a
            // language happens in place — and reserving the space stops the
            // labels shifting sideways as the selection moves.
            right={
              <Icon
                name="check"
                size={18}
                className={code === locale ? "text-accent" : "invisible"}
              />
            }
            onClick={() => setLocale(code)}
          />
        ))}
      </Card>
    </Screen>
  );
}
