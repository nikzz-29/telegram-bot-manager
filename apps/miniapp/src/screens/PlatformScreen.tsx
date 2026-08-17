import React, { useDeferredValue, useMemo, useState } from "react";
import type {
  GlobalBanEntry,
  PaymentProvider,
  PaymentStatus,
  Plan,
  PlatformPlanOverrideResponse,
  PlatformUser,
} from "../api/client";
import { PlatformChart, type PlatformMetric } from "../components/PlatformChart";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Header,
  Icon,
  Row,
  Screen,
  SectionTitle,
  SkeletonRows,
  Toggle,
} from "../components/ui";
import {
  useBroadcast,
  useCreateGlobalBan,
  useGlobalBans,
  useGrantPlatformSubscription,
  useMeta,
  usePlatformDashboard,
  usePlatformPayments,
  usePlatformPlans,
  usePlatformSettings,
  usePlatformUser,
  usePlatformUsers,
  useResetPlatformPlan,
  useRevokeGlobalBan,
  useUpdateCryptoBotSettings,
  useUpdatePlatformPlan,
} from "../hooks/queries";
import { useI18n } from "../i18n/I18nProvider";
import { askConfirmation, hapticResult, pressFeedback } from "../telegram/sdk";

const PLANS: readonly Plan[] = ["free", "pro", "business", "white_label"];
const PERIODS = [1, 7, 30, 90, 365] as const;
const METRICS: readonly PlatformMetric[] = [
  "messages",
  "new_chats",
  "active_chats",
  "moderation_actions",
  "subscriptions",
  "revenue_stars",
];

type Tab = "overview" | "users" | "bans" | "payments" | "plans" | "system" | "broadcast";

