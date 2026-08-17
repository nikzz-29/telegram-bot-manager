/**
 * The shell: session → navigation → one screen, with the native back button
 * driving the stack.
 *
 * DECISION: one effect owns the back handler for the whole app. Screens push and
 * pop through `NavigationContext`; the effect re-subscribes whenever the route
 * changes, so a handler is always attached for the current screen and never for
 * the one below it. Screens that need extra back behaviour (an editor mid-edit)
 * fold it into the same `pop` — there is exactly one exit from a screen.
 */
import React, { useEffect } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BottomNav, isRootRoute } from "./components/BottomNav";
import { LaunchScreen } from "./components/LaunchScreen";
import { Card, EmptyState, ErrorState, Screen, SkeletonRows } from "./components/ui";
import { I18nProvider, useT } from "./i18n/I18nProvider";
import { useSession } from "./hooks/useSession";
import { type Route, NavigationProvider, useNavigation } from "./navigation";
import { useUser, UserProvider } from "./session";
import { bindTheme } from "./telegram/theme";
import { setBackHandler } from "./telegram/sdk";

// Screens are route-level chunks. Telegram webviews often open on constrained
// mobile connections, so downloading screens the user may never visit makes
// the launch slower without improving the first interaction.
const BillingScreen = React.lazy(async () => {
  const module = await import("./screens/BillingScreen");
  return { default: module.BillingScreen };
});
const ChatListScreen = React.lazy(async () => {
  const module = await import("./screens/ChatListScreen");
  return { default: module.ChatListScreen };
});
const ChatScreen = React.lazy(async () => {
  const module = await import("./screens/ChatScreen");
  return { default: module.ChatScreen };
});
const DashboardScreen = React.lazy(async () => {
  const module = await import("./screens/DashboardScreen");
  return { default: module.DashboardScreen };
});
const ModuleScreen = React.lazy(async () => {
  const module = await import("./screens/ModuleScreen");
  return { default: module.ModuleScreen };
});
const PlansScreen = React.lazy(async () => {
  const module = await import("./screens/PlansScreen");
  return { default: module.PlansScreen };
});
const ProfileScreen = React.lazy(async () => {
  const module = await import("./screens/ProfileScreen");
  return { default: module.ProfileScreen };
});
const PostsScreen = React.lazy(async () => {
  const module = await import("./screens/PostsScreen");
  return { default: module.PostsScreen };
});
const ReputationScreen = React.lazy(async () => {
  const module = await import("./screens/ReputationScreen");
  return { default: module.ReputationScreen };
});
const StatsScreen = React.lazy(async () => {
  const module = await import("./screens/StatsScreen");
  return { default: module.StatsScreen };
});
const TriggersScreen = React.lazy(async () => {
  const module = await import("./screens/TriggersScreen");
  return { default: module.TriggersScreen };
});
const UserStatsScreen = React.lazy(async () => {
  const module = await import("./screens/UserStatsScreen");
  return { default: module.UserStatsScreen };
});
const PlatformScreen = React.lazy(async () => {
  const module = await import("./screens/PlatformScreen");
  return { default: module.PlatformScreen };
});

/** The query client lives for the lifetime of the panel. */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      staleTime: 15_000,
      refetchOnWindowFocus: false,
    },
  },
});

function ScreenFor({ route, isSuperadmin }: { route: Route; isSuperadmin: boolean }): React.JSX.Element {
  switch (route.name) {
    case "dashboard":
      return <DashboardScreen />;
    case "userStats":
      return <UserStatsScreen />;
    case "chats":
      return <ChatListScreen />;
    case "plans":
      return <PlansScreen />;
    case "profile":
      return <ProfileScreen />;
    case "chat":
      return <ChatScreen chatId={route.chatId} />;
    case "module":
      return <ModuleScreen chatId={route.chatId} module={route.module} />;
    case "triggers":
      return <TriggersScreen chatId={route.chatId} />;
    case "posts":
      return <PostsScreen chatId={route.chatId} />;
    case "stats":
      return <StatsScreen chatId={route.chatId} />;
    case "reputation":
      return <ReputationScreen chatId={route.chatId} />;
    case "billing":
      return <BillingScreen chatId={route.chatId} />;
    case "platform":
      return isSuperadmin ? <PlatformScreen /> : <DashboardScreen />;
  }
}

function routeKey(route: Route): string {
  return Object.values(route).join(":");
}

function Stack(): React.JSX.Element {
  const { route, atRoot, requestPop } = useNavigation();
  const user = useUser();

  useEffect(() => {
    // The one exit from every screen is Telegram's own back button. It goes
    // through `requestPop` so a screen with unsaved state can ask before the
    // gesture becomes a loss.
    return setBackHandler(atRoot ? null : requestPop);
  }, [atRoot, requestPop]);

  return (
    <div className="app-viewport">
      <div className="app-atmosphere" aria-hidden="true" />
      <div className="route-stage relative z-10" key={routeKey(route)}>
        <React.Suspense
          fallback={
            <Screen>
              <SkeletonRows count={6} />
            </Screen>
          }
        >
          <ScreenFor route={route} isSuperadmin={user.is_superadmin} />
        </React.Suspense>
      </div>
      {isRootRoute(route) && <BottomNav active={route.name} />}
    </div>
  );
}

function Shell(): React.JSX.Element {
  const t = useT();
  const session = useSession();

  if (session.status === "loading") {
    return <LaunchScreen label={t("panel-loading")} />;
  }
  if (session.status === "failed") {
    return (
      <Screen>
        <ErrorState message={session.error} />
      </Screen>
    );
  }
  if (session.status === "outside") {
    return (
      <Screen>
        <Card>
          <EmptyState text={t("panel-outside-telegram")} icon="globe" />
        </Card>
      </Screen>
    );
  }

  return (
    <UserProvider user={session.user}>
      <NavigationProvider initial={{ name: "dashboard" }}>
        <Stack />
      </NavigationProvider>
    </UserProvider>
  );
}

export function App(): React.JSX.Element {
  // `bindTheme` returns its unsubscribe, and returning it from the effect is what
  // detaches the `themeParams` subscription. Discarding it left the listener
  // attached across a remount — harmless while this component owns the app's
  // whole lifetime, and a leak the moment it does not.
  useEffect(() => bindTheme(), []);

  return (
    <I18nProvider>
      <QueryClientProvider client={queryClient}>
        <Shell />
      </QueryClientProvider>
    </I18nProvider>
  );
}
