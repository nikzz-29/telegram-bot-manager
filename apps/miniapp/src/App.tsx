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
import { Card, EmptyState, ErrorState, Screen, SkeletonRows } from "./components/ui";
import { I18nProvider, useT } from "./i18n/I18nProvider";
import { useSession } from "./hooks/useSession";
import { type Route, NavigationProvider, useNavigation } from "./navigation";
import { BillingScreen } from "./screens/BillingScreen";
import { ChatListScreen } from "./screens/ChatListScreen";
import { ChatScreen } from "./screens/ChatScreen";
import { ModuleScreen } from "./screens/ModuleScreen";
import { PlatformScreen } from "./screens/PlatformScreen";
import { PostsScreen } from "./screens/PostsScreen";
import { ReputationScreen } from "./screens/ReputationScreen";
import { StatsScreen } from "./screens/StatsScreen";
import { TriggersScreen } from "./screens/TriggersScreen";
import { UserProvider } from "./session";
import { bindTheme } from "./telegram/theme";
import { setBackHandler } from "./telegram/sdk";

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

function ScreenFor({ route }: { route: Route }): React.JSX.Element {
  switch (route.name) {
    case "chats":
      return <ChatListScreen />;
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
      return <PlatformScreen />;
  }
}

function Stack(): React.JSX.Element {
  const { route, atRoot, pop } = useNavigation();

  useEffect(() => {
    // The one exit from every screen is Telegram's own back button.
    return setBackHandler(atRoot ? null : pop);
  }, [atRoot, pop]);

  return <ScreenFor route={route} />;
}

function Shell(): React.JSX.Element {
  const t = useT();
  const session = useSession();

  if (session.status === "loading") {
    // Skeleton rows rather than a spinner: what is loading is the chat list, and
    // this is the panel's first paint — the shape of what is coming is a better
    // first impression than a shrug, and the page does not jump when it lands.
    return (
      <Screen>
        <SkeletonRows count={4} />
      </Screen>
    );
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
      <NavigationProvider initial={{ name: "chats" }}>
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