const COPY = {
  ru: {
    title: "Командный центр",
    subtitle: "Управление платформой в реальном времени",
    overview: "Обзор",
    users: "Люди",
    bans: "Баны",
    payments: "Платежи",
    plans: "Тарифы",
    system: "Система",
    broadcast: "Рассылка",
    period: "Период наблюдения",
    noData: "За этот период данных пока нет",
    messages: "Сообщения",
    new_chats: "Новые чаты",
    active_chats: "Активные чаты",
    moderation_actions: "Модерация",
    subscriptions: "Подписки",
    revenue_stars: "Выручка Stars",
    knownUsers: "Пользователи",
    totalChats: "Всего чатов",
    payingChats: "Платные чаты",
    refunds: "Возвраты",
    revenueUsd: "Выручка USD",
    planMix: "Состав платформы",
    infrastructure: "Контуры платформы",
    enabled: "Работает",
    unavailable: "Не настроено",
    testnet: "Тестовая сеть",
    mainnet: "Основная сеть",
    searchUsers: "Имя, username или Telegram ID",
    onlyAdmins: "Только администраторы",
    onlyBanned: "Только заблокированные",
    found: "Найдено",
    noUsers: "Пользователи с такими условиями не найдены",
    chats: "Чаты",
    owner: "Владелец",
    admin: "Администратор",
    spent: "Потрачено",
    lastSeen: "Последняя активность",
    openProfile: "Открыть карточку",
    close: "Закрыть",
    userCard: "Карточка пользователя",
    userUnknown: "Пользователь без имени",
    grant: "Выдать подписку",
    grantHint: "Тариф применяется к выбранному чату сразу после подтверждения.",
    months: "Месяцев",
    chat: "Чат",
    chooseChat: "Выберите чат",
    banUser: "Заблокировать глобально",
    unbanUser: "Разблокировать",
    banReason: "Причина глобального бана",
    banReasonDefault: "Ручная блокировка супер-администратором",
    active: "Активен",
    inactive: "Отключён",
    expires: "до",
    blacklist: "Глобальный чёрный список",
    blacklistEmpty: "Глобальных блокировок нет",
    addBan: "Добавить блокировку",
    telegramId: "Telegram ID",
    reason: "Причина",
    paymentJournal: "Журнал операций",
    all: "Все",
    stars: "Stars",
    cryptobot: "CryptoBot",
    paid: "Оплачено",
    pending: "Ожидает",
    failed: "Ошибка",
    refunded: "Возвращено",
    noPayments: "Платежей с такими условиями нет",
    payer: "Плательщик",
    transaction: "Транзакция",
    featureMatrix: "Цены и возможности",
    editPlan: "Редактирование тарифа",
    priceStars: "Цена в Stars",
    priceUsd: "Цена в USD",
    features: "Доступные возможности",
    note: "Внутренняя заметка",
    savePlan: "Сохранить тариф",
    resetPlan: "Вернуть заводские значения",
    override: "Переопределён",
    standard: "Стандартный",
    deployment: "Состояние развёртывания",
    environment: "Окружение",
    ai: "ИИ-модерация",
    providers: "Платёжные провайдеры",
    crossbanThreshold: "Порог кросс-бана",
    cryptoTitle: "CryptoBot Testnet",
    cryptoHint: "Переключает сеть новых CryptoBot-счетов. Незавершённые счета остаются в своей исходной сети.",
    cryptoMissing: "Сначала задайте CRYPTOBOT_TOKEN на сервере.",
    broadcastTitle: "Сообщение всем чатам",
    broadcastHint: "Рассылка попадёт в очередь с низким приоритетом и не задержит модерацию.",
    message: "Текст сообщения",
    recipients: "Получатели по тарифам",
    send: "Поставить рассылку в очередь",
    sent: "Чатов в очереди",
    loading: "Загружаем данные…",
    previous: "Назад",
    next: "Дальше",
    of: "из",
  },
  en: {
    title: "Command center",
    subtitle: "Live platform operations",
    overview: "Overview",
    users: "People",
    bans: "Bans",
    payments: "Payments",
    plans: "Plans",
    system: "System",
    broadcast: "Broadcast",
    period: "Observation window",
    noData: "No data in this period yet",
    messages: "Messages",
    new_chats: "New chats",
    active_chats: "Active chats",
    moderation_actions: "Moderation",
    subscriptions: "Subscriptions",
    revenue_stars: "Stars revenue",
    knownUsers: "Known users",
    totalChats: "Total chats",
    payingChats: "Paying chats",
    refunds: "Refunds",
    revenueUsd: "USD revenue",
    planMix: "Platform mix",
    infrastructure: "Platform circuits",
    enabled: "Online",
    unavailable: "Not configured",
    testnet: "Test network",
    mainnet: "Main network",
    searchUsers: "Name, username or Telegram ID",
    onlyAdmins: "Admins only",
    onlyBanned: "Banned only",
    found: "Found",
    noUsers: "No users match these filters",
    chats: "Chats",
    owner: "Owner",
    admin: "Administrator",
    spent: "Spent",
    lastSeen: "Last active",
    openProfile: "Open profile",
    close: "Close",
    userCard: "User profile",
    userUnknown: "Unnamed user",
    grant: "Grant subscription",
    grantHint: "The selected plan is applied to the chat immediately after confirmation.",
    months: "Months",
    chat: "Chat",
    chooseChat: "Choose a chat",
    banUser: "Ban globally",
    unbanUser: "Lift global ban",
    banReason: "Global ban reason",
    banReasonDefault: "Manual superadmin ban",
    active: "Active",
    inactive: "Inactive",
    expires: "until",
    blacklist: "Global blacklist",
    blacklistEmpty: "There are no global bans",
    addBan: "Add global ban",
    telegramId: "Telegram ID",
    reason: "Reason",
    paymentJournal: "Operation journal",
    all: "All",
    stars: "Stars",
    cryptobot: "CryptoBot",
    paid: "Paid",
    pending: "Pending",
    failed: "Failed",
    refunded: "Refunded",
    noPayments: "No payments match these filters",
    payer: "Payer",
    transaction: "Transaction",
    featureMatrix: "Prices and capabilities",
    editPlan: "Edit plan",
    priceStars: "Price in Stars",
    priceUsd: "Price in USD",
    features: "Available capabilities",
    note: "Internal note",
    savePlan: "Save plan",
    resetPlan: "Restore shipped values",
    override: "Overridden",
    standard: "Shipped",
    deployment: "Deployment state",
    environment: "Environment",
    ai: "AI moderation",
    providers: "Payment providers",
    crossbanThreshold: "Cross-ban threshold",
    cryptoTitle: "CryptoBot Testnet",
    cryptoHint: "Changes the network used for new CryptoBot invoices. Existing invoices stay on their original network.",
    cryptoMissing: "Configure CRYPTOBOT_TOKEN on the server first.",
    broadcastTitle: "Message every chat",
    broadcastHint: "Broadcasts use a low-priority queue and never delay moderation work.",
    message: "Message text",
    recipients: "Recipients by plan",
    send: "Queue broadcast",
    sent: "Chats queued",
    loading: "Loading data…",
    previous: "Previous",
    next: "Next",
    of: "of",
  },
} as const;

const FEATURE_RU: Record<string, string> = {
  moderation: "Модерация",
  captcha: "Капча",
  greeting: "Приветствия",
  stop_words: "Стоп-слова",
  anti_flood: "Антифлуд",
  log_channel: "Канал логов",
  anti_raid: "Антирейд",
  stats: "Статистика",
  triggers: "Триггеры",
  autopost: "Автопостинг",
  reputation: "Репутация",
  levels: "Уровни",
  forced_subscription: "Обязательная подписка",
  ai_moderation: "ИИ-модерация",
  crossban: "Кросс-бан",
  chat_networks: "Сети чатов",
  priority_support: "Приоритетная поддержка",
  white_label: "White label",
};

function number(value: number | string, locale: string): string {
  return Number(value || 0).toLocaleString(locale, { maximumFractionDigits: 2 });
}

