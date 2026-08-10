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
  type PostCreate,
  type PostEntry,
  type PostUpdate,
  type ReputationEntry,
  type StatsOverview,
  type TriggerCreate,
  type TriggerEntry,
  type TriggerUpdate,
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

// --- triggers --------------------------------------------------------------
export async function fetchTriggers(chatId: number): Promise<TriggerEntry[]> {
  return unwrap(
    await client.GET("/api/chats/{chat_id}/triggers", {
      params: { path: { chat_id: chatId } },
    }),
  );
}

export async function createTrigger(
  chatId: number,
  body: TriggerCreate,
): Promise<TriggerEntry> {
  return unwrap(
    await client.POST("/api/chats/{chat_id}/triggers", {
      params: { path: { chat_id: chatId } },
      body,
    }),
  );
}

export async function updateTrigger(
  chatId: number,
  triggerId: number,
  body: TriggerUpdate,
): Promise<TriggerEntry> {
  return unwrap(
    await client.PATCH("/api/chats/{chat_id}/triggers/{trigger_id}", {
      params: { path: { chat_id: chatId, trigger_id: triggerId } },
      body,
    }),
  );
}

export async function deleteTrigger(chatId: number, triggerId: number): Promise<void> {
  unwrap(
    await client.DELETE("/api/chats/{chat_id}/triggers/{trigger_id}", {
      params: { path: { chat_id: chatId, trigger_id: triggerId } },
    }),
  );
}

// --- scheduled posts -------------------------------------------------------
export async function fetchPosts(chatId: number): Promise<PostEntry[]> {
  return unwrap(
    await client.GET("/api/chats/{chat_id}/posts", {
      params: { path: { chat_id: chatId } },
    }),
  );
}

export async function createPost(chatId: number, body: PostCreate): Promise<PostEntry> {
  return unwrap(
    await client.POST("/api/chats/{chat_id}/posts", {
      params: { path: { chat_id: chatId } },
      body,
    }),
  );
}

export async function updatePost(
  chatId: number,
  postId: number,
  body: PostUpdate,
): Promise<PostEntry> {
  return unwrap(
    await client.PATCH("/api/chats/{chat_id}/posts/{post_id}", {
      params: { path: { chat_id: chatId, post_id: postId } },
      body,
    }),
  );
}

export async function deletePost(chatId: number, postId: number): Promise<void> {
  unwrap(
    await client.DELETE("/api/chats/{chat_id}/posts/{post_id}", {
      params: { path: { chat_id: chatId, post_id: postId } },
    }),
  );
}

// --- statistics and reputation ---------------------------------------------
/** `days` is a request, not a promise: the API clamps it to the plan's retention. */
export async function fetchStats(chatId: number, days = 7): Promise<StatsOverview> {
  return unwrap(
    await client.GET("/api/chats/{chat_id}/stats", {
      params: { path: { chat_id: chatId }, query: { days } },
    }),
  );
}

export async function fetchReputation(
  chatId: number,
  options: { limit?: number; orderBy?: string } = {},
): Promise<ReputationEntry[]> {
  return unwrap(
    await client.GET("/api/chats/{chat_id}/reputation", {
      params: {
        path: { chat_id: chatId },
        query: { limit: options.limit, order_by: options.orderBy },
      },
    }),
  );
}

/** A signed delta, never an absolute score — see the API's own note on why. */
export async function adjustReputation(
  chatId: number,
  tgUserId: number,
  delta: number,
): Promise<ReputationEntry> {
  return unwrap(
    await client.POST("/api/chats/{chat_id}/reputation/{tg_user_id}/adjust", {
      params: { path: { chat_id: chatId, tg_user_id: tgUserId } },
      body: { delta },
    }),
  );
}
