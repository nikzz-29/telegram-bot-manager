/**
 * Typed calls, one per API operation the panel uses.
 *
 * Components never touch `client` directly: every path and payload shape is
 * pinned here, so a contract change surfaces as a compile error in one file.
 */
import {
  type AuthUser,
  type ChatDetail,
  type ChatSummary,
  type MetaResponse,
  type ModuleConfigResponse,
  client,
  setSessionToken,
  unwrap,
} from "./client";

/** Trade the Telegram launch string for a session token. */
export async function authenticate(initData: string): Promise<{
  token: string;
  expiresIn: number;
  user: AuthUser;
}> {
  const result = await client.POST("/api/auth/telegram", {
    body: { init_data: initData },
  });
  const data = unwrap(result);
  setSessionToken(data.access_token);
  return { token: data.access_token, expiresIn: data.expires_in, user: data.user };
}

/** The caller behind the current session token. */
export async function fetchCurrentUser(): Promise<AuthUser> {
  return unwrap(await client.GET("/api/auth/me", {}));
}

/**
 * Renew a live session. Telegram's `initData` is single-use, so a panel left
 * open past the token TTL renews through this rather than re-authenticating.
 */
export async function refreshSession(): Promise<string> {
  const data = unwrap(await client.POST("/api/auth/refresh", {}));
  setSessionToken(data.access_token);
  return data.access_token;
}

/** Module catalog, plan matrix and shipped locales — the panel's static shape. */
export async function fetchMeta(): Promise<MetaResponse> {
  return unwrap(await client.GET("/api/meta", {}));
}

export async function fetchChats(): Promise<ChatSummary[]> {
  return unwrap(await client.GET("/api/chats", {}));
}

export async function fetchChat(chatId: number): Promise<ChatDetail> {
  return unwrap(
    await client.GET("/api/chats/{chat_id}", { params: { path: { chat_id: chatId } } }),
  );
}

export async function updateChat(
  chatId: number,
  patch: { language?: string; timezone?: string },
): Promise<ChatDetail> {
  return unwrap(
    await client.PATCH("/api/chats/{chat_id}", {
      params: { path: { chat_id: chatId } },
      body: patch,
    }),
  );
}

export async function fetchModules(chatId: number): Promise<ModuleConfigResponse[]> {
  return unwrap(
    await client.GET("/api/chats/{chat_id}/modules", {
      params: { path: { chat_id: chatId } },
    }),
  );
}

/**
 * Merge a partial settings update into one module.
 *
 * PATCH, not PUT: a settings screen submits the fields it renders, and a newer
 * config key this build does not know about must survive the save.
 */
export async function saveModule(
  chatId: number,
  module: string,
  update: { enabled?: boolean; config?: Record<string, unknown> },
): Promise<ModuleConfigResponse> {
  return unwrap(
    await client.PATCH("/api/chats/{chat_id}/modules/{module}", {
      params: { path: { chat_id: chatId, module } },
      body: update,
    }),
  );
}

export async function resetModule(
  chatId: number,
  module: string,
): Promise<ModuleConfigResponse> {
  return unwrap(
    await client.POST("/api/chats/{chat_id}/modules/{module}/reset", {
      params: { path: { chat_id: chatId, module } },
    }),
  );
}

/** Re-read the admin list from Telegram — how a freshly promoted admin appears. */
export async function syncAdmins(chatId: number): Promise<void> {
  unwrap(
    await client.POST("/api/chats/{chat_id}/admins/sync", {
      params: { path: { chat_id: chatId } },
    }),
  );
}