function date(value: string | null | undefined, locale: string): string {
  if (!value) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime())
    ? value
    : parsed.toLocaleDateString(locale, { day: "2-digit", month: "short", year: "numeric" });
}

function userName(user: PlatformUser, fallback: string): string {
  const full = [user.first_name, user.last_name].filter(Boolean).join(" ").trim();
  return full || (user.username ? `@${user.username}` : fallback);
}

function planName(plan: Plan): string {
  return plan === "white_label" ? "White Label" : plan[0]!.toUpperCase() + plan.slice(1);
}

function Chip({
  active,
  children,
  onClick,
}: {
  active: boolean;
  children: React.ReactNode;
  onClick: () => void;
}): React.JSX.Element {
  return (
    <button
      type="button"
      aria-pressed={active}
      className={`platform-chip ${active ? "platform-chip-active" : ""}`}
      onClick={() => {
        pressFeedback();
        onClick();
      }}
    >
      {children}
    </button>
  );
}

function Tabs({ value, onChange }: { value: Tab; onChange: (tab: Tab) => void }): React.JSX.Element {
  const { locale } = useI18n();
  const c = COPY[locale];
  const tabs: Array<{ value: Tab; label: string; icon: string }> = [
    { value: "overview", label: c.overview, icon: "chart" },
    { value: "users", label: c.users, icon: "user" },
    { value: "bans", label: c.bans, icon: "shield" },
    { value: "payments", label: c.payments, icon: "star" },
    { value: "plans", label: c.plans, icon: "sparkles" },
    { value: "system", label: c.system, icon: "settings" },
    { value: "broadcast", label: c.broadcast, icon: "chat" },
  ];
  return (
    <nav className="platform-tabs" aria-label={c.title}>
      {tabs.map((tab) => (
        <button
          key={tab.value}
          type="button"
          aria-current={value === tab.value ? "page" : undefined}
          className="platform-tab"
          onClick={() => {
            pressFeedback();
            onChange(tab.value);
          }}
        >
          <Icon name={tab.icon} size={17} />
          <span>{tab.label}</span>
        </button>
      ))}
    </nav>
  );
}

function Overview(): React.JSX.Element {
  const { locale } = useI18n();
  const c = COPY[locale];
  const [days, setDays] = useState<(typeof PERIODS)[number]>(30);
  const [metric, setMetric] = useState<PlatformMetric>("messages");
  const dashboard = usePlatformDashboard(days);

  return (
    <>
      <SectionTitle>{c.period}</SectionTitle>
      <div className="platform-chip-rail">
        {PERIODS.map((period) => (
          <Chip key={period} active={days === period} onClick={() => setDays(period)}>
            {period === 365 ? "1Y" : `${period}D`}
          </Chip>
        ))}
      </div>
      {dashboard.isPending ? <div className="mt-3"><SkeletonRows count={5} /></div> : null}
      {dashboard.isError ? (
        <ErrorState message={dashboard.error.message} onRetry={() => void dashboard.refetch()} />
      ) : null}
      {dashboard.isSuccess ? (
        <>
          <div className="platform-kpi-grid mt-3">
            {[
              [c.knownUsers, dashboard.data.totals.known_users, "user"],
              [c.totalChats, dashboard.data.totals.chats, "chat"],
              [c.payingChats, dashboard.data.totals.paying_chats, "star"],
              [c.messages, dashboard.data.totals.messages, "chart"],
              [c.revenue_stars, dashboard.data.totals.revenue_stars, "sparkles"],
              [c.revenueUsd, `$${number(dashboard.data.totals.revenue_usd, locale)}`, "globe"],
            ].map(([label, value, icon]) => (
              <article className="platform-kpi" key={String(label)}>
                <span className="platform-kpi-icon"><Icon name={String(icon)} size={17} /></span>
                <strong>{typeof value === "number" ? number(value, locale) : value}</strong>
                <span>{label}</span>
              </article>
            ))}
          </div>

          <SectionTitle>{c[metric]}</SectionTitle>
          <Card className="platform-analytics-card">
            <div className="platform-metric-rail">
              {METRICS.map((item) => (
                <Chip key={item} active={metric === item} onClick={() => setMetric(item)}>
                  {c[item]}
                </Chip>
              ))}
            </div>
            <PlatformChart
              series={dashboard.data.series ?? []}
              metric={metric}
              locale={locale}
              emptyLabel={c.noData}
              ariaLabel={c[metric]}
            />
          </Card>

          <SectionTitle>{c.planMix}</SectionTitle>
          <Card className="px-4 py-2">
            {(dashboard.data.plan_mix ?? []).map((row) => {
              const share = dashboard.data.totals.chats
                ? Math.round((row.chats / dashboard.data.totals.chats) * 100)
                : 0;
              return (
                <div className="platform-plan-row" key={row.plan}>
                  <div className="flex items-center justify-between gap-3">
                    <strong>{planName(row.plan)}</strong>
                    <span>{number(row.chats, locale)} · {share}%</span>
                  </div>
                  <div className="platform-plan-track"><i style={{ width: `${share}%` }} /></div>
                  <small>{number(row.active_chats, locale)} {c.active_chats.toLowerCase()} · {number(row.subscriptions, locale)} {c.subscriptions.toLowerCase()}</small>
                </div>
              );
            })}
          </Card>

          <SectionTitle>{c.infrastructure}</SectionTitle>
          <div className="grid grid-cols-2 gap-2">
            <Card className="platform-circuit">
              <Icon name="star" size={20} />
              <strong>CryptoBot</strong>
              <Badge tone={dashboard.data.cryptobot_configured ? (dashboard.data.cryptobot_testnet ? "warning" : "success") : "destructive"}>
                {dashboard.data.cryptobot_configured ? (dashboard.data.cryptobot_testnet ? c.testnet : c.mainnet) : c.unavailable}
              </Badge>
            </Card>
            <Card className="platform-circuit">
              <Icon name="sparkles" size={20} />
              <strong>{c.ai}</strong>
              <Badge tone={dashboard.data.ai_moderation_available ? "success" : "warning"}>
                {dashboard.data.ai_moderation_available ? c.enabled : c.unavailable}
              </Badge>
            </Card>
          </div>
        </>
      ) : null}
    </>
  );
}

