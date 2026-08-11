/**
 * Scheduled posts: the queue, and an editor for one entry.
 *
 * DECISION: the schedule input follows the kind, because the three kinds are not
 * the same kind of moment. A one-off is an instant, so it uses
 * `datetime-local` and converts to UTC — the device's clock is where the user
 * picked it. `daily` and `cron` are wall-clock rules that the worker resolves in
 * the chat's timezone, so they stay as the plain `HH:MM` and cron text the API
 * stores; converting those would turn "09:00 in this chat" into "09:00 wherever
 * the admin happened to be standing".
 */
import React, { useState } from "react";
import type { PostCreate, PostEntry, ScheduleKind } from "../api/client";
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
import { useI18n, useT } from "../i18n/I18nProvider";
import { useCreatePost, useDeletePost, usePosts, useUpdatePost } from "../hooks/queries";
import { useDiscardGuard } from "../hooks/useDiscardGuard";
import { askConfirmation, hapticResult } from "../telegram/sdk";

const KINDS: readonly ScheduleKind[] = ["once", "daily", "cron"];

const DEFAULTS: Record<ScheduleKind, string> = {
  once: "",
  daily: "09:00",
  cron: "0 9 * * *",
};

/** `2026-08-10T09:30` in device-local time → the UTC instant the API stores. */
function toInstant(local: string): string {
  return new Date(local).toISOString();
}

/** The inverse, for editing an existing one-off. */
function toLocalInput(instant: string): string {
  const at = new Date(instant);
  const pad = (value: number): string => String(value).padStart(2, "0");
  return `${at.getFullYear()}-${pad(at.getMonth() + 1)}-${pad(at.getDate())}T${pad(at.getHours())}:${pad(at.getMinutes())}`;
}

function formatWhen(instant: string, locale: string): string {
  return new Date(instant).toLocaleString(locale, {
    dateStyle: "short",
    timeStyle: "short",
  });
}

/** The stored value for a kind, in the shape that kind's input wants. */
function toInput(kind: ScheduleKind, stored: string): string {
  if (kind !== "once") {
    return stored;
  }
  const parsed = new Date(stored);
  return Number.isNaN(parsed.getTime()) ? "" : toLocalInput(stored);
}

/**
 * The three kinds, as one choice.
 *
 * DECISION: a column of rows with a checkmark, not a horizontal segmented
 * control. The kinds are a single either/or and must read as one control, but
 * the triggers editor makes the same choice over labels like "Регулярное
 * выражение", which cannot fit three across a phone — and a mode picker that
 * changes shape depending on how long the words happen to be is worse than one
 * that does not. Telegram's own single-choice lists are vertical for this reason.
 */
function KindPicker({
  kind,
  onPick,
}: {
  kind: ScheduleKind;
  onPick: (next: ScheduleKind) => void;
}): React.JSX.Element {
  const t = useT();
  return (
    <>
      {KINDS.map((option) => (
        <Row
          key={option}
          title={t(`posts-schedule-${option}`)}
          onClick={() => onPick(option)}
          // The check is always rendered and merely hidden when unselected: it
          // holds the column width steady as the choice moves, and giving `Row` a
          // `right` is what stops it drawing a chevron on a row that picks rather
          // than navigates.
          right={
            <Icon
              name="check"
              size={18}
              className={option === kind ? "text-accent" : "invisible"}
            />
          }
        />
      ))}
    </>
  );
}

function ScheduleInput({
  kind,
  value,
  onChange,
}: {
  kind: ScheduleKind;
  value: string;
  onChange: (value: string) => void;
}): React.JSX.Element {
  const t = useT();
  if (kind === "cron") {
    return (
      <div className="px-4 py-3">
        <div className="text-row">{t("posts-cron")}</div>
        <input
          className="tg-input mt-2 w-full font-mono"
          value={value}
          spellCheck={false}
          onChange={(event) => onChange(event.target.value)}
        />
        <p className="mt-2 text-label text-hint">{t("posts-cron-hint")}</p>
      </div>
    );
  }
  return (
    <Row
      title={kind === "once" ? t("posts-run-at") : t("posts-time")}
      subtitle={kind === "daily" ? t("posts-daily-hint") : undefined}
      right={
        <input
          type={kind === "once" ? "datetime-local" : "time"}
          // Seated on the ground colour, so the value reads as something you can
          // tap and edit rather than as a stated fact like the rows above it.
          className="rounded-control bg-ground px-2.5 py-1.5 text-right text-row text-link outline-none"
          value={value}
          onChange={(event) => onChange(event.target.value)}
        />
      }
    />
  );
}

