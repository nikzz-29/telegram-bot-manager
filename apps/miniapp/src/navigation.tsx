/**
 * Navigation, as a stack rather than a URL.
 *
 * DECISION: no router library and no history entries. A Mini App is a webview
 * without an address bar — there is nothing to bookmark, nothing to share, and
 * the user's only "back" is Telegram's own button. A three-field stack in state
 * matches that exactly, and wiring the native back button to `pop` gives the
 * Android hardware gesture the behaviour people expect for free.
 */
import React, { createContext, useCallback, useContext, useMemo, useState } from "react";

export type Route =
  | { name: "chats" }
  | { name: "chat"; chatId: number }
  | { name: "module"; chatId: number; module: string }
  | { name: "triggers"; chatId: number }
  | { name: "posts"; chatId: number }
  | { name: "stats"; chatId: number }
  | { name: "reputation"; chatId: number }
  | { name: "billing"; chatId: number }
  | { name: "platform" };

export interface Navigation {
  route: Route;
  /** True at the root, where the back button must be hidden rather than shown. */
  atRoot: boolean;
  push: (route: Route) => void;
  pop: () => void;
  reset: (route: Route) => void;
}

const NavigationContext = createContext<Navigation | null>(null);

export function NavigationProvider({
  initial,
  children,
}: {
  initial: Route;
  children: React.ReactNode;
}): React.JSX.Element {
  const [stack, setStack] = useState<Route[]>([initial]);

  const push = useCallback((route: Route) => {
    setStack((current) => [...current, route]);
    // A pushed screen starts at its own top, not wherever the previous one was
    // scrolled to — the webview keeps one scroll position for the whole app.
    window.scrollTo(0, 0);
  }, []);

  const pop = useCallback(() => {
    setStack((current) => (current.length > 1 ? current.slice(0, -1) : current));
  }, []);

  const reset = useCallback((route: Route) => {
    setStack([route]);
    window.scrollTo(0, 0);
  }, []);

  const value = useMemo<Navigation>(
    () => ({
      route: stack[stack.length - 1] as Route,
      atRoot: stack.length === 1,
      push,
      pop,
      reset,
    }),
    [stack, push, pop, reset],
  );

  return (
    <NavigationContext.Provider value={value}>{children}</NavigationContext.Provider>
  );
}

export function useNavigation(): Navigation {
  const value = useContext(NavigationContext);
  if (value === null) {
    throw new Error("useNavigation must be used inside <NavigationProvider>");
  }
  return value;
}