function Pager({ offset, limit, total, onChange }: { offset: number; limit: number; total: number; onChange: (value: number) => void }): React.JSX.Element | null {
  const { locale } = useI18n();
  const c = COPY[locale];
  if (total <= limit) return null;
  return (
    <div className="platform-pager">
      <button type="button" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>{c.previous}</button>
      <span>{Math.floor(offset / limit) + 1} {c.of} {Math.ceil(total / limit)}</span>
      <button type="button" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>{c.next}</button>
    </div>
  );
}

function UserDrawer({ id, onClose }: { id: number; onClose: () => void }): React.JSX.Element {
  const { locale } = useI18n();
  const c = COPY[locale];
  const detail = usePlatformUser(id);
  const grant = useGrantPlatformSubscription();
  const createBan = useCreateGlobalBan();
  const revokeBan = useRevokeGlobalBan();
  const [chatId, setChatId] = useState(0);
  const [plan, setPlan] = useState<Plan>("pro");
  const [months, setMonths] = useState(1);
  const [reason, setReason] = useState<string>(c.banReasonDefault);

  return (
    <div className="platform-drawer-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="platform-drawer" role="dialog" aria-modal="true" aria-label={c.userCard}>
        <div className="platform-drawer-head">
          <div><small>{c.userCard}</small><strong>{detail.data ? userName(detail.data.user, c.userUnknown) : c.loading}</strong></div>
          <button type="button" onClick={onClose} aria-label={c.close}><Icon name="plus" size={22} /></button>
        </div>
        <div className="platform-drawer-scroll">
          {detail.isPending ? <SkeletonRows count={5} /> : null}
          {detail.isError ? <ErrorState message={detail.error.message} onRetry={() => void detail.refetch()} /> : null}
          {detail.data ? (
            <>
              <Card>
                <Row title={`ID ${detail.data.user.tg_user_id}`} subtitle={detail.data.user.username ? `@${detail.data.user.username}` : undefined} icon="user" />
                <Row title={c.chats} right={<strong>{detail.data.user.admin_chats}</strong>} />
                <Row title={c.spent} right={<span>⭐ {number(detail.data.user.spent_stars, locale)} · ${number(detail.data.user.spent_usd, locale)}</span>} />
                <Row title={c.lastSeen} right={<span className="text-label text-hint">{date(detail.data.user.last_seen_at, locale)}</span>} />
              </Card>
              <SectionTitle>{c.chats}</SectionTitle>
              <Card>
                {(detail.data.chats ?? []).length === 0 ? <EmptyState text={c.noData} icon="chat" /> : (detail.data.chats ?? []).map((chat) => (
                  <button key={chat.id} type="button" className={`platform-user-chat ${chatId === chat.id ? "platform-user-chat-active" : ""}`} onClick={() => { pressFeedback(); setChatId(chat.id); }}>
                    <span><strong>{chat.title}</strong><small>{chat.owner_tg_id === id ? c.owner : c.admin} · {chat.is_active ? c.active : c.inactive}</small></span>
                    <span><Badge tone={chat.plan === "free" ? "neutral" : "accent"}>{planName(chat.plan)}</Badge><small>{chat.plan_expires_at ? `${c.expires} ${date(chat.plan_expires_at, locale)}` : "∞"}</small></span>
                  </button>
                ))}
              </Card>
              <SectionTitle>{c.grant}</SectionTitle>
              <Card className="p-4">
                <p className="mb-3 text-label text-hint">{c.grantHint}</p>
                <label className="platform-field"><span>{c.chat}</span><select className="tg-input" value={chatId} onChange={(event) => setChatId(Number(event.target.value))}><option value={0}>{c.chooseChat}</option>{(detail.data.chats ?? []).map((chat) => <option key={chat.id} value={chat.id}>{chat.title}</option>)}</select></label>
                <div className="mt-3 grid grid-cols-2 gap-2">
                  <label className="platform-field"><span>{c.plans}</span><select className="tg-input" value={plan} onChange={(event) => setPlan(event.target.value as Plan)}>{PLANS.map((item) => <option key={item} value={item}>{planName(item)}</option>)}</select></label>
                  <label className="platform-field"><span>{c.months}</span><input className="tg-input" type="number" min={1} max={120} value={months} onChange={(event) => setMonths(Math.max(1, Number(event.target.value)))} /></label>
                </div>
                <div className="mt-3"><Button disabled={!chatId || grant.isPending} onClick={() => grant.mutate({ tgUserId: id, body: { chat_id: chatId, plan, months } }, { onSuccess: () => { hapticResult(true); void detail.refetch(); }, onError: () => hapticResult(false) })}>{c.grant}</Button></div>
                {grant.isError ? <p className="platform-error">{grant.error.message}</p> : null}
              </Card>
              <SectionTitle>{c.bans}</SectionTitle>
              {detail.data.user.is_globally_banned ? (
                <Button variant="secondary" disabled={revokeBan.isPending} onClick={() => revokeBan.mutate(id, { onSuccess: () => { hapticResult(true); void detail.refetch(); }, onError: () => hapticResult(false) })}>{c.unbanUser}</Button>
              ) : (
                <Card className="p-4">
                  <label className="platform-field"><span>{c.banReason}</span><input className="tg-input" value={reason} maxLength={512} onChange={(event) => setReason(event.target.value)} /></label>
                  <div className="mt-3"><Button variant="destructive" disabled={!reason.trim() || createBan.isPending} onClick={() => createBan.mutate({ tg_user_id: id, reason }, { onSuccess: () => { hapticResult(true); void detail.refetch(); }, onError: () => hapticResult(false) })}>{c.banUser}</Button></div>
                </Card>
              )}
            </>
          ) : null}
        </div>
      </section>
    </div>
  );
}