function Editor({
  chatId,
  post,
  onDone,
}: {
  chatId: number;
  post: PostEntry | null;
  onDone: () => void;
}): React.JSX.Element {
  const t = useT();
  const create = useCreatePost(chatId);
  const update = useUpdatePost(chatId);
  const remove = useDeletePost(chatId);

  const [title, setTitle] = useState(post?.title ?? "");
  const [content, setContent] = useState(post?.content ?? "");
  const [kind, setKind] = useState<ScheduleKind>(post?.schedule_kind ?? "daily");
  const [value, setValue] = useState(
    post === null ? DEFAULTS.daily : toInput(post.schedule_kind, post.schedule_value),
  );
  const [pin, setPin] = useState(post?.pin ?? false);
  const [deletePrevious, setDeletePrevious] = useState(post?.delete_previous ?? false);
  const [enabled, setEnabled] = useState(post?.enabled ?? true);

  const pending = create.isPending || update.isPending || remove.isPending;
  const failure = create.error ?? update.error ?? remove.error;
  const valid = content.trim() !== "" && value.trim() !== "";

  /*
   * Every field against the value it opened with, so a change made and undone
   * leaves the form clean. A new post starts dirty the moment anything is typed,
   * which is what the blank defaults below compare against.
   */
  const dirty =
    title !== (post?.title ?? "") ||
    content !== (post?.content ?? "") ||
    kind !== (post?.schedule_kind ?? "daily") ||
    value !==
      (post === null ? DEFAULTS.daily : toInput(post.schedule_kind, post.schedule_value)) ||
    pin !== (post?.pin ?? false) ||
    deletePrevious !== (post?.delete_previous ?? false) ||
    enabled !== (post?.enabled ?? true);
  const confirmDiscard = useDiscardGuard({ dirty, onClose: onDone });
  const leave = (): void => {
    void confirmDiscard().then((may) => {
      if (may) {
        onDone();
      }
    });
  };

  /** Each kind speaks its own dialect, so switching kinds starts from a default. */
  const switchKind = (next: ScheduleKind): void => {
    setKind(next);
    setValue(next === post?.schedule_kind ? toInput(next, post.schedule_value) : DEFAULTS[next]);
  };

  const submit = (): void => {
    const body: PostCreate = {
      title,
      content,
      schedule_kind: kind,
      schedule_value: kind === "once" ? toInstant(value) : value,
      pin,
      delete_previous: deletePrevious,
      enabled,
    };
    const handlers = {
      onSuccess: () => {
        hapticResult(true);
        onDone();
      },
      onError: () => hapticResult(false),
    };
    if (post === null) {
      create.mutate(body, handlers);
    } else {
      update.mutate({ id: post.id, body }, handlers);
    }
  };

  return (
    <>
      <Card>
        <div className="px-4 py-3">
          <div className="text-row">{t("posts-name")}</div>
          <input
            className="tg-input mt-2 w-full"
            value={title}
            maxLength={128}
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>
        <div className="px-4 py-3">
          <div className="text-row">{t("posts-text")}</div>
          <textarea
            className="tg-input mt-2 h-40 w-full resize-y"
            value={content}
            maxLength={4000}
            onChange={(event) => setContent(event.target.value)}
          />
        </div>
      </Card>

      <SectionTitle>{t("posts-schedule")}</SectionTitle>
      {/* The kind and the value it takes are one decision, so they share a card:
          picking a row above changes the field directly below it. */}
      <Card>
        <KindPicker kind={kind} onPick={switchKind} />
        <ScheduleInput kind={kind} value={value} onChange={setValue} />
      </Card>

      <Card className="mt-2">
        <Row title={t("posts-pin")} right={<Toggle checked={pin} onChange={setPin} />} />
        <Row
          title={t("posts-delete-previous")}
          right={<Toggle checked={deletePrevious} onChange={setDeletePrevious} />}
        />
        <Row
          title={t("posts-enabled")}
          right={<Toggle checked={enabled} onChange={setEnabled} />}
        />
      </Card>

      <div className="mt-6 space-y-3">
        <Button disabled={!valid || pending} onClick={submit}>
          {pending ? t("panel-saving") : t("panel-save")}
        </Button>
        {failure && <p className="text-center text-label text-destructive">{failure.message}</p>}
        {post !== null && (
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
              remove.mutate(post.id, {
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

/** What a row says under the title: when it next fires, or the rule itself. */
function describe(post: PostEntry, locale: string, unset: string): string {
  if (post.next_run_at != null) {
    return formatWhen(post.next_run_at, locale);
  }
  return post.schedule_value || unset;
}

export function PostsScreen({ chatId }: { chatId: number }): React.JSX.Element {
  const { t, locale } = useI18n();
  const posts = usePosts(chatId);
  // `undefined` is the list; `null` is a new post; an entry is that one.
  const [editing, setEditing] = useState<PostEntry | null | undefined>(undefined);

  if (editing !== undefined) {
    return (
      <Screen>
        <Header
          title={editing === null ? t("posts-add") : t("panel-edit")}
          icon={editing === null ? "plus" : "clock"}
        />
        <Editor chatId={chatId} post={editing} onDone={() => setEditing(undefined)} />
      </Screen>
    );
  }

  return (
    <Screen>
      <Header title={t("posts-title")} icon="clock" />
      {posts.isPending && <SkeletonRows />}
      {posts.isError && (
        <ErrorState message={posts.error.message} onRetry={() => void posts.refetch()} />
      )}
      {posts.isSuccess && (
        <Card>
          {posts.data.length === 0 ? (
            <EmptyState text={t("posts-empty")} icon="clock" />
          ) : (
            posts.data.map((post) => (
              <Row
                key={post.id}
                title={post.title || post.content}
                subtitle={t("posts-next-run", {
                  when: describe(post, locale, t("field-unset")),
                })}
                onClick={() => setEditing(post)}
                // The badge fills `right`, which would otherwise drop the
                // automatic chevron — a post still opens an editor.
                chevron
                right={
                  <Badge tone={post.enabled ? "success" : "neutral"}>
                    {post.enabled ? t("posts-enabled") : t("posts-paused")}
                  </Badge>
                }
              />
            ))
          )}
        </Card>
      )}
      <div className="mt-4">
        <Button onClick={() => setEditing(null)}>{t("posts-add")}</Button>
      </div>
    </Screen>
  );
}
