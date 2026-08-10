/**
 * Reputation: the leaderboard, with a manual adjustment per member.
 *
 * DECISION: the adjustment field takes a delta, not a new total. An admin
 * correcting an abuse ("someone farmed +40 off alt accounts") knows the amount
 * to remove, not the number that should be left — and a delta is also what the
 * API's endpoint speaks, so no arithmetic happens in two places.
 */
import React, { useState } from "react";
import type { ReputationEntry } from "../api/client";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Row,
  Screen,
  SectionTitle,
  Spinner,
} from "../components/ui";
import { useT } from "../i18n/I18nProvider";
import { useAdjustReputation, useReputation } from "../hooks/queries";
import { hapticResult } from "../telegram/sdk";

function nameOf(entry: ReputationEntry): string {
  return (
    entry.display_name ??
    (entry.username != null ? `@${entry.username}` : String(entry.tg_user_id))
  );
}

function Adjuster({
  chatId,
  entry,
  onDone,
}: {
  chatId: number;
  entry: ReputationEntry;
  onDone: () => void;
}): React.JSX.Element {
  const t = useT();
  const adjust = useAdjustReputation(chatId);
  const [delta, setDelta] = useState("");
  const parsed = Number.parseInt(delta, 10);
  const valid = Number.isFinite(parsed) && parsed !== 0;

  return (
    <>
      <Card>
        <Row
          title={nameOf(entry)}
          subtitle={t("reputation-level", { level: entry.level })}
          right={<span className="tabular-nums text-hint">{entry.points}</span>}
        />
        <div className="px-4 py-3">
          <div className="text-[15px]">{t("reputation-adjust")}</div>
          <input
            className="tg-input mt-2 w-full tabular-nums"
            inputMode="numeric"
            value={delta}
            placeholder="-10"
            onChange={(event) => setDelta(event.target.value)}
          />
          <p className="mt-2 text-[13px] text-hint">{t("reputation-adjust-hint")}</p>
        </div>
      </Card>

      <div className="mt-6 space-y-3">
        <Button
          disabled={!valid || adjust.isPending}
          onClick={() =>
            adjust.mutate(
              { tgUserId: entry.tg_user_id, delta: parsed },
              {
                onSuccess: () => {
                  hapticResult(true);
                  onDone();
                },
                onError: () => hapticResult(false),
              },
            )
          }
        >
          {adjust.isPending ? t("panel-saving") : t("panel-save")}
        </Button>
        {adjust.isError && (
          <p className="text-center text-[13px] text-destructive">{adjust.error.message}</p>
        )}
        <Button variant="secondary" disabled={adjust.isPending} onClick={onDone}>
          {t("panel-cancel")}
        </Button>
      </div>
    </>
  );
}

export function ReputationScreen({ chatId }: { chatId: number }): React.JSX.Element {
  const t = useT();
  const reputation = useReputation(chatId);
  const [editing, setEditing] = useState<ReputationEntry | null>(null);

  if (editing !== null) {
    return (
      <Screen>
        <SectionTitle>{t("reputation-adjust")}</SectionTitle>
        <Adjuster chatId={chatId} entry={editing} onDone={() => setEditing(null)} />
      </Screen>
    );
  }

  return (
    <Screen>
      <SectionTitle>{t("reputation-title")}</SectionTitle>
      {reputation.isPending && <Spinner />}
      {reputation.isError && (
        <ErrorState
          message={reputation.error.message}
          onRetry={() => void reputation.refetch()}
        />
      )}
      {reputation.isSuccess && (
        <Card>
          {reputation.data.length === 0 ? (
            <EmptyState text={t("reputation-empty")} />
          ) : (
            reputation.data.map((entry) => (
              <Row
                key={entry.tg_user_id}
                title={nameOf(entry)}
                subtitle={t("reputation-level", { level: entry.level })}
                onClick={() => setEditing(entry)}
                right={
                  <span className="tabular-nums text-[15px]">{entry.points}</span>
                }
              />
            ))
          )}
        </Card>
      )}
    </Screen>
  );
}