function Users(): React.JSX.Element {
  const { locale } = useI18n();
  const c = COPY[locale];
  const [search, setSearch] = useState("");
  const deferredSearch = useDeferredValue(search.trim());
  const [bannedOnly, setBannedOnly] = useState(false);
  const [adminsOnly, setAdminsOnly] = useState(false);
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const users = usePlatformUsers({ search: deferredSearch, bannedOnly, adminsOnly, offset });

  return (
    <>
      <SectionTitle>{c.users}</SectionTitle>
      <Card className="platform-search-card">
        <Icon name="user" size={19} />
        <input value={search} onChange={(event) => { setSearch(event.target.value); setOffset(0); }} placeholder={c.searchUsers} aria-label={c.searchUsers} />
      </Card>
      <div className="platform-chip-rail mt-2">
        <Chip active={adminsOnly} onClick={() => { setAdminsOnly((value) => !value); setOffset(0); }}>{c.onlyAdmins}</Chip>
        <Chip active={bannedOnly} onClick={() => { setBannedOnly((value) => !value); setOffset(0); }}>{c.onlyBanned}</Chip>
      </div>
      {users.isPending ? <div className="mt-3"><SkeletonRows count={7} /></div> : null}
      {users.isError ? <ErrorState message={users.error.message} onRetry={() => void users.refetch()} /> : null}
      {users.data ? (
        <>
          <div className="platform-list-summary"><span>{c.found}</span><strong>{number(users.data.total, locale)}</strong></div>
          <Card>
            {(users.data.items ?? []).length === 0 ? <EmptyState text={c.noUsers} icon="user" /> : (users.data.items ?? []).map((user) => (
              <Row key={user.tg_user_id} title={userName(user, c.userUnknown)} subtitle={`${user.username ? `@${user.username} · ` : ""}ID ${user.tg_user_id} · ${user.admin_chats} ${c.chats.toLowerCase()}`} icon="user" iconTone={user.is_globally_banned ? "destructive" : "accent"} right={<div className="flex items-center gap-2">{user.is_globally_banned ? <Badge tone="destructive">{c.bans}</Badge> : null}<Icon name="chevron" size={18} className="text-hint" /></div>} onClick={() => setSelected(user.tg_user_id)} />
            ))}
          </Card>
          <Pager offset={users.data.offset} limit={users.data.limit} total={users.data.total} onChange={setOffset} />
        </>
      ) : null}
      {selected !== null ? <UserDrawer id={selected} onClose={() => setSelected(null)} /> : null}
    </>
  );
}

