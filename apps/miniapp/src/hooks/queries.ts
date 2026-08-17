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
  ChatBotPermissions,
  ChatSummary,
  GlobalBanCreate,
  GlobalBanEntry,
  InvoiceRequest,
  InvoiceResponse,
  MetaResponse,
  ModuleConfigResponse,
  OperationResult,
  PaymentEntry,
  PaymentProvider,
  PaymentStatus,
  PlanCatalog,
  Plan,
  PlatformDashboard,
  PlatformPaymentPage,
  PlatformPlanOverride,
  PlatformPlanOverrideResponse,
  PlatformSettings,
  PlatformStats,
  PlatformSubscriptionGrant,
  PlatformUserDetail,
  PlatformUserPage,
  PostCreate,
  PostEntry,
  PostUpdate,
  ReputationEntry,
  StatsOverview,
  TriggerCreate,
  TriggerEntry,
  TriggerUpdate,
  UserDashboard,
  UserProfile,
} from "../api/client";
import * as api from "../api/operations";

/** One place to spell the keys, so an invalidation cannot miss a query. */
export const keys = {
  meta: ["meta"] as const,
  profile: ["me", "profile"] as const,
  dashboard: (days: number, chatId?: number) =>
    ["me", "dashboard", days, chatId ?? "all"] as const,
  chats: ["chats"] as const,
  chat: (id: number) => ["chat", id] as const,
  botPermissions: (id: number) => ["chat", id, "bot-permissions"] as const,
  modules: (id: number) => ["chat", id, "modules"] as const,
  triggers: (id: number) => ["chat", id, "triggers"] as const,
  posts: (id: number) => ["chat", id, "posts"] as const,
  stats: (id: number, days: number) => ["chat", id, "stats", days] as const,
  reputation: (id: number) => ["chat", id, "reputation"] as const,
  plans: (id: number) => ["chat", id, "plans"] as const,
  payments: (id: number) => ["chat", id, "payments"] as const,
  platformStats: ["platform", "stats"] as const,
  platformDashboard: (days: number) => ["platform", "dashboard", days] as const,
  platformUsers: (search: string, bannedOnly: boolean, adminsOnly: boolean, offset: number) =>
    ["platform", "users", search, bannedOnly, adminsOnly, offset] as const,
  platformUser: (id: number) => ["platform", "user", id] as const,
  platformPayments: (status: string, provider: string, offset: number) =>
    ["platform", "payments", status, provider, offset] as const,
  platformSettings: ["platform", "settings"] as const,
  platformPlans: ["platform", "plans"] as const,
  platformBans: ["platform", "bans"] as const,
};

/** The catalog changes on deploy, not during a session. */
export function useMeta(): UseQueryResult<MetaResponse> {
  return useQuery({ queryKey: keys.meta, queryFn: api.fetchMeta, staleTime: Infinity });
}

export function useUserProfile(): UseQueryResult<UserProfile> {
  return useQuery({ queryKey: keys.profile, queryFn: api.fetchUserProfile });
}

export function useUserDashboard(
  days: 1 | 7 | 30 | 90,
  chatId?: number,
): UseQueryResult<UserDashboard> {
  return useQuery({
    queryKey: keys.dashboard(days, chatId),
    queryFn: () => api.fetchUserDashboard(days, chatId),
  });
}

export function useChats(): UseQueryResult<ChatSummary[]> {
  return useQuery({ queryKey: keys.chats, queryFn: api.fetchChats });
}

export function useChat(chatId: number): UseQueryResult<ChatDetail> {
  return useQuery({ queryKey: keys.chat(chatId), queryFn: () => api.fetchChat(chatId) });
}

export function useChatBotPermissions(
  chatId: number,
): UseQueryResult<ChatBotPermissions> {
  return useQuery({
    queryKey: keys.botPermissions(chatId),
    queryFn: () => api.fetchChatBotPermissions(chatId),
    staleTime: 30_000,
  });
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

export function usePlatformDashboard(days: number): UseQueryResult<PlatformDashboard> {
  return useQuery({
    queryKey: keys.platformDashboard(days),
    queryFn: () => api.fetchPlatformDashboard(days),
  });
}

export function usePlatformUsers(options: {
  search: string;
  bannedOnly: boolean;
  adminsOnly: boolean;
  offset: number;
}): UseQueryResult<PlatformUserPage> {
  return useQuery({
    queryKey: keys.platformUsers(
      options.search,
      options.bannedOnly,
      options.adminsOnly,
      options.offset,
    ),
    queryFn: () => api.fetchPlatformUsers({ ...options, limit: 40 }),
  });
}

export function usePlatformUser(
  tgUserId: number | null,
): UseQueryResult<PlatformUserDetail> {
  return useQuery({
    queryKey: keys.platformUser(tgUserId ?? 0),
    queryFn: () => api.fetchPlatformUser(tgUserId!),
    enabled: tgUserId !== null,
  });
}

export function usePlatformPayments(options: {
  status?: PaymentStatus;
  provider?: PaymentProvider;
  offset: number;
}): UseQueryResult<PlatformPaymentPage> {
  return useQuery({
    queryKey: keys.platformPayments(options.status ?? "all", options.provider ?? "all", options.offset),
    queryFn: () => api.fetchPlatformPayments({ ...options, limit: 50 }),
  });
}

export function usePlatformSettings(): UseQueryResult<PlatformSettings> {
  return useQuery({ queryKey: keys.platformSettings, queryFn: api.fetchPlatformSettings });
}

export function usePlatformPlans(): UseQueryResult<PlatformPlanOverrideResponse[]> {
  return useQuery({ queryKey: keys.platformPlans, queryFn: api.fetchPlatformPlans });
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

export function useGrantPlatformSubscription(): UseMutationResult<
  OperationResult,
  Error,
  { tgUserId: number; body: PlatformSubscriptionGrant }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ tgUserId, body }) => api.grantPlatformSubscription(tgUserId, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["platform"] });
      await queryClient.invalidateQueries({ queryKey: keys.chats });
    },
  });
}

export function useUpdateCryptoBotSettings(): UseMutationResult<
  PlatformSettings,
  Error,
  boolean
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (testnet) => api.updateCryptoBotSettings({ testnet }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.platformSettings });
      await queryClient.invalidateQueries({ queryKey: ["platform", "dashboard"] });
      await queryClient.invalidateQueries({ queryKey: keys.meta });
    },
  });
}

export function useUpdatePlatformPlan(): UseMutationResult<
  PlatformPlanOverrideResponse,
  Error,
  { plan: Plan; body: PlatformPlanOverride }
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ plan, body }) => api.updatePlatformPlan(plan, body),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.platformPlans });
      await queryClient.invalidateQueries({ queryKey: keys.meta });
    },
  });
}

export function useResetPlatformPlan(): UseMutationResult<
  PlatformPlanOverrideResponse,
  Error,
  Plan
> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.resetPlatformPlan,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: keys.platformPlans });
      await queryClient.invalidateQueries({ queryKey: keys.meta });
    },
  });
}
