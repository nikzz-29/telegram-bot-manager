import React, { useEffect, useMemo, useState } from "react";
import type { Plan, PlanMeta } from "../api/client";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Header,
  Icon,
  PickerRow,
  Row,
  Screen,
  SectionTitle,
  SkeletonRows,
} from "../components/ui";
import { useT } from "../i18n/I18nProvider";
import { useChats, useMeta } from "../hooks/queries";
import { useNavigation } from "../navigation";

const PLAN_ORDER: readonly Plan[] = ["free", "pro", "business", "white_label"];

function price(plan: PlanMeta, t: ReturnType<typeof useT>): string {
  if (plan.plan === "free") {
    return t("plans-free-price");
  }
  return t("plans-price", { stars: plan.stars, usd: plan.usd });
}

export function PlansScreen(): React.JSX.Element {
  const t = useT();
  const { push } = useNavigation();
  const meta = useMeta();
  const chats = useChats();
  const [selectedChat, setSelectedChat] = useState("");
  const [expanded, setExpanded] = useState<Plan | null>("pro");

  useEffect(() => {
    if (!selectedChat && chats.data?.[0]) {
      setSelectedChat(String(chats.data[0].id));
    }
  }, [chats.data, selectedChat]);

  const plans = useMemo(
    () =>
      [...(meta.data?.plans ?? [])].sort(
        (left, right) => PLAN_ORDER.indexOf(left.plan) - PLAN_ORDER.indexOf(right.plan),
      ),
    [meta.data?.plans],
  );

  if (meta.isPending || chats.isPending) {
    return (
      <Screen>
        <Header title={t("plans-title")} icon="star" />
        <div className="mt-3">
          <SkeletonRows count={6} />
        </div>
      </Screen>
    );
  }
  if (meta.isError || chats.isError) {
    const message = meta.error?.message ?? chats.error?.message ?? t("panel-auth-failed");
    return (
      <Screen>
        <Header title={t("plans-title")} icon="star" />
        <ErrorState
          message={message}
          onRetry={() => {
            void meta.refetch();
            void chats.refetch();
          }}
        />
      </Screen>
    );
  }

  const selectedId = selectedChat ? Number(selectedChat) : null;
  return (
    <Screen>
      <Header title={t("plans-title")} subtitle={t("plans-subtitle")} icon="star" />

      <SectionTitle>{t("plans-chat-title")}</SectionTitle>
      {chats.data.length === 0 ? (
        <Card>
          <EmptyState text={t("plans-no-chats")} icon="chat" />
        </Card>
      ) : (
        <Card>
          <PickerRow
            title={t("plans-chat-title")}
            value={selectedChat}
            options={chats.data.map((chat) => ({
              value: String(chat.id),
              label: chat.title || t("chat-untitled"),
            }))}
            unsetLabel={t("field-unset")}
            onPick={setSelectedChat}
          />
        </Card>
      )}

      <SectionTitle>{t("plans-compare")}</SectionTitle>
      <div className="space-y-2">
        {plans.map((plan) => {
          const open = expanded === plan.plan;
          const chatPlan = chats.data.find((chat) => chat.id === selectedId)?.plan;
          const current = chatPlan === plan.plan;
          return (
            <div key={plan.plan}>
              <Card>
                <Row
                  title={
                    <span className="flex min-w-0 flex-wrap items-center gap-1.5">
                      <span>{t(`plan-${plan.plan}`)}</span>
                      {current && <Badge tone="success">{t("plans-current")}</Badge>}
                    </span>
                  }
                  subtitle={
                    <>
                      <span>{t(`plan-description-${plan.plan}`)}</span>
                      <span className="mt-1 block font-medium text-text">{price(plan, t)}</span>
                    </>
                  }
                  icon={plan.plan === "free" ? "shield" : plan.plan === "pro" ? "spark" : "star"}
                  onClick={() => setExpanded(open ? null : plan.plan)}
                  right={
                    <Icon
                      name="chevron"
                      size={18}
                      className={`text-hint transition-transform duration-[--panel-motion] ${
                        open ? "rotate-90" : ""
                      }`}
                    />
                  }
                />
                {open && (
                  <div className="border-t border-separator bg-ground">
                    {(plan.features ?? []).map((feature) => (
                      <Row
                        key={feature}
                        title={t(`feature-${feature.replace(/_/g, "-")}`)}
                        right={<Icon name="check" size={18} className="text-accent" />}
                      />
                    ))}
                  </div>
                )}
              </Card>
              {open && plan.plan !== "free" && selectedId !== null && (
                <div className="mt-2">
                  <Button
                    disabled={current}
                    onClick={() => push({ name: "billing", chatId: selectedId })}
                  >
                    {current ? t("plans-current") : t("plans-choose", { plan: t(`plan-${plan.plan}`) })}
                  </Button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </Screen>
  );
}