function Bans(): React.JSX.Element {
  const { locale } = useI18n();
  const c = COPY[locale];
  const bans = useGlobalBans();
  const create = useCreateGlobalBan();
  const revoke = useRevokeGlobalBan();
  const [userId, setUserId] = useState("");
  const [reason, setReason] = useState("");
  const parsed = Number.parseInt(userId, 10);

  const remove = async (ban: GlobalBanEntry): Promise<void> => {
    const confirmed = await askConfirmation({ message: `${c.unbanUser}: ${ban.tg_user_id}?`, confirmText: c.unbanUser, cancelText: c.close, destructive: true });
    if (confirmed) revoke.mutate(ban.tg_user_id, { onSuccess: () => hapticResult(true), onError: () => hapticResult(false) });
  };

  return (
    <>
      <SectionTitle>{c.blacklist}</SectionTitle>
      {bans.isPending ? <SkeletonRows count={5} /> : null}
      {bans.isError ? <ErrorState message={bans.error.message} onRetry={() => void bans.refetch()} /> : null}
      {bans.data ? <Card>{bans.data.length === 0 ? <EmptyState text={c.blacklistEmpty} icon="shield" /> : bans.data.map((ban) => <Row key={ban.id} title={`ID ${ban.tg_user_id}`} subtitle={ban.reason || `${ban.chat_count} ${c.chats.toLowerCase()}`} icon="shield" iconTone="destructive" right={<button type="button" className="platform-icon-action text-destructive" onClick={() => void remove(ban)}><Icon name="trash" size={18} /></button>} />)}</Card> : null}
      <SectionTitle>{c.addBan}</SectionTitle>
      <Card className="p-4">
        <div className="grid grid-cols-[minmax(0,0.75fr)_minmax(0,1.25fr)] gap-2">
          <label className="platform-field"><span>{c.telegramId}</span><input className="tg-input" inputMode="numeric" value={userId} onChange={(event) => setUserId(event.target.value)} /></label>
          <label className="platform-field"><span>{c.reason}</span><input className="tg-input" maxLength={512} value={reason} onChange={(event) => setReason(event.target.value)} /></label>
        </div>
        <div className="mt-3"><Button variant="destructive" disabled={!Number.isFinite(parsed) || parsed <= 0 || create.isPending} onClick={() => create.mutate({ tg_user_id: parsed, reason }, { onSuccess: () => { setUserId(""); setReason(""); hapticResult(true); }, onError: () => hapticResult(false) })}>{c.addBan}</Button></div>
      </Card>
    </>
  );
}

function Payments(): React.JSX.Element {
  const { locale } = useI18n();
  const c = COPY[locale];
  const [status, setStatus] = useState<PaymentStatus | undefined>();
  const [provider, setProvider] = useState<PaymentProvider | undefined>();
  const [offset, setOffset] = useState(0);
  const payments = usePlatformPayments({ status, provider, offset });
  const statusLabel: Record<PaymentStatus, string> = { paid: c.paid, pending: c.pending, failed: c.failed, refunded: c.refunded };

  return (
    <>
      <SectionTitle>{c.paymentJournal}</SectionTitle>
      <div className="platform-filter-stack">
        <div className="platform-chip-rail"><Chip active={provider === undefined} onClick={() => { setProvider(undefined); setOffset(0); }}>{c.all}</Chip><Chip active={provider === "stars"} onClick={() => { setProvider("stars"); setOffset(0); }}>{c.stars}</Chip><Chip active={provider === "cryptobot"} onClick={() => { setProvider("cryptobot"); setOffset(0); }}>{c.cryptobot}</Chip></div>
        <div className="platform-chip-rail"><Chip active={status === undefined} onClick={() => { setStatus(undefined); setOffset(0); }}>{c.all}</Chip>{(["paid", "pending", "failed", "refunded"] as const).map((item) => <Chip key={item} active={status === item} onClick={() => { setStatus(item); setOffset(0); }}>{statusLabel[item]}</Chip>)}</div>
      </div>
      {payments.isPending ? <div className="mt-3"><SkeletonRows count={7} /></div> : null}
      {payments.isError ? <ErrorState message={payments.error.message} onRetry={() => void payments.refetch()} /> : null}
      {payments.data ? (
        <>
          <div className="platform-list-summary"><span>{c.found}</span><strong>{number(payments.data.total, locale)}</strong></div>
          <Card>{(payments.data.items ?? []).length === 0 ? <EmptyState text={c.noPayments} icon="star" /> : (payments.data.items ?? []).map((payment) => <div className="platform-payment" key={payment.id}><div className="platform-payment-main"><span className={`platform-provider platform-provider-${payment.provider}`}>{payment.provider === "stars" ? "★" : "₿"}</span><span><strong>{number(payment.amount, locale)} {payment.currency}</strong><small>{payment.chat_title} · {planName(payment.plan)} × {payment.months}</small></span><Badge tone={payment.status === "paid" ? "success" : payment.status === "refunded" ? "warning" : payment.status === "failed" ? "destructive" : "neutral"}>{statusLabel[payment.status]}</Badge></div><div className="platform-payment-meta"><span>{date(payment.created_at, locale)}</span><span>{c.payer}: {payment.payer_tg_id ?? "—"}</span><span title={payment.provider_payment_id}>{c.transaction}: {payment.provider_payment_id.slice(0, 12)}</span></div></div>)}</Card>
          <Pager offset={payments.data.offset} limit={payments.data.limit} total={payments.data.total} onChange={setOffset} />
        </>
      ) : null}
    </>
  );
}

