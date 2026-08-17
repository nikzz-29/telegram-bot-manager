export type User = {
  tg_user_id: number;
  username: string | null;
  first_name: string;
  last_name: string | null;
  language_code: string;
  is_superadmin: boolean;
  is_premium: boolean;
  has_photo: boolean;
  photo_url: string | null;
};

export type Profile = {
  user: User;
  display_name: string;
  first_seen_at: string | null;
  chats_total: number;
  chats_owned: number;
  chats_admin: number;
  paid_chats: number;
  total_members: number;
};

export type Chat = {
  id: number;
  tg_chat_id: number;
  title: string;
  type: string;
  plan: string;
  plan_expires_at: string | null;
  is_active: boolean;
  role: string;
  members_count: number | null;
};

export type Point = { date: string; messages: number; active_users: number; joins: number; leaves: number; moderation_actions: number };
export type Dashboard = {
  period_days: number;
  analytics_available: boolean;
  totals: { messages: number; active_users: number; joins: number; leaves: number; net_growth: number; moderation_actions: number };
  previous: { messages: number; active_users: number; joins: number; leaves: number; net_growth: number; moderation_actions: number };
  deltas_percent: Record<string, number | null>;
  series: Point[];
  moderation: { total: number; warns: number; restrictions: number; mine: number; automated: number; moderators: number; breakdown: { action: string; count: number }[] };
  chats: Chat[];
};

export type Meta = { plans: { plan: string; stars: number; usd: string; features: string[]; limits: Record<string, number> }[] };
export type AuthResponse = { access_token: string; expires_in: number; user: User };
