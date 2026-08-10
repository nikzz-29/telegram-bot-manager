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
  Button,
  Card,
  EmptyState,
  ErrorState,
  Row,
  Screen,
  SectionTitle,
  Spinner,
} from "../components/ui";
import { useI18n, useT } from "../i18n/I18nProvider";
import { useCreateInvoice, usePayments, usePlans } from "../hooks/queries";
import { hapticResult, openExternal, openInvoice } from "../telegram/sdk";

const TERMS: readonly number[] = [1, 3, 12];

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
  const expiry = (): string => {
    if (expiresAt == null) {
      return t("billing-lifetime");
    }
    const at = new Date(expiresAt);
    const key = at.getTime() < Date.now() ? "billing-expired" : "billing-expires";
    return t(key, { date: formatDate(expiresAt, locale) });
  };
  return (
    <Card>
      <Row title={t("billing-current")} right={<span>{t(`plan-${plan}`)}</span>} />
      <Row title={expiry()} />
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
          <Row key={feature} title={t(`feature-${feature.replace(/_/g, "-")}`)} />
        ))}
      </Card>
      <div className="mt-3 space-y-2">
        <Button disabled={disabled} onClick={() => onPay("stars")}>
          {t("billing-pay-stars", { amount: option.stars * months })}
        </Button>
        <Button variant="secondary" disabled={disabled} onClick={() => onPay("cryptobot")}>
          {t("billing-pay-crypto", { amount: (Number(option.usd) * months).toFixed(2) })}
        </Button>
      </div>
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
          <EmptyState text={t("billing-history-empty")} />
        ) : (
          payments.map((payment) => (
            <Row
              key={payment.id}
              title={`${t(`plan-${payment.plan}`)} · ${t("billing-months", { count: payment.months })}`}
              subtitle={formatDate(payment.created_at, locale)}
              right={
                <span className="text-[13px] text-hint">
                  {payment.amount} {payment.currency} · {t(`billing-status-${payment.status}`)}
                </span>
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
            setNotice(null);
            return;
          }
          if (provider === "cryptobot") {
            // An external checkout: we cannot observe it, so refetch on return.
            openExternal(url);
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
                : null,
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
        <Spinner />
      </Screen>
    );
  }
  if (plans.isError) {
    return (
      <Screen>
        <ErrorState message={plans.error.message} onRetry={() => void plans.refetch()} />
      </Screen>
    );
  }

  const upgrades = plans.data.options.filter(
    (option) => option.plan !== plans.data.current_plan,
  );

  return (
    <Screen>
      <SectionTitle>{t("billing-title")}</SectionTitle>
      <CurrentPlan plan={plans.data.current_plan} expiresAt={plans.data.expires_at} />

      {notice != null && <p className="mt-3 text-center text-[13px] text-hint">{notice}</p>}
      {invoice.isError && (
        <p className="mt-3 text-center text-[13px] text-destructive">
          {invoice.error.message}
        </p>
      )}

      <SectionTitle>{t("billing-choose-term")}</SectionTitle>
      <div className="flex gap-2">
        {TERMS.map((term) => (
          <button
            key={term}
            type="button"
            onClick={() => setMonths(term)}
            className={`flex-1 rounded-lg px-3 py-2 text-[14px] ${
              term === months ? "bg-accent text-accent-text" : "bg-surface text-link"
            }`}
          >
            {t("billing-months", { count: term })}
          </button>
        ))}
      </div>

      {upgrades.map((option) => (
        <PlanCard
          key={option.plan}
          option={option}
          months={months}
          disabled={invoice.isPending}
          onPay={(provider) => pay(option.plan, provider)}
        />
      ))}

      {payments.isSuccess && <History payments={payments.data} />}
    </Screen>
  );
}
