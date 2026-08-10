/**
 * The signed-in user, published to every screen below the shell.
 *
 * DECISION: this context exists because `useSession` must run exactly once.
 * Telegram's launch string is single-use, so a second `useSession()` call — say
 * in a screen that only wants to know whether the viewer is a superadmin — would
 * mount a second exchange with its own `exchanged` ref and spend a string the
 * API has already burned. The shell owns the session; everyone else reads it.
 */
import React, { createContext, useContext } from "react";
import type { AuthUser } from "./api/client";

const UserContext = createContext<AuthUser | null>(null);

export function UserProvider({
  user,
  children,
}: {
  user: AuthUser;
  children: React.ReactNode;
}): React.JSX.Element {
  return <UserContext.Provider value={user}>{children}</UserContext.Provider>;
}

export function useUser(): AuthUser {
  const user = useContext(UserContext);
  if (user === null) {
    throw new Error("useUser must be used inside <UserProvider>");
  }
  return user;
}
