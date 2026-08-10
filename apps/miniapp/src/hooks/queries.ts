/**
 * Every server read and write the panel makes, as React Query hooks.
 *
 * DECISION: mutations invalidate by chat rather than patching the cache by hand.
 * A settings save can change more than the field that was edited — turning a
 * module on can flip `available` elsewhere, and paying moves the whole plan — so
 * refetching the chat's slice is both simpler and harder to get subtly wrong.
 */
import {
  type UseMutationResult,
  type UseQueryResult,
  useMutation,
  useQueryClient,
  useQuery,
} from "@tanstack/react-query";
import type {
  BroadcastRequest,
  ChatDetail,
  ChatSummary,
  GlobalBanCreate,
  GlobalBanEntry,
  InvoiceRequest,
  InvoiceResponse,
  MetaResponse,
  ModuleConfigResponse,
  OperationResult,
  PaymentEntry,
  PlanCatalog,
  PlatformStats,
  PostCreate,
  PostEntry,
  PostUpdate,
  ReputationEntry,
  StatsOverview,
  TriggerCreate,
  TriggerEntry,
  TriggerUpdate,
} from "../api/client";
import * as api from "../api/operations";

/** One place to spell the keys, so an invalidation cannot miss a query. */
export const keys = {
  meta: ["meta"] as const,
  chats: ["chats"] as const,
  chat: (id: number) => ["chat", id] as const,
  modules: (id: number) => ["chat", id, "modules"] as const,
  triggers: (id: number) => ["chat", id, "triggers"] as const,
  posts: (id: number) => ["chat", id, "posts"] as const,
  stats: (id: number, days: number) => ["chat", id, "stats", days] as const,
  reputation: (id: number) => ["chat", id, "reputation"] as const,
  plans: (id: number) => ["chat", id, "plans"] as const,
  payments: (id: number) => ["chat", id, "payments"] as const,
  platformStats: ["platform", "stats"] as const,
  platformBans: ["platform", "bans"] as const,
};

/** The catalog changes on deploy, not during a session. */
export function useMeta(): UseQueryResult<MetaResponse> {
  return useQuery({ queryKey: keys.meta, queryFn: api.fetchMeta, staleTime: Infinity });
}

export function useChats(): UseQueryResult<ChatSummary[]> {
  return useQuery({ queryKey: keys.chats, queryFn: api.fetchChats });
}

export function useChat(chatId: number): UseQueryResult<ChatDetail> {
  return useQuery({ queryKey: keys.chat(chatId), queryFn: () => api.fetchChat(chatId) });
}

export function useModules(chatId: number): UseQueryResult<ModuleConfigResponse[]> {
  return useQuery({
    queryKey: keys.modules(chatId),
    queryFn: () => api.fetchModules(chatId),
  });
}

export function useTriggers(chatId: number): UseQueryResult<TriggerEntry[]> {
  return useQuery({
    queryKey: keys.triggers(chatId),
    queryFn: () => api.fetchTriggers(chatId),
  });
}

export function usePosts(chatId: number): UseQueryResult<PostEntry[]> {
  return useQuery({ queryKey: keys.posts(chatId), queryFn: () => api.fetchPosts(chatId) });
}

export function useStats(chatId: number, days: number): UseQueryResult<StatsOverview> {
  return useQuery({
    queryKey: keys.stats(chatId, days),
    queryFn: () => api.fetchStats(chatId, days),
  });
}

export function useReputation(chatId: number): UseQueryResult<ReputationEntry[]> {
  return useQuery({
    queryKey: keys.reputation(chatId),
    queryFn: () => api.fetchReputation(chatId, { limit: 50 }),
  });
}

export function usePlans(chatId: number): UseQueryResult<PlanCatalog> {
  return useQuery({ queryKey: keys.plans(chatId), queryFn: () => api.fetchPlans(chatId) });
}

export function usePayments(chatId: number): UseQueryResult<PaymentEntry[]> {
  return useQuery({
    queryKey: keys.payments(chatId),
    queryFn: () => api.fetchPayments(chatId),
  });
}

export function usePlatformStats(): UseQueryResult<PlatformStats> {
  return useQuery({ queryKey: keys.platformStats, queryFn: api.fetchPlatformStats });
}

export function useGlobalBans(): UseQueryResult<GlobalBanEntry[]> {
  return useQuery({
    queryKey: keys.platformBans,
    queryFn: () => api.fetchGlobalBans({ activeOnly: true, limit: 100 }),
  });
}

