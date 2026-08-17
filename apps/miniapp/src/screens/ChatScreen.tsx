/**
 * One chat: its general settings, then every module as a row into its own screen.
 *
 * The module list is drawn from `/api/meta` (what exists, in what order, gated
 * behind which plan) crossed with `/api/chats/{id}/modules` (what this chat has
 * turned on, and whether its plan allows it). Neither half is enough alone: meta
 * knows the catalog, the chat knows the state.
 */
import React from "react";
import type { ModuleConfigResponse } from "../api/client";
import {
  Badge,
  Card,
  ErrorState,
  Header,
  Row,
  Screen,
  SectionTitle,
  SkeletonRows,
  Spinner,
  Toggle,
} from "../components/ui";
import { useT } from "../i18n/I18nProvider";
import {
  useChat,
  useChatBotPermissions,
  useMeta,
  useModules,
  useSaveModule,
  useSyncAdmins,
} from "../hooks/queries";
import { type Route, useNavigation } from "../navigation";
import { hapticResult } from "../telegram/sdk";
import { GeneralSettings } from "./chat/GeneralSettings";

/**
 * The screens that show a module's *data* rather than its settings.
 *
 * DECISION: each one is gated on the module that owns the data, not on a plan.
 * `available` already folds the plan in, and the chat's own answer is the one
 * that stays right when a payment lands while the panel is open. Triggers and
 * reputation share `engagement` because one module owns both tables.
 *
 * DECISION: the icon is named here rather than inherited from the owning
 * module's `meta.icon`. Two of these tools are backed by the same module, so
 * inheriting would draw triggers and reputation with one glyph and make them
 * look like the same destination — the icon has to say which tool, not which
 * module.
 */
type ToolRoute = Extract<Route, { name: "triggers" | "posts" | "stats" | "reputation" }>;

const TOOLS: readonly {
  module: string;
  titleKey: string;
  route: ToolRoute["name"];
  icon: string;
}[] = [
  { module: "engagement", titleKey: "triggers-title", route: "triggers", icon: "chat" },
  { module: "autopost", titleKey: "posts-title", route: "posts", icon: "clock" },
  { module: "stats", titleKey: "module-stats-title", route: "stats", icon: "chart" },
  { module: "engagement", titleKey: "reputation-title", route: "reputation", icon: "spark" },
];

