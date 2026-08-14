import React from "react";
import { useT } from "../i18n/I18nProvider";
import { type Route, useNavigation } from "../navigation";
import { pressFeedback } from "../telegram/sdk";
import { Icon } from "./Icon";

export type RootRouteName = "dashboard" | "userStats" | "chats" | "plans" | "profile";

const ITEMS: ReadonlyArray<{
  name: RootRouteName;
  icon: string;
  label: string;
}> = [
  { name: "dashboard", icon: "home", label: "nav-dashboard" },
  { name: "userStats", icon: "chart", label: "nav-stats" },
  { name: "chats", icon: "chat", label: "nav-chats" },
  { name: "plans", icon: "star", label: "nav-plans" },
  { name: "profile", icon: "user", label: "nav-profile" },
];

export function isRootRoute(route: Route): route is Route & { name: RootRouteName } {
  return ITEMS.some((item) => item.name === route.name);
}

export function BottomNav({ active }: { active: RootRouteName }): React.JSX.Element {
  const t = useT();
  const { reset } = useNavigation();
  return (
    <nav className="tg-bottom-nav" aria-label={t("nav-label")}>
      <div className="mx-auto grid w-full max-w-2xl grid-cols-5">
        {ITEMS.map((item) => {
          const selected = item.name === active;
          return (
            <button
              key={item.name}
              type="button"
              aria-current={selected ? "page" : undefined}
              className={`tg-bottom-nav-item ${selected ? "text-accent" : "text-hint"}`}
              onClick={() => {
                pressFeedback();
                reset({ name: item.name });
              }}
            >
              <span className={`tg-bottom-nav-icon ${selected ? "bg-accent-tint" : ""}`}>
                <Icon name={item.icon} size={20} />
              </span>
              <span>{t(item.label)}</span>
            </button>
          );
        })}
      </div>
    </nav>
  );
}
