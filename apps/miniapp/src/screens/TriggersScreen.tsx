/**
 * Triggers: a keyword list, and an editor for one of them.
 *
 * DECISION: the editor is a screen, not a modal. A trigger has seven fields and
 * a multi-line reply; a sheet over the list would fight the keyboard on a phone,
 * and Telegram's back button already gives a pushed screen a way out.
 */
import React, { useState } from "react";
import type { TriggerCreate, TriggerEntry } from "../api/client";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Row,
  Screen,
  SectionTitle,
  Spinner,
  Toggle,
} from "../components/ui";
import { useT } from "../i18n/I18nProvider";
import {
  useCreateTrigger,
  useDeleteTrigger,
  useTriggers,
  useUpdateTrigger,
} from "../hooks/queries";
import { hapticResult } from "../telegram/sdk";

const MATCHES = ["exact", "contains", "regex"] as const;

const BLANK: TriggerCreate = {
  pattern: "",
  response: "",
  match: "contains",
  case_sensitive: false,
  delete_trigger: false,
  enabled: true,
};

function Editor({
  chatId,
  trigger,
  onDone,
}: {
  chatId: number;
  trigger: TriggerEntry | null;
  onDone: () => void;
}): React.JSX.Element {
  const t = useT();
  const create = useCreateTrigger(chatId);
  const update = useUpdateTrigger(chatId);
  const remove = useDeleteTrigger(chatId);
  const [draft, setDraft] = useState<TriggerCreate>(
    trigger === null
      ? BLANK
      : {
          pattern: trigger.pattern,
          response: trigger.response,
          match: trigger.match,
          case_sensitive: trigger.case_sensitive ?? false,
          delete_trigger: trigger.delete_trigger ?? false,
          enabled: trigger.enabled ?? true,
        },
  );

  const pending = create.isPending || update.isPending || remove.isPending;
  const failure = create.error ?? update.error;
  const valid = draft.pattern.trim() !== "" && draft.response.trim() !== "";

  const submit = (): void => {
    const handlers = {
      onSuccess: () => {
        hapticResult(true);
        onDone();
      },
      onError: () => hapticResult(false),
    };
    if (trigger === null) {
      create.mutate(draft, handlers);
    } else {
      update.mutate({ id: trigger.id, body: draft }, handlers);
    }
  };

  return (
    <>
      <Card>
        <div className="px-4 py-3">
          <div className="text-[15px]">{t("triggers-pattern")}</div>
          <input
            className="tg-input mt-2 w-full"
            value={draft.pattern}
            maxLength={256}
            spellCheck={false}
            onChange={(event) => setDraft({ ...draft, pattern: event.target.value })}
          />
        </div>
        <Row
          title={t("triggers-match")}
          right={
            <select
              className="bg-transparent text-right text-[15px] text-link outline-none"
              value={draft.match ?? "contains"}
              onChange={(event) =>
                setDraft({ ...draft, match: event.target.value as TriggerCreate["match"] })
              }
            >
              {MATCHES.map((match) => (
                <option key={match} value={match}>
                  {t(`triggers-match-${match}`)}
                </option>
              ))}
            </select>
          }
        />
        <Row
          title={t("triggers-case-sensitive")}
          right={
            <Toggle
              checked={draft.case_sensitive ?? false}
              onChange={(value) => setDraft({ ...draft, case_sensitive: value })}
            />
          }
        />
        <Row
          title={t("triggers-delete-source")}
          right={
            <Toggle
              checked={draft.delete_trigger ?? false}
              onChange={(value) => setDraft({ ...draft, delete_trigger: value })}
            />
          }
        />
        <div className="px-4 py-3">
          <div className="text-[15px]">{t("triggers-response")}</div>
          <textarea
            className="tg-input mt-2 h-32 w-full resize-y"
            value={draft.response}
            maxLength={4000}
            onChange={(event) => setDraft({ ...draft, response: event.target.value })}
          />
        </div>
      </Card>

      <div className="mt-6 space-y-3">
        <Button disabled={!valid || pending} onClick={submit}>
          {pending ? t("panel-saving") : t("panel-save")}
        </Button>
        {failure && (
          <p className="text-center text-[13px] text-destructive">{failure.message}</p>
        )}
        {trigger !== null && (
          <Button
            variant="destructive"
            disabled={pending}
            onClick={() => {
              if (!window.confirm(t("panel-confirm-delete"))) {
                return;
              }
              remove.mutate(trigger.id, {
                onSuccess: () => {
                  hapticResult(true);
                  onDone();
                },
                onError: () => hapticResult(false),
              });
            }}
          >
            {t("panel-delete")}
          </Button>
        )}
        <Button variant="secondary" disabled={pending} onClick={onDone}>
          {t("panel-cancel")}
        </Button>
      </div>
    </>
  );
}

export function TriggersScreen({ chatId }: { chatId: number }): React.JSX.Element {
  const t = useT();
  const triggers = useTriggers(chatId);
  // `undefined` is the list; `null` is a new trigger; an entry is that one.
  const [editing, setEditing] = useState<TriggerEntry | null | undefined>(undefined);

  if (editing !== undefined) {
    return (
      <Screen>
        <SectionTitle>{editing === null ? t("triggers-add") : t("panel-edit")}</SectionTitle>
        <Editor chatId={chatId} trigger={editing} onDone={() => setEditing(undefined)} />
      </Screen>
    );
  }

  return (
    <Screen>
      <SectionTitle>{t("triggers-title")}</SectionTitle>
      {triggers.isPending && <Spinner />}
      {triggers.isError && (
        <ErrorState message={triggers.error.message} onRetry={() => void triggers.refetch()} />
      )}
      {triggers.isSuccess && (
        <Card>
          {triggers.data.length === 0 ? (
            <EmptyState text={t("triggers-empty")} />
          ) : (
            triggers.data.map((trigger) => (
              <Row
                key={trigger.id}
                title={trigger.pattern}
                subtitle={trigger.response}
                onClick={() => setEditing(trigger)}
                right={
                  <span className="tabular-nums text-[13px] text-hint">{trigger.hits ?? 0}</span>
                }
              />
            ))
          )}
        </Card>
      )}
      <div className="mt-4">
        <Button onClick={() => setEditing(null)}>{t("triggers-add")}</Button>
      </div>
    </Screen>
  );
}
