import type { AuthResponse, Chat, Dashboard, Meta, Profile } from "./types";

const TOKEN_KEY = "tg-manager-site-session";
let token = sessionStorage.getItem(TOKEN_KEY);

export const LOGOUT_EVENT = "tg-manager:logout";
export function clearToken(): void {
  token = null;
  sessionStorage.removeItem(TOKEN_KEY);
  if (typeof window !== "undefined") window.dispatchEvent(new Event(LOGOUT_EVENT));
}
export function setToken(value: string): void { token = value; sessionStorage.setItem(TOKEN_KEY, value); }
export function hasToken(): boolean { return Boolean(token); }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(path, { ...init, cache: "no-store", headers });
  if (!response.ok) {
    if (response.status === 401) clearToken();
    let message = response.statusText;
    try { const problem = await response.json() as { title?: string }; message = problem.title ?? message; } catch { /* plain response */ }
    throw new Error(message || "Request failed");
  }
  return response.json() as Promise<T>;
}

export async function login(tokenValue: string): Promise<AuthResponse> {
  const result = await request<AuthResponse>("/api/auth/website", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: tokenValue }),
  });
  setToken(result.access_token);
  return result;
}
export const fetchProfile = (): Promise<Profile> => request("/api/me/profile");
export const fetchChats = (): Promise<Chat[]> => request("/api/chats");
export const fetchDashboard = (days: number, chatId?: number): Promise<Dashboard> => {
  const params = new URLSearchParams({ days: String(days) });
  if (chatId !== undefined) params.set("chat_id", String(chatId));
  return request(`/api/me/dashboard?${params.toString()}`);
};
export const fetchMeta = (): Promise<Meta> => request("/api/meta");
