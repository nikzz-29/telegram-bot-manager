/**
 * The plan: what this chat has, what the others cost, and how to pay.
 *
 * DECISION: paying does not optimistically move the plan. Both providers settle
 * out-of-band — Stars through Telegram's own sheet, CryptoBot through a webhook
 * that may land seconds later — so the screen refetches and shows whatever the
 * server says. A panel that promised "Pro" before the webhook arrived would be
 * lying about the one thing the user just paid for.
 */
import React, { useState } from "react";
import type { PaymentEntry, Plan, PlanOption } from "../api/client";
import {
  Badge,
  Card,
  EmptyState,
  ErrorState,
  Header,
  Icon,
  Row,
  Screen,
  SectionTitle,
  SegmentedControl,
  SkeletonRows,
} from "../components/ui";
import { useI18n, useT } from "../i18n/I18nProvider";
import { useCreateInvoice, usePayments, usePlans } from "../hooks/queries";
import { hapticResult, openExternal, openInvoice } from "../telegram/sdk";

const TERMS: readonly number[] = [1, 3, 12];

/**
 * How loudly each payment state is said.
 *
 * DECISION: `refunded` is neutral, not destructive. Nothing went wrong — the
 * money came back — and colouring it the same red as a declined card would make
 * a settled account look like an unpaid one.
 */
const STATUS_TONE: Record<
  PaymentEntry["status"],
  "neutral" | "success" | "warning" | "destructive"
> = {
  paid: "success",
  pending: "warning",
  failed: "destructive",
  refunded: "neutral",
};

function formatDate(value: string, locale: string): string {
  return new Date(value).toLocaleDateString(locale, { dateStyle: "medium" });
}

/** The current plan and when it lapses, in one line. */
function CurrentPlan({
  plan,
  expiresAt,
}: {
  plan: Plan;
  expiresAt: string | null | undefined;
}): React.JSX.Element {
  const { t, locale } = useI18n();
  const lapsed = expiresAt != null && new Date(expiresAt).getTime() < Date.now();
  const expiry = (): string => {
    if (expiresAt == null) {
      return t("billing-lifetime");
    }
    const key = lapsed ? "billing-expired" : "billing-expires";
    return t(key, { date: formatDate(expiresAt, locale) });
  };
  /*
   * DECISION: `free` is neutral rather than green. Every chat is on it by
   * default and it never lapses, so a success badge would congratulate the user
   * for not having bought anything — and would make the one row that should
   * read as an upsell look like a settled subscription.
   */
  const tone = lapsed ? "destructive" : plan === "free" ? "neutral" : "success";
  return (
    <Card className="mt-3">
      <Row
        title={t("billing-current")}
        subtitle={expiry()}
        right={<Badge tone={tone}>{t(`plan-${plan}`)}</Badge>}
      />
    </Card>
  );
}

function PlanCard({
  option,
  months,
  disabled,
  onPay,
}: {
  option: PlanOption;
  months: number;
  disabled: boolean;
  onPay: (provider: "stars" | "cryptobot") => void;
}): React.JSX.Element {
  const t = useT();
  return (
    <>
      <SectionTitle>{t(`plan-${option.plan}`)}</SectionTitle>
      <Card>
        {option.features.map((feature) => (
          <Row
            key={feature}
            title={t(`feature-${feature.replace(/_/g, "-")}`)}
            // A trailing tick rather than a leading tile: a plan's feature list
            // runs to a dozen rows, and a dozen filled squares down the left
            // edge outweighs the words they are marking.
            right={<Icon name="check" size={18} className="text-accent" />}
          />
        ))}
      </Card>
      {/*
        DECISION: the two ways to pay are rows in their own card, not stacked
        buttons. A button pair reads as one primary choice and one fallback,
        which is the wrong shape — Stars and crypto are the same purchase
        through different tills, and as rows each carries its own price and its
        own affordance instead of competing for emphasis.
      */}
      <Card className="mt-2">
        <Row
          title={t("billing-pay-stars", { amount: option.stars * months })}
          icon="star"
          disabled={disabled}
          onClick={() => onPay("stars")}
        />
        <Row
          title={t("billing-pay-crypto", { amount: (Number(option.usd) * months).toFixed(2) })}
          // A globe, because this one leaves Telegram for an external checkout.
          icon="globe"
          disabled={disabled}
          onClick={() => onPay("cryptobot")}
        />
      </Card>
    </>
  );
}

