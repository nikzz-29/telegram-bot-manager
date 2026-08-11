/**
 * The platform operator's screen: totals, the global blacklist, and broadcast.
 *
 * DECISION: this screen is reachable only when `/auth/me` says the caller is a
 * superadmin, and every endpoint it calls re-checks that server-side. Hiding the
 * entry point is for tidiness, not security — the panel is JavaScript in a
 * webview, and a hidden button is not an authorization decision.
 */
import React, { useState } from "react";
import type { GlobalBanEntry, Plan } from "../api/client";
import {
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
  Spinner,
  Toggle,
} from "../components/ui";
import { useT } from "../i18n/I18nProvider";
import {
  useBroadcast,
  useCreateGlobalBan,
  useGlobalBans,
  usePlatformStats,
  useRevokeGlobalBan,
} from "../hooks/queries";
import { askConfirmation, hapticResult } from "../telegram/sdk";

const PLANS: readonly Plan[] = ["free", "pro", "business", "white_label"];

/**
 * One figure and what it counts.
 *
 * DECISION: a local component, not a new shared primitive. This is the only
 * screen in the panel that reports platform-wide numbers, and a stat tile
 * promoted into `ui.tsx` on a sample size of one would be a guess at what the
 * next caller needs rather than a contract.
 */
function Stat({
  value,
  label,
  className = "",
}: {
  value: string | number;
  label: string;
  className?: string;
}): React.JSX.Element {
  return (
    <Card className={`px-4 py-3 ${className}`}>
      {/* Tabular figures so the numbers line up column to column as they change. */}
      <div className="text-display font-semibold tabular-nums">{value}</div>
      <div className="mt-0.5 text-label text-hint">{label}</div>
    </Card>
  );
}

function Totals(): React.JSX.Element {
  const t = useT();
  const stats = usePlatformStats();

  // DECISION: a spinner here, not a skeleton. What is loading is five numbers
  // and a four-row breakdown, and a skeleton's whole point is to hold the shape
  // of a list of unknown length — this block's shape is fixed and short enough
  // that the placeholder would be more furniture than the content.
  if (stats.isPending) {
    return <Spinner />;
  }
  if (stats.isError) {
    return <ErrorState message={stats.error.message} onRetry={() => void stats.refetch()} />;
  }

  const figures: [string, string | number][] = [
    ["platform-chats", stats.data.total_chats],
    ["platform-active-chats", stats.data.active_chats],
    ["platform-revenue-stars", stats.data.revenue_stars],
    ["platform-revenue-usd", stats.data.revenue_usd],
  ];

  return (
    <>
      <div className="mt-3 grid grid-cols-2 gap-2">
        {figures.map(([key, value]) => (
          <Stat key={key} value={value} label={t(key)} />
        ))}
        {/* The blacklist total spans the pair: it belongs to the section below,
            not to the chat-and-revenue grid, and a fifth half-width tile would
            just look like a sixth had failed to load. */}
        <Stat
          value={stats.data.global_bans}
          label={t("platform-bans")}
          className="col-span-2"
        />
      </div>
      <Card className="mt-2">
        {PLANS.map((plan) => (
          <Row
            key={plan}
            title={t(`plan-${plan}`)}
            right={
              <span className="tabular-nums text-hint">
                {stats.data.chats_by_plan[plan] ?? 0}
              </span>
            }
          />
        ))}
      </Card>
    </>
  );
}

