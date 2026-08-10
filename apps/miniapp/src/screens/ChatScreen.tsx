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
  Card,
  ErrorState,
  Row,
  Screen,
  SectionTitle,
  Spinner,
  Toggle,
} from "../components/ui";
import { useT } from "../i18n/I18nProvider";
import { useChat, useMeta, useModules, useSaveModule, useSyncAdmins } from "../hooks/queries";
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
 */
type ToolRoute = Extract<Route, { name: "triggers" | "posts" | "stats" | "reputation" }>;

const TOOLS: readonly { module: string; titleKey: string; route: ToolRoute["name"] }[] = [
  { module: "engagement", titleKey: "triggers-title", route: "triggers" },
  { module: "autopost", titleKey: "posts-title", route: "posts" },
  { module: "stats", titleKey: "module-stats-title", route: "stats" },
  { module: "engagement", titleKey: "reputation-title", route: "reputation" },
];

export function ChatScreen({ chatId }: { chatId: number }): React.JSX.Element {
  const t = useT();
  const navigation = useNavigation();
  const chat = useChat(chatId);
  const meta = useMeta();
  const modules = useModules(chatId);
  const saveModule = useSaveModule(chatId);
  const syncAdmins = useSyncAdmins(chatId);

  if (chat.isPending || meta.isPending || modules.isPending) {
    return (
      <Screen>
        <Spinner />
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
      <SectionTitle>{t("chat-general")}</SectionTitle>
      <GeneralSettings chat={chat.data} locales={meta.data.locales ?? []} />

      <SectionTitle>{t("chat-sections")}</SectionTitle>
      <Card>
        {catalog.map((module) => {
          const entry = state.get(module.name);
          const available = entry?.available ?? false;
          return (
            <Row
              key={module.name}
              title={t(module.title_key)}
              subtitle={
                available
                  ? t(module.description_key)
                  : t("module-locked", { plan: t(`plan-${module.required_plan}`) })
              }
              onClick={() =>
                navigation.push({ name: "module", chatId, module: module.name })
              }
              right={
                <Toggle
                  checked={entry?.enabled ?? false}
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
          subtitle={t(`plan-${chat.data.plan}`)}
          onClick={() => navigation.push({ name: "billing", chatId })}
        />
      </Card>

      <Card className="mt-4">
        <Row
          title={t("chat-sync-admins")}
          subtitle={syncAdmins.isSuccess ? t("chat-sync-done") : t("chat-sync-admins-hint")}
          onClick={() => {
            syncAdmins.mutate(undefined, {
              onSuccess: () => hapticResult(true),
              onError: () => hapticResult(false),
            });
          }}
        />
      </Card>
    </Screen>
  );
}
