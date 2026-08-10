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
  Row,
  Screen,
  SectionTitle,
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
import { hapticResult } from "../telegram/sdk";

const PLANS: readonly Plan[] = ["free", "pro", "business", "white_label"];

function Totals(): React.JSX.Element {
  const t = useT();
  const stats = usePlatformStats();

  if (stats.isPending) {
    return <Spinner />;
  }
  if (stats.isError) {
    return <ErrorState message={stats.error.message} onRetry={() => void stats.refetch()} />;
  }

  const cells: [string, string | number][] = [
    ["platform-chats", stats.data.total_chats],
    ["platform-active-chats", stats.data.active_chats],
    ["platform-revenue-stars", stats.data.revenue_stars],
    ["platform-revenue-usd", stats.data.revenue_usd],
    ["platform-bans", stats.data.global_bans],
  ];

  return (
    <>
      <div className="grid grid-cols-2 gap-2">
        {cells.map(([key, value]) => (
          <div key={key} className="tg-card px-4 py-3">
            <div className="text-[22px] font-semibold tabular-nums">{value}</div>
            <div className="text-[13px] text-hint">{t(key)}</div>
          </div>
        ))}
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
      className="text-[13px] text-destructive"
      disabled={revoke.isPending}
      onClick={() =>
        revoke.mutate(ban.tg_user_id, {
          onSuccess: () => hapticResult(true),
          onError: () => hapticResult(false),
        })
      }
    >
      {t("platform-ban-revoke")}
    </button>
  );

  return (
    <>
      <SectionTitle>{t("platform-bans-title")}</SectionTitle>
      {bans.isPending && <Spinner />}
      {bans.isError && (
        <ErrorState message={bans.error.message} onRetry={() => void bans.refetch()} />
      )}
      {bans.isSuccess && (
        <Card>
          {bans.data.length === 0 ? (
            <EmptyState text={t("platform-bans-empty")} />
          ) : (
            bans.data.map((ban) => (
              <Row
                key={ban.id}
                title={String(ban.tg_user_id)}
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
        <div className="px-4 py-3">
          <div className="text-[15px]">{t("platform-ban-user-id")}</div>
          <input
            className="tg-input mt-2 w-full tabular-nums"
            inputMode="numeric"
            value={userId}
            onChange={(event) => setUserId(event.target.value)}
          />
        </div>
        <div className="px-4 py-3">
          <div className="text-[15px]">{t("platform-ban-reason")}</div>
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
          <p className="mt-2 text-center text-[13px] text-destructive">
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
          <div className="text-[15px]">{t("platform-broadcast-text")}</div>
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
                onChange={(on) => toggle(plan, on)}
              />
            }
          />
        ))}
      </Card>

      <div className="mt-3 space-y-2">
        <Button
          disabled={text.trim() === "" || plans.length === 0 || broadcast.isPending}
          onClick={() => {
            if (!window.confirm(t("platform-broadcast-confirm"))) {
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
        {broadcast.isSuccess && (
          <p className="text-center text-[13px] text-hint">{broadcast.data.detail}</p>
        )}
        {broadcast.isError && (
          <p className="text-center text-[13px] text-destructive">
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
      <SectionTitle>{t("platform-title")}</SectionTitle>
      <Totals />
      <Blacklist />
      <Broadcast />
    </Screen>
  );
}
