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
import { useI18n, useT } from "../i18n/I18nProvider";
import { useCreatePost, useDeletePost, usePosts, useUpdatePost } from "../hooks/queries";
import { hapticResult } from "../telegram/sdk";

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
        <div className="text-[15px]">{t("posts-cron")}</div>
        <input
          className="tg-input mt-2 w-full font-mono"
          value={value}
          spellCheck={false}
          onChange={(event) => onChange(event.target.value)}
        />
        <p className="mt-2 text-[13px] text-hint">{t("posts-cron-hint")}</p>
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
          className="bg-transparent text-right text-[15px] text-link outline-none"
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
          <div className="text-[15px]">{t("posts-name")}</div>
          <input
            className="tg-input mt-2 w-full"
            value={title}
            maxLength={128}
            onChange={(event) => setTitle(event.target.value)}
          />
        </div>
        <div className="px-4 py-3">
          <div className="text-[15px]">{t("posts-text")}</div>
          <textarea
            className="tg-input mt-2 h-40 w-full resize-y"
            value={content}
            maxLength={4000}
            onChange={(event) => setContent(event.target.value)}
          />
        </div>
      </Card>

      <SectionTitle>{t("posts-schedule")}</SectionTitle>
      <div className="mb-2 flex gap-2">
        {KINDS.map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => switchKind(option)}
            className={`flex-1 rounded-lg px-3 py-2 text-[14px] ${
              option === kind ? "bg-accent text-accent-text" : "bg-surface text-link"
            }`}
          >
            {t(`posts-schedule-${option}`)}
          </button>
        ))}
      </div>
      <Card>
        <ScheduleInput kind={kind} value={value} onChange={setValue} />
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
        {failure && <p className="text-center text-[13px] text-destructive">{failure.message}</p>}
        {post !== null && (
          <Button
            variant="destructive"
            disabled={pending}
            onClick={() => {
              if (!window.confirm(t("panel-confirm-delete"))) {
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
        <Button variant="secondary" disabled={pending} onClick={onDone}>
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
        <SectionTitle>{editing === null ? t("posts-add") : t("panel-edit")}</SectionTitle>
        <Editor chatId={chatId} post={editing} onDone={() => setEditing(undefined)} />
      </Screen>
    );
  }

  return (
    <Screen>
      <SectionTitle>{t("posts-title")}</SectionTitle>
      {posts.isPending && <Spinner />}
      {posts.isError && (
        <ErrorState message={posts.error.message} onRetry={() => void posts.refetch()} />
      )}
      {posts.isSuccess && (
        <Card>
          {posts.data.length === 0 ? (
            <EmptyState text={t("posts-empty")} />
          ) : (
            posts.data.map((post) => (
              <Row
                key={post.id}
                title={post.title || post.content}
                subtitle={t("posts-next-run", {
                  when: describe(post, locale, t("field-unset")),
                })}
                onClick={() => setEditing(post)}
                right={
                  post.enabled ? undefined : (
                    <span className="text-[13px] text-hint">{t("posts-paused")}</span>
                  )
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