/** Invalidate everything scoped to one chat — see the note at the top. */
function useChatInvalidator(chatId: number): () => Promise<void> {
  const queryClient = useQueryClient();
  return async () => {
    await queryClient.invalidateQueries({ queryKey: ["chat", chatId] });
  };
}

export function useSaveModule(
  chatId: number,
): UseMutationResult<
  ModuleConfigResponse,
  Error,
  { module: string; enabled?: boolean; config?: Record<string, unknown> }
> {
  const invalidate = useChatInvalidator(chatId);
  return useMutation({
    mutationFn: ({ module, ...update }) => api.saveModule(chatId, module, update),
    onSuccess: invalidate,
  });
}

export function useResetModule(
  chatId: number,
): UseMutationResult<ModuleConfigResponse, Error, string> {
  const invalidate = useChatInvalidator(chatId);
  return useMutation({
    mutationFn: (module: string) => api.resetModule(chatId, module),
    onSuccess: invalidate,
  });
}

export function useUpdateChat(
  chatId: number,
): UseMutationResult<ChatDetail, Error, { language?: string; timezone?: string }> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (patch) => api.updateChat(chatId, patch),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["chat", chatId] });
      // The list shows the title and plan too, and both can move here.
      await queryClient.invalidateQueries({ queryKey: keys.chats });
    },
  });
}

export function useSyncAdmins(chatId: number): UseMutationResult<void, Error, void> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.syncAdmins(chatId),
    onSuccess: async () => {
      // A sync can revoke *our* access, so the chat list is part of the answer.
      await queryClient.invalidateQueries({ queryKey: keys.chats });
    },
  });
}

export function useCreateTrigger(
  chatId: number,
): UseMutationResult<TriggerEntry, Error, TriggerCreate> {
  const invalidate = useChatInvalidator(chatId);
  return useMutation({
    mutationFn: (body) => api.createTrigger(chatId, body),
    onSuccess: invalidate,
  });
}

export function useUpdateTrigger(
  chatId: number,
): UseMutationResult<TriggerEntry, Error, { id: number; body: TriggerUpdate }> {
  const invalidate = useChatInvalidator(chatId);
  return useMutation({
    mutationFn: ({ id, body }) => api.updateTrigger(chatId, id, body),
    onSuccess: invalidate,
  });
}

export function useDeleteTrigger(chatId: number): UseMutationResult<void, Error, number> {
  const invalidate = useChatInvalidator(chatId);
  return useMutation({
    mutationFn: (id) => api.deleteTrigger(chatId, id),
    onSuccess: invalidate,
  });
}

export function useCreatePost(
  chatId: number,
): UseMutationResult<PostEntry, Error, PostCreate> {
  const invalidate = useChatInvalidator(chatId);
  return useMutation({
    mutationFn: (body) => api.createPost(chatId, body),
    onSuccess: invalidate,
  });
}

export function useUpdatePost(
  chatId: number,
): UseMutationResult<PostEntry, Error, { id: number; body: PostUpdate }> {
  const invalidate = useChatInvalidator(chatId);
  return useMutation({
    mutationFn: ({ id, body }) => api.updatePost(chatId, id, body),
    onSuccess: invalidate,
  });
}

export function useDeletePost(chatId: number): UseMutationResult<void, Error, number> {
  const invalidate = useChatInvalidator(chatId);
  return useMutation({
    mutationFn: (id) => api.deletePost(chatId, id),
    onSuccess: invalidate,
  });
}

export function useAdjustReputation(
  chatId: number,
): UseMutationResult<ReputationEntry, Error, { tgUserId: number; delta: number }> {
  const invalidate = useChatInvalidator(chatId);
  return useMutation({
    mutationFn: ({ tgUserId, delta }) => api.adjustReputation(chatId, tgUserId, delta),
    onSuccess: invalidate,
  });
}

export function useCreateInvoice(
  chatId: number,
): UseMutationResult<InvoiceResponse, Error, InvoiceRequest> {
  return useMutation({ mutationFn: (body) => api.createInvoice(chatId, body) });
}

export function useCreateGlobalBan(): UseMutationResult<
  GlobalBanEntry,
  Error,
  GlobalBanCreate
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.createGlobalBan,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["platform"] });
    },
  });
}

export function useRevokeGlobalBan(): UseMutationResult<OperationResult, Error, number> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.revokeGlobalBan,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["platform"] });
    },
  });
}

export function useBroadcast(): UseMutationResult<
  OperationResult,
  Error,
  BroadcastRequest
> {
  return useMutation({ mutationFn: api.sendBroadcast });
}