function PlanEditor({ item }: { item: PlatformPlanOverrideResponse }): React.JSX.Element {
  const { locale } = useI18n();
  const c = COPY[locale];
  const meta = useMeta();
  const update = useUpdatePlatformPlan();
  const reset = useResetPlatformPlan();
  const [stars, setStars] = useState(String(item.effective_stars));
  const [usd, setUsd] = useState(item.effective_usd);
  const [features, setFeatures] = useState<string[]>([...(item.effective_features ?? [])]);
  const [note, setNote] = useState(item.note);
  const allFeatures = useMemo(() => Array.from(new Set((meta.data?.plans ?? []).flatMap((plan) => plan.features ?? []))).sort(), [meta.data?.plans]);
  const toggleFeature = (feature: string): void => setFeatures((current) => current.includes(feature) ? current.filter((item) => item !== feature) : [...current, feature]);

  return (
    <>
      <div className="platform-plan-editor-head"><div><small>{c.editPlan}</small><strong>{planName(item.plan)}</strong></div><Badge tone={item.updated_at ? "warning" : "neutral"}>{item.updated_at ? c.override : c.standard}</Badge></div>
      <div className="grid grid-cols-2 gap-2 p-4 pb-0">
        <label className="platform-field"><span>{c.priceStars}</span><input className="tg-input" type="number" min={0} value={stars} onChange={(event) => setStars(event.target.value)} /></label>
        <label className="platform-field"><span>{c.priceUsd}</span><input className="tg-input" inputMode="decimal" value={usd} onChange={(event) => setUsd(event.target.value)} /></label>
      </div>
      <div className="px-4 pt-4"><span className="platform-field-label">{c.features}</span><div className="platform-feature-grid">{allFeatures.map((feature) => <label key={feature} className={`platform-feature ${features.includes(feature) ? "platform-feature-active" : ""}`}><input type="checkbox" checked={features.includes(feature)} onChange={() => { pressFeedback(); toggleFeature(feature); }} /><Icon name={features.includes(feature) ? "check" : "plus"} size={15} /><span>{locale === "ru" ? FEATURE_RU[feature] ?? feature.split("_").join(" ") : feature.split("_").join(" ")}</span></label>)}</div></div>
      <div className="p-4"><label className="platform-field"><span>{c.note}</span><textarea className="tg-input min-h-20 resize-y" value={note} maxLength={2000} onChange={(event) => setNote(event.target.value)} /></label><div className="mt-3 grid grid-cols-[1fr_auto] gap-2"><Button disabled={update.isPending || stars === ""} onClick={() => update.mutate({ plan: item.plan, body: { stars: Number(stars), usd, features, note } }, { onSuccess: () => hapticResult(true), onError: () => hapticResult(false) })}>{c.savePlan}</Button><button type="button" className="platform-reset" aria-label={c.resetPlan} disabled={reset.isPending} onClick={async () => { const confirmed = await askConfirmation({ message: `${c.resetPlan}: ${planName(item.plan)}?`, confirmText: c.resetPlan, cancelText: c.close, destructive: true }); if (confirmed) reset.mutate(item.plan, { onSuccess: () => hapticResult(true), onError: () => hapticResult(false) }); }}><Icon name="refresh" size={19} /></button></div>{update.isError ? <p className="platform-error">{update.error.message}</p> : null}</div>
    </>
  );
}

function Plans(): React.JSX.Element {
  const { locale } = useI18n();
  const c = COPY[locale];
  const plans = usePlatformPlans();
  const [selected, setSelected] = useState<Plan>("pro");
  const item = plans.data?.find((plan) => plan.plan === selected);
  return (
    <>
      <SectionTitle>{c.featureMatrix}</SectionTitle>
      <div className="platform-chip-rail">{PLANS.map((plan) => <Chip key={plan} active={selected === plan} onClick={() => setSelected(plan)}>{planName(plan)}</Chip>)}</div>
      {plans.isPending ? <div className="mt-3"><SkeletonRows count={6} /></div> : null}
      {plans.isError ? <ErrorState message={plans.error.message} onRetry={() => void plans.refetch()} /> : null}
      {item ? <Card key={`${item.plan}-${item.updated_at ?? "stock"}`} className="mt-3"><PlanEditor item={item} /></Card> : null}
    </>
  );
}