export function ChatScreen({ chatId }: { chatId: number }): React.JSX.Element {
  const t = useT();
  const navigation = useNavigation();
  const chat = useChat(chatId);
  const permissions = useChatBotPermissions(chatId);
  const meta = useMeta();
  const modules = useModules(chatId);
  const saveModule = useSaveModule(chatId);
  const syncAdmins = useSyncAdmins(chatId);

  if (chat.isPending || meta.isPending || modules.isPending) {
    return (
      <Screen>
        <SkeletonRows count={5} />
      </Screen>
    );
  }
  // The three `isPending` checks above do not narrow `.data` on their own —
  // a query can also be in `error`, where `data` is undefined too.
  if (!chat.isSuccess || !meta.isSuccess || !modules.isSuccess) {
    const failure = chat.error ?? meta.error ?? modules.error;
    return (
      <Screen>
        <ErrorState
          message={failure?.message ?? t("error-generic")}
          onRetry={() => {
            void chat.refetch();
            void modules.refetch();
          }}
        />
      </Screen>
    );
  }

  const state = new Map<string, ModuleConfigResponse>(
    modules.data.map((entry) => [entry.module, entry]),
  );
  const catalog = [...(meta.data.modules ?? [])].sort((a, b) => a.order - b.order);

  return (
    <Screen>
      {/* The title is the chat's own name rather than a key: Telegram's header
          names the bot, so without this nothing on screen says which chat these
          settings belong to. */}
      <Header title={chat.data.title} subtitle={t(`plan-${chat.data.plan}`)} icon="settings" />

      <SectionTitle>{t("chat-general")}</SectionTitle>
      <GeneralSettings chat={chat.data} locales={meta.data.locales ?? []} />

      <SectionTitle>{t("chat-bot-permissions")}</SectionTitle>
      {permissions.isPending ? <SkeletonRows count={3} /> : null}
      {permissions.isError ? (
        <ErrorState
          message={permissions.error.message}
          onRetry={() => void permissions.refetch()}
        />
      ) : null}
      {permissions.data ? (
        <Card>
          <Row
            title={t("chat-bot-status")}
            icon="shield"
            subtitle={
              permissions.data.privacy_mode_disabled
                ? t("chat-privacy-disabled")
                : t("chat-privacy-enabled")
            }
            right={
              <Badge tone={permissions.data.is_admin ? "success" : "destructive"}>
                {permissions.data.is_admin ? t("state-ready") : t("state-attention")}
              </Badge>
            }
          />
          {(
            [
              ["can_read_messages", "chat-permission-read"],
              ["can_delete_messages", "chat-permission-delete"],
              ["can_restrict_members", "chat-permission-restrict"],
              ["can_invite_users", "chat-permission-invite"],
            ] as const
          ).map(([key, label]) => (
            <Row
              key={key}
              title={t(label)}
              right={
                <Badge tone={permissions.data[key] ? "success" : "warning"}>
                  {permissions.data[key] ? t("state-on") : t("state-off")}
                </Badge>
              }
            />
          ))}
        </Card>
      ) : null}

      <SectionTitle>{t("chat-sections")}</SectionTitle>
      <Card>
        {catalog.map((module) => {
          const entry = state.get(module.name);
          const available = entry?.available ?? false;
          return (
            <Row
              key={module.name}
              title={t(module.title_key)}
              // The registry names the glyph server-side, so a module added
              // after this build ships still draws with its own icon.
              icon={module.icon}
              // DECISION: a locked module's tile goes grey. It says the same
              // thing as the "needs plan X" subtitle, but it survives the
              // glance — the column of tiles is what the eye runs down, and an
              // accent tile on a row you cannot use reads as available.
              iconTone={available ? "accent" : "hint"}
              subtitle={
                available
                  ? t(module.description_key)
                  : t("module-locked", { plan: t(`plan-${module.required_plan}`) })
              }
              onClick={() =>
                navigation.push({ name: "module", chatId, module: module.name })
              }
              // DECISION: no hand-drawn chevron beside the toggle, even though
              // the row does navigate. A switch is already the loudest thing on
              // the row, and pairing it with a chevron gives one cell two
              // competing affordances; Telegram's own toggle rows carry neither.
              // The icon tile is what marks this as a destination.
              right={
                <Toggle
                  checked={entry?.enabled ?? false}
                  label={t(module.title_key)}
                  // A mandatory module is the moderation core: the toggle shows
                  // its state but the chat cannot run without it.
                  disabled={!available || module.mandatory || saveModule.isPending}
                  onChange={(enabled) => {
                    saveModule.mutate(
                      { module: module.name, enabled },
                      {
                        onSuccess: () => hapticResult(true),
                        onError: () => hapticResult(false),
                      },
                    );
                  }}
                />
              }
            />
          );
        })}
      </Card>

      <SectionTitle>{t("chat-tools")}</SectionTitle>
      <Card>
        {TOOLS.map((tool) => {
          const available = state.get(tool.module)?.available ?? false;
          const spec = catalog.find((entry) => entry.name === tool.module);
          return (
            <Row
              key={tool.route}
              title={t(tool.titleKey)}
              icon={tool.icon}
              iconTone={available ? "accent" : "hint"}
              subtitle={
                available || spec === undefined
                  ? undefined
                  : t("module-locked", { plan: t(`plan-${spec.required_plan}`) })
              }
              // A locked row stays visible: seeing what the next plan unlocks is
              // the point of showing it at all.
              onClick={
                available
                  ? () => navigation.push({ name: tool.route, chatId })
                  : undefined
              }
            />
          );
        })}
      </Card>

      <SectionTitle>{t("section-billing")}</SectionTitle>
      <Card>
        <Row
          title={t("billing-title")}
          icon="star"
          subtitle={t(`plan-${chat.data.plan}`)}
          onClick={() => navigation.push({ name: "billing", chatId })}
        />
      </Card>

      <Card className="mt-4">
        {/*
         * DECISION: this row reports all four states of its own mutation, and no
         * chevron. It used to show only the success one — and to keep showing it
         * for as long as the screen stayed open, so a later promotion in Telegram
         * was answered by a row still claiming the list was current. A failure
         * showed nothing at all beyond a buzz, which is indistinguishable from a
         * tap that never registered.
         *
         * The success line clears itself after a few seconds. It is a receipt for
         * the tap, not a fact about the chat, and once it stops being the former
         * it is only pretending to be the latter.
         */}
        <Row
          title={t("chat-sync-admins")}
          icon="refresh"
          chevron={false}
          subtitle={
            syncAdmins.isError ? (
              <span className="text-destructive">{syncAdmins.error.message}</span>
            ) : syncAdmins.isSuccess ? (
              t("chat-sync-done")
            ) : (
              t("chat-sync-admins-hint")
            )
          }
          right={syncAdmins.isPending ? <Spinner /> : undefined}
          onClick={() => {
            syncAdmins.mutate(undefined, {
              onSuccess: () => {
                hapticResult(true);
                window.setTimeout(() => syncAdmins.reset(), 4000);
              },
              onError: () => hapticResult(false),
            });
          }}
        />
      </Card>
    </Screen>
  );
}
