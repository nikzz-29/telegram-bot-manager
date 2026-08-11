/**
 * Reputation: the leaderboard, with a manual adjustment per member.
 *
 * DECISION: the adjustment is a delta, not a new total. An admin correcting an
 * abuse ("someone farmed +40 off alt accounts") knows the amount to remove, not
 * the number that should be left — and a delta is also what the API's endpoint
 * speaks, so no arithmetic happens in two places.
 *
 * DECISION: that delta is entered as a direction plus a count rather than as a
 * signed number. See the comment on `sign` in `Adjuster`.
 */
import React, { useState } from "react";
import type { ReputationEntry } from "../api/client";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Header,
  Row,
  Screen,
  SectionTitle,
  SegmentedControl,
  SkeletonRows,
  VALUE_INPUT,
} from "../components/ui";
import { useT } from "../i18n/I18nProvider";
import { useAdjustReputation, useReputation } from "../hooks/queries";
import { useDiscardGuard } from "../hooks/useDiscardGuard";
import { hapticResult } from "../telegram/sdk";

/** Which way the amount below it goes. */
type Sign = "add" | "remove";

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
  /*
   * DECISION: the sign is a control, not a character in the field. The delta is
   * usually negative — the reason an admin opens this screen is almost always
   * points someone should not have — and the field asked for that minus from an
   * `inputMode="numeric"` keypad, which on iOS has no minus key at all. Its own
   * placeholder read "-10", a value the keyboard it summons cannot type.
   *
   * Splitting them also lets the field state the amount as a plain count, which
   * is how the person doing it thinks about it: take 10 points away, not add -10.
   */
  const [sign, setSign] = useState<Sign>("remove");
  const [amount, setAmount] = useState("");
  const magnitude = Number.parseInt(amount, 10);
  const valid = Number.isFinite(magnitude) && magnitude > 0;
  const delta = sign === "remove" ? -magnitude : magnitude;

  // One field, so dirtiness is just "something is typed". The sign alone is not
  // a draft: it opens on a value, and flipping it back and forth changes nothing
  // until an amount exists to apply it to.
  const confirmDiscard = useDiscardGuard({ dirty: amount !== "", onClose: onDone });
  const leave = (): void => {
    void confirmDiscard().then((may) => {
      if (may) {
        onDone();
      }
    });
  };

  return (
    <>
      <Card>
        <Row
          title={nameOf(entry)}
          subtitle={t("reputation-level", { level: entry.level })}
        />
        {/*
         * DECISION: the score gets its own labelled row here, where on the list
         * it sits unlabelled at the end of the member's row. Unlabelled is right
         * while you are scanning a leaderboard and wrong the moment you are about
         * to change the number — this is the value the delta below applies to,
         * and it should say so.
         */}
        <Row
          title={t("reputation-score")}
          right={<span className="text-row tabular-nums">{entry.points}</span>}
        />
      </Card>

      <SectionTitle>{t("reputation-adjust")}</SectionTitle>
      <Card>
        <div className="px-4 py-3">
          <SegmentedControl<Sign>
            value={sign}
            onChange={setSign}
            disabled={adjust.isPending}
            options={[
              { value: "add", label: t("reputation-adjust-add") },
              { value: "remove", label: t("reputation-adjust-remove") },
            ]}
          />
        </div>
        <Row
          title={t("reputation-adjust-amount")}
          // The arithmetic is done here rather than left to the admin. The field
          // takes a count and the control above says which way it goes; what the
          // person actually wants to know is the number the member ends up with.
          subtitle={
            valid ? t("reputation-adjust-result", { total: entry.points + delta }) : undefined
          }
          right={
            <input
              className={`w-24 tabular-nums ${VALUE_INPUT}`}
              inputMode="numeric"
              value={amount}
              placeholder="10"
              disabled={adjust.isPending}
              onChange={(event) => setAmount(event.target.value.replace(/\D/g, ""))}
            />
          }
        />
      </Card>
      {/* Telegram puts the sentence that qualifies a field under the group, not
          inside it — the field is the control, this is the caveat about it. */}
      <p className="px-1 pt-2 text-label text-hint">{t("reputation-adjust-hint")}</p>

      <div className="mt-6 space-y-3">
        <Button
          disabled={!valid || adjust.isPending}
          onClick={() =>
            adjust.mutate(
              { tgUserId: entry.tg_user_id, delta },
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
          <p className="text-center text-label text-destructive">{adjust.error.message}</p>
        )}
        <Button variant="secondary" disabled={adjust.isPending} onClick={leave}>
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
        {/* The same title as the list it came from: this is still reputation,
            one member deep. The group heading below says what is being done. */}
        <Header title={t("reputation-title")} icon="star" />
        <Adjuster chatId={chatId} entry={editing} onDone={() => setEditing(null)} />
      </Screen>
    );
  }

  return (
    <Screen>
      <Header title={t("reputation-title")} icon="star" />
      {reputation.isPending && <SkeletonRows />}
      {reputation.isError && (
        <ErrorState
          message={reputation.error.message}
          onRetry={() => void reputation.refetch()}
        />
      )}
      {reputation.isSuccess && (
        <Card>
          {reputation.data.length === 0 ? (
            <EmptyState text={t("reputation-empty")} icon="star" />
          ) : (
            reputation.data.map((entry) => (
              <Row
                key={entry.tg_user_id}
                title={nameOf(entry)}
                subtitle={t("reputation-level", { level: entry.level })}
                onClick={() => setEditing(entry)}
                // The score fills `right`, which would otherwise drop the
                // automatic chevron — every row here opens the adjuster, and a
                // score is a value, never a promise that tapping does something.
                chevron
                right={<span className="text-row tabular-nums">{entry.points}</span>}
              />
            ))
          )}
        </Card>
      )}
    </Screen>
  );
}
