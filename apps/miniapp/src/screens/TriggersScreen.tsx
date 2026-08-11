/**
 * Triggers: a keyword list, and an editor for one of them.
 *
 * DECISION: the editor is a screen, not a modal. A trigger has seven fields and
 * a multi-line reply; a sheet over the list would fight the keyboard on a phone,
 * and Telegram's back button already gives a pushed screen a way out.
 */
import React, { useMemo, useState } from "react";
import type { TriggerCreate, TriggerEntry } from "../api/client";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Header,
  Icon,
  Row,
  Screen,
  SectionTitle,
  SkeletonRows,
  Toggle,
} from "../components/ui";
import { useT } from "../i18n/I18nProvider";
import {
  useCreateTrigger,
  useDeleteTrigger,
  useTriggers,
  useUpdateTrigger,
} from "../hooks/queries";
import { useDiscardGuard } from "../hooks/useDiscardGuard";
import { askConfirmation, hapticResult } from "../telegram/sdk";

const MATCHES = ["exact", "contains", "regex"] as const;

const BLANK: TriggerCreate = {
  pattern: "",
  response: "",
  match: "contains",
  case_sensitive: false,
  delete_trigger: false,
  enabled: true,
};

/**
 * The three match modes, as one choice.
 *
 * DECISION: a column of rows with a checkmark, replacing the native `<select>`.
 * A dropdown hides two of the three modes behind a tap and renders as whatever
 * the OS feels like, which is the one control on the screen that could not be
 * themed; spelling the modes out costs two rows and makes the choice legible at
 * rest. Horizontal segments were the other option and do not survive
 * "Регулярное выражение" three across a phone.
 */
function MatchPicker({
  match,
  onPick,
  disabled,
}: {
  match: TriggerCreate["match"];
  onPick: (next: TriggerCreate["match"]) => void;
  disabled: boolean;
}): React.JSX.Element {
  const t = useT();
  return (
    <>
      {MATCHES.map((option) => (
        <Row
          key={option}
          title={t(`triggers-match-${option}`)}
          onClick={() => onPick(option)}
          disabled={disabled}
          // The check is always rendered and merely hidden when unselected: it
          // holds the column width steady as the choice moves, and giving `Row` a
          // `right` is what stops it drawing a chevron on a row that picks rather
          // than navigates.
          right={
            <Icon
              name="check"
              size={18}
              className={option === match ? "text-accent" : "invisible"}
            />
          }
        />
      ))}
    </>
  );
}

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
  const initial = useMemo<TriggerCreate>(
    () =>
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
    [trigger],
  );
  const [draft, setDraft] = useState<TriggerCreate>(initial);

  /*
   * DECISION: `pending` locks the fields, not just the buttons. It used to grey
   * out the three buttons and leave every input, picker and switch live — so a
   * character typed while the request was in flight went into a draft the
   * response then replaced, and the edit vanished with nothing to say it had.
   * The form is being sent; there is no such thing as a change to it that still
   * counts.
   */
  const pending = create.isPending || update.isPending || remove.isPending;
  const failure = create.error ?? update.error;
  const valid = draft.pattern.trim() !== "" && draft.response.trim() !== "";

  /*
   * Compared field by field against what the editor opened with, so typing a
   * character and deleting it again leaves the form clean. A boolean flipped by
   * the first `setDraft` would call that dirty and ask on the way out.
   */
  const dirty = (Object.keys(initial) as (keyof TriggerCreate)[]).some(
    (key) => draft[key] !== initial[key],
  );
  const confirmDiscard = useDiscardGuard({ dirty, onClose: onDone });
  const leave = (): void => {
    void confirmDiscard().then((may) => {
      if (may) {
        onDone();
      }
    });
  };

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
          <div className="text-row">{t("triggers-pattern")}</div>
          <input
            className="tg-input mt-2 w-full"
            value={draft.pattern}
            maxLength={256}
            spellCheck={false}
            disabled={pending}
            onChange={(event) => setDraft({ ...draft, pattern: event.target.value })}
          />
        </div>
      </Card>

      <SectionTitle>{t("triggers-match")}</SectionTitle>
      <Card>
        <MatchPicker
          match={draft.match ?? "contains"}
          disabled={pending}
          onPick={(next) => setDraft({ ...draft, match: next })}
        />
      </Card>

      <Card className="mt-2">
        <Row
          title={t("triggers-case-sensitive")}
          right={
            <Toggle
              checked={draft.case_sensitive ?? false}
              label={t("triggers-case-sensitive")}
              disabled={pending}
              onChange={(value) => setDraft({ ...draft, case_sensitive: value })}
            />
          }
        />
        <Row
          title={t("triggers-delete-source")}
          right={
            <Toggle
              checked={draft.delete_trigger ?? false}
              label={t("triggers-delete-source")}
              disabled={pending}
              onChange={(value) => setDraft({ ...draft, delete_trigger: value })}
            />
          }
        />
      </Card>

      <Card className="mt-2">
        <div className="px-4 py-3">
          <div className="text-row">{t("triggers-response")}</div>
          <textarea
            className="tg-input mt-2 h-32 w-full resize-y"
            value={draft.response}
            maxLength={4000}
            disabled={pending}
            onChange={(event) => setDraft({ ...draft, response: event.target.value })}
          />
        </div>
      </Card>

      <div className="mt-6 space-y-3">
        <Button disabled={!valid || pending} onClick={submit}>
          {pending ? t("panel-saving") : t("panel-save")}
        </Button>
        {failure && <p className="text-center text-label text-destructive">{failure.message}</p>}
        {trigger !== null && (
          <Button
            variant="destructive"
            disabled={pending}
            onClick={async () => {
              const confirmed = await askConfirmation({
                message: t("panel-confirm-delete"),
                confirmText: t("panel-delete"),
                cancelText: t("panel-cancel"),
                destructive: true,
              });
              if (!confirmed) {
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
        <Button variant="secondary" disabled={pending} onClick={leave}>
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
        <Header
          title={editing === null ? t("triggers-add") : t("panel-edit")}
          icon={editing === null ? "plus" : "spark"}
        />
        <Editor chatId={chatId} trigger={editing} onDone={() => setEditing(undefined)} />
      </Screen>
    );
  }

  return (
    <Screen>
      <Header title={t("triggers-title")} icon="spark" />
      {triggers.isPending && <SkeletonRows />}
      {triggers.isError && (
        <ErrorState message={triggers.error.message} onRetry={() => void triggers.refetch()} />
      )}
      {triggers.isSuccess && (
        <Card>
          {triggers.data.length === 0 ? (
            <EmptyState text={t("triggers-empty")} icon="spark" />
          ) : (
            triggers.data.map((trigger) => (
              <Row
                key={trigger.id}
                title={trigger.pattern}
                subtitle={trigger.response}
                onClick={() => setEditing(trigger)}
                // The hit count fills `right`, which would otherwise drop the
                // automatic chevron — a trigger still opens an editor.
                chevron
                right={
                  <Badge>
                    <span className="tabular-nums">{trigger.hits ?? 0}</span>
                  </Badge>
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