function System(): React.JSX.Element {
  const { locale } = useI18n();
  const c = COPY[locale];
  const settings = usePlatformSettings();
  const updateCrypto = useUpdateCryptoBotSettings();
  return (
    <>
      <SectionTitle>{c.deployment}</SectionTitle>
      {settings.isPending ? <SkeletonRows count={5} /> : null}
      {settings.isError ? <ErrorState message={settings.error.message} onRetry={() => void settings.refetch()} /> : null}
      {settings.data ? (
        <>
          <Card>
            <Row title={c.environment} icon="globe" right={<Badge tone={settings.data.environment === "production" ? "success" : "warning"}>{settings.data.environment}</Badge>} />
            <Row title={c.ai} icon="sparkles" right={<Badge tone={settings.data.ai_moderation_available ? "success" : "warning"}>{settings.data.ai_moderation_available ? c.enabled : c.unavailable}</Badge>} />
            <Row title={c.providers} icon="star" right={<span className="text-label text-hint">{(settings.data.payment_providers ?? []).join(" · ") || "—"}</span>} />
            <Row title={c.crossbanThreshold} icon="shield" right={<strong>{settings.data.global_ban_chat_threshold}</strong>} />
          </Card>
          <SectionTitle>{c.cryptoTitle}</SectionTitle>
          <Card>
            <div className="platform-system-hero"><span className="platform-system-orbit"><Icon name="star" size={24} /></span><div><strong>CryptoBot · {settings.data.cryptobot.network}</strong><p>{c.cryptoHint}</p></div></div>
            <Row title={c.testnet} subtitle={settings.data.cryptobot.configured ? (settings.data.cryptobot.testnet ? c.testnet : c.mainnet) : c.cryptoMissing} right={<Toggle label={c.cryptoTitle} checked={settings.data.cryptobot.testnet} disabled={!settings.data.cryptobot.configured || updateCrypto.isPending} onChange={(value) => updateCrypto.mutate(value, { onSuccess: () => hapticResult(true), onError: () => hapticResult(false) })} />} />
          </Card>
          {updateCrypto.isError ? <p className="platform-error">{updateCrypto.error.message}</p> : null}
        </>
      ) : null}
    </>
  );
}

function Broadcast(): React.JSX.Element {
  const { locale } = useI18n();
  const c = COPY[locale];
  const broadcast = useBroadcast();
  const [text, setText] = useState("");
  const [plans, setPlans] = useState<Plan[]>([...PLANS]);
  const togglePlan = (plan: Plan): void => setPlans((current) => current.includes(plan) ? current.filter((item) => item !== plan) : [...current, plan]);
  return (
    <>
      <SectionTitle>{c.broadcastTitle}</SectionTitle>
      <Card className="platform-broadcast-card">
        <div className="platform-broadcast-intro"><span><Icon name="chat" size={23} /></span><div><strong>{c.broadcastTitle}</strong><p>{c.broadcastHint}</p></div></div>
        <label className="platform-field px-4"><span>{c.message}</span><textarea className="tg-input min-h-40 resize-y" maxLength={4000} value={text} onChange={(event) => setText(event.target.value)} /></label>
        <div className="px-4 pt-4"><span className="platform-field-label">{c.recipients}</span><div className="platform-feature-grid">{PLANS.map((plan) => <label key={plan} className={`platform-feature ${plans.includes(plan) ? "platform-feature-active" : ""}`}><input type="checkbox" checked={plans.includes(plan)} onChange={() => { pressFeedback(); togglePlan(plan); }} /><Icon name={plans.includes(plan) ? "check" : "plus"} size={15} /><span>{planName(plan)}</span></label>)}</div></div>
        <div className="p-4"><Button disabled={!text.trim() || plans.length === 0 || broadcast.isPending} onClick={async () => { const confirmed = await askConfirmation({ message: c.broadcastTitle, confirmText: c.send, cancelText: c.close, destructive: false }); if (confirmed) broadcast.mutate({ text: text.trim(), plans }, { onSuccess: () => { setText(""); hapticResult(true); }, onError: () => hapticResult(false) }); }}>{c.send}</Button>{broadcast.isSuccess ? <p className="platform-success">{c.sent}: {broadcast.data.detail}</p> : null}{broadcast.isError ? <p className="platform-error">{broadcast.error.message}</p> : null}</div>
      </Card>
    </>
  );
}

export function PlatformScreen(): React.JSX.Element {
  const { locale } = useI18n();
  const c = COPY[locale];
  const [tab, setTab] = useState<Tab>("overview");
  return (
    <Screen wide>
      <div className="platform-command-header">
        <Header title={c.title} subtitle={c.subtitle} icon="globe" action={<span className="platform-live"><i /> LIVE</span>} />
      </div>
      <Tabs value={tab} onChange={setTab} />
      <div className="platform-workspace" key={tab}>
        {tab === "overview" ? <Overview /> : null}
        {tab === "users" ? <Users /> : null}
        {tab === "bans" ? <Bans /> : null}
        {tab === "payments" ? <Payments /> : null}
        {tab === "plans" ? <Plans /> : null}
        {tab === "system" ? <System /> : null}
        {tab === "broadcast" ? <Broadcast /> : null}
      </div>
    </Screen>
  );
}
