/**
 * Navigation, as a stack rather than a URL.
 *
 * DECISION: no router library and no history entries. A Mini App is a webview
 * without an address bar — there is nothing to bookmark, nothing to share, and
 * the user's only "back" is Telegram's own button. A three-field stack in state
 * matches that exactly, and wiring the native back button to `pop` gives the
 * Android hardware gesture the behaviour people expect for free.
 */
import React, {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

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
  /**
   * Go back: what Telegram's back button calls.
   *
   * Screens holding unsaved state take this over with `useBackIntercept`; with no
   * interceptor registered it is just `pop`.
   */
  requestPop: () => void;
  /** See `useBackIntercept`. Returns the unregister function. */
  registerBackIntercept: (intercept: BackIntercept) => () => void;
}

/**
 * Called instead of popping the stack.
 *
 * Returns true to let the pop proceed, false when the screen handled the gesture
 * itself — an editor rendered inside its list screen closes back to the list,
 * which is one level shallower than leaving the route.
 *
 * Async because the answer may be a native popup, which is a round trip through
 * the Telegram client.
 */
export type BackIntercept = () => boolean | Promise<boolean>;

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

  /*
   * DECISION: the interceptor lives in a ref, not in state. It is read when the
   * user taps back and never rendered, so holding it in state would re-render the
   * whole stack every time an editor's dirty flag flips — and the interceptor
   * closes over that flag, so its identity changes on every keystroke.
   */
  const intercept = useRef<BackIntercept | null>(null);

  const registerBackIntercept = useCallback((next: BackIntercept) => {
    intercept.current = next;
    return () => {
      // Only if it is still ours: an editor unmounting after its replacement
      // registered would otherwise clear an interceptor it does not own.
      if (intercept.current === next) {
        intercept.current = null;
      }
    };
  }, []);

  const requestPop = useCallback(() => {
    const ask = intercept.current;
    if (ask === null) {
      pop();
      return;
    }
    void (async () => {
      if (await ask()) {
        pop();
      }
    })();
  }, [pop]);

  const value = useMemo<Navigation>(
    () => ({
      route: stack[stack.length - 1] as Route,
      atRoot: stack.length === 1,
      push,
      pop,
      reset,
      requestPop,
      registerBackIntercept,
    }),
    [stack, push, pop, reset, requestPop, registerBackIntercept],
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

/**
 * Take over the back button for the lifetime of the current screen.
 *
 * Used by editors: while the screen's back button is active, this component is
 * its only exit, so the interceptor is also the natural place to close a local
 * editor back to the list — see `BackIntercept`.
 *
 * One interceptor at a time: the last to register wins. Only one screen renders
 * per route and the editors replace their list rather than sitting over it, so
 * two live at once is not a state this app can reach.
 *
 * Pass `null` when the screen has nothing to protect — a list with no open
 * editor — rather than calling the hook conditionally.
 */
export function useBackIntercept(intercept: BackIntercept | null): void {
  const { registerBackIntercept } = useNavigation();
  useEffect(() => {
    if (intercept === null) {
      return undefined;
    }
    return registerBackIntercept(intercept);
  }, [intercept, registerBackIntercept]);
}
