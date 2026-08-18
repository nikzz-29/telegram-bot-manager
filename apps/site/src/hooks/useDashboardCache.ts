import { useCallback, useEffect, useRef, useState } from "react";

import { fetchDashboard, LOGOUT_EVENT } from "../api";
import type { Dashboard } from "../types";

export type DashboardFetcher = (days: number, chatId?: number) => Promise<Dashboard>;
export type DashboardChatId = number | undefined;
export const DEFAULT_PERIODS = [1, 7, 30, 90] as const;

export function dashboardCacheKey(chatId: DashboardChatId, days: number): string {
  return `${chatId === undefined ? "all" : chatId}:${days}`;
}

export type DashboardCache = {
  get: (days: number, chatId?: number) => Promise<Dashboard>;
  peek: (days: number, chatId?: number) => Dashboard | undefined;
  prefetch: (chatId?: number) => Promise<void>;
  clear: () => void;
  dispose: () => void;
};

type CacheOptions = { periods?: readonly number[]; maxConcurrent?: number };

export function createDashboardCache(fetcher: DashboardFetcher, options: CacheOptions = {}): DashboardCache {
  const periods = [...(options.periods ?? DEFAULT_PERIODS)];
  const maxConcurrent = Math.max(1, options.maxConcurrent ?? 2);
  const values = new Map<string, Dashboard>();
  const pending = new Map<string, Promise<Dashboard>>();
  let generation = 0;

  const get = (days: number, chatId?: number): Promise<Dashboard> => {
    const key = dashboardCacheKey(chatId, days);
    const cached = values.get(key);
    if (cached) return Promise.resolve(cached);
    const ongoing = pending.get(key);
    if (ongoing) return ongoing;
    const requestGeneration = generation;
    const request = fetcher(days, chatId).then((value) => {
      if (requestGeneration === generation) values.set(key, value);
      return value;
    }).finally(() => pending.delete(key));
    pending.set(key, request);
    return request;
  };

  const prefetch = async (chatId?: number): Promise<void> => {
    const queue = periods.filter((days) => !values.has(dashboardCacheKey(chatId, days)) && !pending.has(dashboardCacheKey(chatId, days)));
    let cursor = 0;
    const worker = async (): Promise<void> => {
      while (cursor < queue.length) {
        const days = queue[cursor++];
        await get(days, chatId).catch(() => undefined);
      }
    };
    await Promise.all(Array.from({ length: Math.min(maxConcurrent, queue.length) }, () => worker()));
  };

  return {
    get,
    peek: (days, chatId) => values.get(dashboardCacheKey(chatId, days)),
    prefetch,
    clear: () => { generation += 1; values.clear(); pending.clear(); },
    dispose: () => { generation += 1; values.clear(); pending.clear(); },
  };
}

export type UseDashboardCacheOptions = CacheOptions & {
  userKey: string | number | null;
  period: number;
  chatId?: number;
  fetcher?: DashboardFetcher;
};

export type UseDashboardCacheResult = {
  data: Dashboard | undefined;
  error: Error | undefined;
  isLoading: boolean;
  isRefreshing: boolean;
  retry: () => void;
  prefetch: () => Promise<void>;
  cache: DashboardCache;
};

/** Session-only dashboard data. A new authenticated user always receives a fresh cache. */
export function useDashboardCache({ userKey, period, chatId, fetcher = fetchDashboard, periods, maxConcurrent }: UseDashboardCacheOptions): UseDashboardCacheResult {
  const cacheRef = useRef<{ userKey: string | number | null; value: DashboardCache } | null>(null);
  if (!cacheRef.current || cacheRef.current.userKey !== userKey) {
    cacheRef.current?.value.dispose();
    cacheRef.current = { userKey, value: createDashboardCache(fetcher, { periods, maxConcurrent }) };
  }
  const cache = cacheRef.current.value;
  const [state, setState] = useState<{ data?: Dashboard; error?: Error; loading: boolean; refreshing: boolean }>({ loading: true, refreshing: false });
  const [retryToken, setRetryToken] = useState(0);

  useEffect(() => {
    let active = true;
    const previous = cache.peek(period, chatId);
    setState({ data: previous, loading: !previous, refreshing: Boolean(previous) });
    void cache.get(period, chatId).then((data) => {
      if (active) setState({ data, loading: false, refreshing: false });
      void cache.prefetch(chatId);
    }).catch((reason: unknown) => {
      if (active) setState({ data: previous, loading: !previous, refreshing: false, error: reason instanceof Error ? reason : new Error("Could not load dashboard") });
    });
    return () => { active = false; };
  }, [cache, chatId, period, retryToken]);

  useEffect(() => {
    const handleLogout = () => { cache.dispose(); setState({ loading: true, refreshing: false }); };
    window.addEventListener(LOGOUT_EVENT, handleLogout);
    return () => window.removeEventListener(LOGOUT_EVENT, handleLogout);
  }, [cache]);

  const retry = useCallback(() => setRetryToken((value) => value + 1), []);
  const prefetch = useCallback(() => cache.prefetch(chatId), [cache, chatId]);
  return { data: state.data, error: state.error, isLoading: state.loading, isRefreshing: state.refreshing, retry, prefetch, cache };
}