function Blacklist(): React.JSX.Element {
  const t = useT();
  const bans = useGlobalBans();
  const create = useCreateGlobalBan();
  const revoke = useRevokeGlobalBan();
  const [userId, setUserId] = useState("");
  const [reason, setReason] = useState("");

  const parsed = Number.parseInt(userId, 10);
  const valid = Number.isFinite(parsed) && parsed > 0;

  const rowRight = (ban: GlobalBanEntry): React.JSX.Element => (
    <button
      type="button"
      className="flex items-center gap-1 text-label text-destructive disabled:opacity-50"
      disabled={revoke.isPending}
      onClick={() =>
        revoke.mutate(ban.tg_user_id, {
          onSuccess: () => hapticResult(true),
          onError: () => hapticResult(false),
        })
      }
    >
      <Icon name="trash" size={16} />
      {t("platform-ban-revoke")}
    </button>
  );

  return (
    <>
      <SectionTitle>{t("platform-bans-title")}</SectionTitle>
      {bans.isPending && <SkeletonRows />}
      {bans.isError && (
        <ErrorState message={bans.error.message} onRetry={() => void bans.refetch()} />
      )}
      {bans.isSuccess && (
        <Card>
          {bans.data.length === 0 ? (
            <EmptyState text={t("platform-bans-empty")} icon="shield" />
          ) : (
            bans.data.map((ban) => (
              <Row
                key={ban.id}
                title={String(ban.tg_user_id)}
                // DECISION: the tile is destructive but the title is not. Every
                // row in this list is a ban, so `destructive` on the row itself
                // would turn the whole card red and stop distinguishing
                // anything — the tone belongs on the mark, not on the ID.
                icon="shield"
                iconTone="destructive"
                subtitle={
                  ban.reason ||
                  t("platform-ban-chats", { count: ban.chat_count })
                }
                right={rowRight(ban)}
              />
            ))
          )}
        </Card>
      )}

      <Card className="mt-3">
        <div className="border-b border-separator px-4 py-3">
          <div className="text-row">{t("platform-ban-user-id")}</div>
          <input
            className="tg-input mt-2 w-full tabular-nums"
            inputMode="numeric"
            value={userId}
            onChange={(event) => setUserId(event.target.value)}
          />
        </div>
        <div className="px-4 py-3">
          <div className="text-row">{t("platform-ban-reason")}</div>
          <input
            className="tg-input mt-2 w-full"
            value={reason}
            maxLength={256}
            onChange={(event) => setReason(event.target.value)}
          />
        </div>
      </Card>
      <div className="mt-3">
        <Button
          variant="destructive"
          disabled={!valid || create.isPending}
          onClick={() =>
            create.mutate(
              { tg_user_id: parsed, reason },
              {
                onSuccess: () => {
                  setUserId("");
                  setReason("");
                  hapticResult(true);
                },
                onError: () => hapticResult(false),
              },
            )
          }
        >
          {t("platform-ban-add")}
        </Button>
        {create.isError && (
          <p className="mt-2 text-center text-label text-destructive">
            {create.error.message}
          </p>
        )}
      </div>
    </>
  );
}
function Broadcast(): React.JSX.Element {
  const t = useT();
  const broadcast = useBroadcast();
  const [text, setText] = useState("");
  const [plans, setPlans] = useState<Plan[]>([...PLANS]);

  const toggle = (plan: Plan, on: boolean): void => {
    setPlans((current) =>
      on ? [...current, plan] : current.filter((entry) => entry !== plan),
    );
  };

  return (
    <>
      <SectionTitle>{t("platform-broadcast-title")}</SectionTitle>
      <Card>
        <div className="px-4 py-3">
          <div className="text-row">{t("platform-broadcast-text")}</div>
          <textarea
            className="tg-input mt-2 h-32 w-full resize-y"
            value={text}
            maxLength={4000}
            onChange={(event) => setText(event.target.value)}
          />
        </div>
      </Card>

      <SectionTitle>{t("platform-broadcast-plans")}</SectionTitle>
      <Card>
        {PLANS.map((plan) => (
          <Row
            key={plan}
            title={t(`plan-${plan}`)}
            right={
              <Toggle
                checked={plans.includes(plan)}
                label={t(`plan-${plan}`)}
                onChange={(on) => toggle(plan, on)}
              />
            }
          />
        ))}
      </Card>

      <div className="mt-3 space-y-2">
        <Button
          disabled={text.trim() === "" || plans.length === 0 || broadcast.isPending}
          onClick={async () => {
            const confirmed = await askConfirmation({
              message: t("platform-broadcast-confirm"),
              confirmText: t("platform-broadcast-send"),
              cancelText: t("panel-cancel"),
              // Not destructive — nothing is deleted — but it is irreversible
              // and goes to every chat at once, so it still gets a gate.
              destructive: false,
            });
            if (!confirmed) {
              return;
            }
            broadcast.mutate(
              { text, plans },
              {
                onSuccess: () => {
                  setText("");
                  hapticResult(true);
                },
                onError: () => hapticResult(false),
              },
            );
          }}
        >
          {broadcast.isPending ? t("panel-saving") : t("platform-broadcast-send")}
        </Button>
        {/* `detail` carries the chat count as a bare string — rendering it raw
            printed "47" under the button with nothing saying what 47 was. */}
        {broadcast.isSuccess && (
          <p className="text-center text-label text-hint">
            {t("platform-broadcast-queued", {
              count: Number.parseInt(broadcast.data.detail, 10) || 0,
            })}
          </p>
        )}
        {broadcast.isError && (
          <p className="text-center text-label text-destructive">
            {broadcast.error.message}
          </p>
        )}
      </div>
    </>
  );
}

export function PlatformScreen(): React.JSX.Element {
  const t = useT();
  return (
    <Screen>
      <Header title={t("platform-title")} icon="globe" />
      <Totals />
      <Blacklist />
      <Broadcast />
    </Screen>
  );
}