function History({ payments }: { payments: readonly PaymentEntry[] }): React.JSX.Element {
  const { t, locale } = useI18n();
  return (
    <>
      <SectionTitle>{t("billing-history")}</SectionTitle>
      <Card>
        {payments.length === 0 ? (
          <EmptyState text={t("billing-history-empty")} icon="clock" />
        ) : (
          payments.map((payment) => (
            <Row
              key={payment.id}
              title={`${t(`plan-${payment.plan}`)} · ${t("billing-months", { count: payment.months })}`}
              subtitle={formatDate(payment.created_at, locale)}
              right={
                <div className="flex items-center gap-2">
                  <span className="text-label tabular-nums text-hint">
                    {payment.amount} {payment.currency}
                  </span>
                  <Badge tone={STATUS_TONE[payment.status]}>
                    {t(`billing-status-${payment.status}`)}
                  </Badge>
                </div>
              }
            />
          ))
        )}
      </Card>
    </>
  );
}
export function BillingScreen({ chatId }: { chatId: number }): React.JSX.Element {
  const t = useT();
  const plans = usePlans(chatId);
  const payments = usePayments(chatId);
  const invoice = useCreateInvoice(chatId);
  const [months, setMonths] = useState(1);
  const [notice, setNotice] = useState<string | null>(null);

  const pay = (plan: Plan, provider: "stars" | "cryptobot"): void => {
    setNotice(t("billing-invoice-opening"));
    invoice.mutate(
      { plan, provider, months },
      {
        onError: () => {
          setNotice(null);
          hapticResult(false);
        },
        onSuccess: async (response) => {
          const url = response.invoice_url;
          if (url == null) {
            // The API accepted the order and returned no link. Nothing was
            // charged, but saying nothing here reads as "the tap did nothing" —
            // and the next thing a user does about that is tap again.
            setNotice(t("billing-invoice-failed"));
            hapticResult(false);
            return;
          }
          if (provider === "cryptobot") {
            // An external checkout: we cannot observe it, so refetch on return.
            if (!openExternal(url)) {
              // No link opener in this client, so no sheet is coming.
              setNotice(t("billing-invoice-unsupported"));
              hapticResult(false);
              return;
            }
            setNotice(null);
            await plans.refetch();
            await payments.refetch();
            return;
          }
          const outcome = await openInvoice(url);
          hapticResult(outcome === "paid");
          setNotice(
            outcome === "paid"
              ? t("billing-invoice-paid")
              : outcome === "cancelled"
                ? t("billing-invoice-cancelled")
                : outcome === "unsupported"
                  ? t("billing-invoice-unsupported")
                  : t("billing-invoice-failed"),
          );
          // Even a cancelled sheet is worth a refetch — the webhook for a
          // previous attempt may have landed while it was open.
          await plans.refetch();
          await payments.refetch();
        },
      },
    );
  };

  if (plans.isPending) {
    return (
      <Screen>
        <Header title={t("billing-title")} icon="star" />
        <div className="mt-3">
          <SkeletonRows count={4} />
        </div>
      </Screen>
    );
  }
  if (plans.isError) {
    return (
      <Screen>
        <Header title={t("billing-title")} icon="star" />
        <ErrorState message={plans.error.message} onRetry={() => void plans.refetch()} />
      </Screen>
    );
  }

  const upgrades = plans.data.options.filter(
    (option) => option.plan !== plans.data.current_plan,
  );

  return (
    <Screen>
      <Header title={t("billing-title")} icon="star" />
      <CurrentPlan plan={plans.data.current_plan} expiresAt={plans.data.expires_at} />

      {notice != null && <p className="mt-3 text-center text-label text-hint">{notice}</p>}
      {invoice.isError && (
        <p className="mt-3 text-center text-label text-destructive">
          {invoice.error.message}
        </p>
      )}

      <SectionTitle>{t("billing-choose-term")}</SectionTitle>
      <SegmentedControl
        value={months}
        onChange={setMonths}
        disabled={invoice.isPending}
        options={TERMS.map((term) => ({
          value: term,
          label: t("billing-months", { count: term }),
        }))}
      />

      {upgrades.map((option) => (
        <PlanCard
          key={option.plan}
          option={option}
          months={months}
          disabled={invoice.isPending}
          onPay={(provider) => pay(option.plan, provider)}
        />
      ))}

      {/*
       * The history says what has already been charged, so it has to account for
       * itself. Rendered only on success, a failed fetch left a hole where the
       * section belongs — indistinguishable from a chat that has never paid, and
       * the one reading it is deciding whether to pay again.
       */}
      {payments.isPending && <SkeletonRows count={3} />}
      {payments.isError && (
        <>
          <SectionTitle>{t("billing-history")}</SectionTitle>
          <Card>
            <ErrorState
              message={payments.error.message}
              onRetry={() => void payments.refetch()}
            />
          </Card>
        </>
      )}
      {payments.isSuccess && <History payments={payments.data} />}
    </Screen>
  );
}
