/**
 * The session: trade Telegram's launch string for a token, and keep it alive.
 *
 * DECISION: `initData` is exchanged exactly once, on mount, and the session is
 * kept going with `/auth/refresh` afterwards. Telegram's launch string is
 * single-use against replay protection on the API side — a panel that
 * re-authenticated on every 401 would be rejected the second time and log the
 * user out for good.
 *
 * DECISION: the refresh timer is set from the token's own `expires_in` rather
 * than a constant here. The TTL is the API's decision, and duplicating it in the
 * client is how a panel ends up refreshing after the token already died.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { type AuthUser, setSessionLostHandler, setSessionToken } from "../api/client";
import { authenticate, refreshSession } from "../api/operations";
import { initTelegram, launchInitData } from "../telegram/sdk";

/** Renew this long before expiry, so a slow network still lands in time. */
const REFRESH_MARGIN_SECONDS = 60;

export type SessionState =
  | { status: "loading" }
  | { status: "ready"; user: AuthUser }
  | { status: "outside" }
  | { status: "failed"; error: string };

export function useSession(): SessionState {
  const [state, setState] = useState<SessionState>({ status: "loading" });
  const timer = useRef<number | null>(null);
  // Guards React 18's double-mount in StrictMode: `initData` is single-use, so
  // exchanging it twice would spend the launch string on a discarded render.
  const exchanged = useRef(false);

  const scheduleRefresh = useCallback((expiresIn: number) => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
    }
    const delay = Math.max(30, expiresIn - REFRESH_MARGIN_SECONDS) * 1000;
    timer.current = window.setTimeout(() => {
      void refreshSession()
        .then(() => scheduleRefresh(expiresIn))
        .catch(() => setState({ status: "failed", error: "panel-auth-failed" }));
    }, delay);
  }, []);

  useEffect(() => {
    if (exchanged.current) {
      return;
    }
    exchanged.current = true;

    initTelegram();
    const initData = launchInitData();
    if (!initData) {
      // A plain browser, or a client that sent nothing we can verify.
      setState({ status: "outside" });
      return;
    }

    void authenticate(initData)
      .then(({ user, expiresIn }) => {
        setState({ status: "ready", user });
        scheduleRefresh(expiresIn);
      })
      .catch(() => setState({ status: "failed", error: "panel-auth-failed" }));
  }, [scheduleRefresh]);

  useEffect(() => {
    // The API rejected a token we thought was live — it outlived its TTL while
    // the tab was backgrounded, or the server restarted with a new secret.
    setSessionLostHandler(() => {
      void refreshSession().catch(() =>
        setState({ status: "failed", error: "panel-auth-failed" }),
      );
    });
    return () => {
      setSessionLostHandler(null);
      if (timer.current !== null) {
        window.clearTimeout(timer.current);
      }
      setSessionToken(null);
    };
  }, []);

  return state;
}
