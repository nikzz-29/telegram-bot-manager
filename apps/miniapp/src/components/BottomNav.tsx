import React from "react";
import { useT } from "../i18n/I18nProvider";
import { type Route, useNavigation } from "../navigation";
import { useUser } from "../session";
import { pressFeedback } from "../telegram/sdk";
import { Icon } from "./Icon";

export type RootRouteName =
  | "dashboard"
  | "userStats"
  | "chats"
  | "plans"
  | "profile"
  | "platform";

interface NavItem {
  name: RootRouteName;
  icon: string;
  label: string;
}

const BASE_ITEMS: readonly NavItem[] = [
  { name: "dashboard", icon: "home", label: "nav-dashboard" },
  { name: "userStats", icon: "chart", label: "nav-stats" },
  { name: "chats", icon: "chat", label: "nav-chats" },
  { name: "plans", icon: "star", label: "nav-plans" },
  { name: "profile", icon: "user", label: "nav-profile" },
];
const PLATFORM_ITEM: NavItem = { name: "platform", icon: "globe", label: "nav-platform" };
const SUPERADMIN_ITEMS: readonly NavItem[] = [...BASE_ITEMS, PLATFORM_ITEM];
const ROOT_ROUTES = new Set<RootRouteName>(SUPERADMIN_ITEMS.map((item) => item.name));

export function isRootRoute(route: Route): route is Route & { name: RootRouteName } {
  return ROOT_ROUTES.has(route.name as RootRouteName);
}

export function BottomNav({ active }: { active: RootRouteName }): React.JSX.Element {
  const t = useT();
  const { reset } = useNavigation();
  const user = useUser();
  const items = user.is_superadmin ? SUPERADMIN_ITEMS : BASE_ITEMS;
  return (
    <nav className="tg-bottom-nav" aria-label={t("nav-label")}>
      <div className="tg-bottom-nav-grid mx-auto w-full max-w-2xl">
        {items.map((item) => {
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
