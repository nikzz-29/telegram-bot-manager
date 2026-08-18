import { describe, expect, it, vi } from "vitest";

import { createDashboardCache, dashboardCacheKey, type DashboardFetcher } from "./useDashboardCache";
import type { Dashboard } from "../types";

const dashboard = (days: number, chatId?: number): Dashboard => ({
  period_days: days,
  selected_chat_id: chatId ?? null,
  analytics_available: true,
  scoped_chat_count: 1,
  analytics_chat_count: 1,
  totals: { messages: days, active_users: days, joins: 0, leaves: 0, net_growth: 0, moderation_actions: 0 },
  previous: { messages: 0, active_users: 0, joins: 0, leaves: 0, net_growth: 0, moderation_actions: 0 },
  deltas_percent: {},
  series: [],
  moderation: { total: 0, warns: 0, restrictions: 0, mine: 0, automated: 0, moderators: 0, breakdown: [] },
  top_users: [],
  chats: [],
});

describe("dashboard cache", () => {
  it("keeps aggregate and chat keys isolated", () => {
    expect(dashboardCacheKey(undefined, 7)).toBe("all:7");
    expect(dashboardCacheKey(42, 7)).toBe("42:7");
    expect(dashboardCacheKey(42, 30)).not.toBe(dashboardCacheKey(42, 7));
  });

  it("deduplicates concurrent reads and reuses a cached result", async () => {
    let release!: (value: Dashboard) => void;
    const pending = new Promise<Dashboard>((resolve) => { release = resolve; });
    const fetcher = vi.fn<DashboardFetcher>(() => pending);
    const cache = createDashboardCache(fetcher, { periods: [7] });

    const first = cache.get(7);
    const second = cache.get(7);
    expect(fetcher).toHaveBeenCalledTimes(1);
    release(dashboard(7));
    await expect(first).resolves.toMatchObject({ period_days: 7 });
    await expect(second).resolves.toMatchObject({ period_days: 7 });
    await expect(cache.get(7)).resolves.toMatchObject({ period_days: 7 });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("prefetches missing periods with bounded concurrency", async () => {
    const active: number[] = [];
    let peak = 0;
    const fetcher = vi.fn<DashboardFetcher>(async (days) => {
      active.push(days);
      peak = Math.max(peak, active.length);
      await Promise.resolve();
      active.splice(active.indexOf(days), 1);
      return dashboard(days);
    });
    const cache = createDashboardCache(fetcher, { periods: [1, 7, 30, 90], maxConcurrent: 2 });
    await cache.get(7);
    await cache.prefetch();
    expect(peak).toBeLessThanOrEqual(2);
    expect(fetcher).toHaveBeenCalledTimes(4);
    expect(cache.peek(30)?.period_days).toBe(30);
  });

  it("recovers after a per-key error and clears all memory on dispose", async () => {
    const fetcher = vi.fn<DashboardFetcher>()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce(dashboard(7));
    const cache = createDashboardCache(fetcher, { periods: [7] });
    await expect(cache.get(7)).rejects.toThrow("offline");
    await expect(cache.get(7)).resolves.toMatchObject({ period_days: 7 });
    cache.dispose();
    expect(cache.peek(7)).toBeUndefined();
  });
});
