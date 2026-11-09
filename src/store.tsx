import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import type { Account, AutoTransfer, Card, CardTheme, DB, Tx, User } from './data/mock';
import type { ChatContext, ChatMessage } from './api/chat';
import { api, BankError, getToken, setToken } from './api/http';
import { accountFrom, autoFrom, cardFrom, paymentFrom, scheduledFrom, txFrom, type AccountResponse, type CardResponse, type Favorite, type PaymentResponse, type Recipient, type ScheduleResponse, type Term, type TransactionResponse } from './api/bank';
export { BankError } from './api/http';
export const wait = (ms = 500) => new Promise((resolve) => setTimeout(resolve, ms));
export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export interface TransferInput { fromId: string; toNumber: string; amount: number }
export interface TransferResult { tx: Tx; toName: string; toNumber: string; balanceAfter: number }
export interface Notice { id: string; date: string; kind: 'in' | 'scheduled' | 'failed' | 'card' | 'auto' | 'login'; title: string; sub: string; to: string; read: boolean }
type Chat = { messages: ChatMessage[]; context: ChatContext };
const emptyChat: Chat = { messages: [], context: {} };
const emptyDB = (): DB => ({ users: [], accounts: [], txs: [], cards: [], cardTxs: [], scheduled: [], autoTransfers: [], readAt: {}, recipients: [] });
type Me = { id: string; email: string; user_name: string };
const stored = <T,>(key: string, fallback: T): T => { try { return JSON.parse(localStorage.getItem(key) ?? 'null') ?? fallback; } catch { return fallback; } };
const normalizeNumber = (value: string) => { const d = value.replace(/\D/g, ''); return `${d.slice(0, 3)}-${d.slice(3, 7)}-${d.slice(7, 11)}`; };
const SYNC_INTERVAL = 10_000;

async function loadInBatches<T, R>(rows: T[], load: (row: T) => Promise<R>, size: number) {
  const result: R[] = [];
  for (let i = 0; i < rows.length; i += size) {
    result.push(...await Promise.all(rows.slice(i, i + size).map(load)));
  }
  return result;
}

function useBankState() {
  const [{ db, user }, setState] = useState<{ db: DB; user: User | null }>({ db: emptyDB(), user: null });
  const [loading, setLoading] = useState(!!getToken());
  const [loadError, setLoadError] = useState('');
  const [chat, setChat] = useState<Chat>(emptyChat);
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [deviceUser, setDevice] = useState<User | null>(() => stored('naengo-api-device', null));
  const [idleMinutes, setIdle] = useState<number>(() => stored('naengo-idle', 10));
  const lastActive = useRef(Date.now());
  const epoch = useRef(0);
  const refreshTail = useRef<{ version: number; task: Promise<boolean> } | null>(null);
  const lastRefresh = useRef(0);
  const codeFlow = useRef<{ email: string; purpose: string; code?: string } | null>(null);
  const favorites = useRef<Favorite[]>([]);
  function toast(message: string) { setToastMsg(message); clearTimeout(timer.current); timer.current = setTimeout(() => setToastMsg(null), 2500); }
  function logout() {
    epoch.current++; setToken(null); setState({ db: emptyDB(), user: null }); setChat(emptyChat);
    lastRefresh.current = 0;
    setNotices([]); setUnread(0); favorites.current = []; codeFlow.current = null;
    setLoading(false); setLoadError('');
  }
  function forgetDevice() { localStorage.removeItem('naengo-api-device'); setDevice(null); }

  async function refresh(background = false): Promise<boolean> {
    const token = getToken(); if (!token) return false;
    const version = epoch.current;
    const queued = refreshTail.current?.version === version ? refreshTail.current.task : null;
    if (background && (queued || Date.now() - lastRefresh.current < SYNC_INTERVAL)) {
      return queued ?? Promise.resolve(false);
    }
    const task = (queued ?? Promise.resolve()).then(() => loadSnapshot(token, version));
    refreshTail.current = { version, task };
    void task.finally(() => { if (refreshTail.current?.task === task) refreshTail.current = null; });
    return task;
  }

  async function loadSnapshot(token: string, version: number) {
    if (version !== epoch.current || getToken() !== token) return false;
    const read = <T,>(path: string) => {
      if (version !== epoch.current || getToken() !== token) throw new Error('Session changed');
      return api<T>(path);
    };
    lastRefresh.current = Date.now();
    if (!user) setLoading(true);
    try {
      const me = await read<Me>('/me');
      const [active, closed, cards, schedules, favs, recent, notices] = await Promise.all([
        read<AccountResponse[]>('/accounts'), read<AccountResponse[]>('/accounts?status=closed'), read<CardResponse[]>('/cards'),
        read<ScheduleResponse[]>('/auto-transfers'), read<Favorite[]>('/favorite-recipients'), read<Recipient[]>('/transfers/recent'),
        read<{ items: { id: number; type: string; message: string; created_at: string; read_at: string | null }[]; unread: number }>('/notifications'),
      ]);
      const rows = [...active, ...closed];
      const today = new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' });
      const accountData = await loadInBatches(rows, (a) => Promise.all([
        read<AccountResponse>(`/accounts/${a.id}`),
        read<TransactionResponse[]>(`/accounts/${a.id}/transactions?from=1900-01-01&to=${today}`),
      ]), 3);
      const payLists = await loadInBatches(cards, (c) => read<PaymentResponse[]>(`/cards/${c.id}/payments`), 6);
      const details = accountData.map(([account]) => account);
      const transactions = accountData.flatMap(([, txs]) => txs);
      if (version !== epoch.current || getToken() !== token) return false;
      const profile: User = { name: me.user_name, email: me.email, favRecipients: favs.map((f) => f.account_num) };
      const recipients = new Map<string, { number: string; name: string; count: number; last: string; fav: boolean }>();
      for (const r of recent) recipients.set(r.account_num, { number: r.account_num, name: r.holder_name, count: transactions.filter((t) => t.transaction_direction === 'OUT' && t.counterparty_account === r.account_num).length, last: r.last_sent_at ?? '', fav: false });
      for (const f of favs) recipients.set(f.account_num, { number: f.account_num, name: f.alias || f.holder_name, count: recipients.get(f.account_num)?.count ?? 0, last: recipients.get(f.account_num)?.last ?? '', fav: true });
      favorites.current = favs;
      const themes = stored<Record<string, CardTheme>>('naengo-card-themes', {});
      setState({ user: profile, db: { users: [profile], accounts: details.map((a) => accountFrom(a, me.email)), txs: transactions.map(txFrom),
        cards: cards.map((c) => ({ ...cardFrom(c, me.email), theme: themes[c.id] ?? 'navy' })), cardTxs: payLists.flat().map(paymentFrom),
        scheduled: schedules.filter((s) => s.cycle === 'ONCE').map((s) => scheduledFrom(s, me.email)),
        autoTransfers: schedules.filter((s) => s.cycle !== 'ONCE').map((s) => autoFrom(s, me.email)), readAt: {},
        recipients: [...recipients.values()].sort((a, b) => Number(b.fav) - Number(a.fav) || b.last.localeCompare(a.last)),
      } });
      setNotices(notices.items.map((n) => ({ id: String(n.id), date: n.created_at,
        kind: n.type === 'CARD_PAYMENT' ? 'card' : n.type === 'TRANSFER_IN' ? 'in' : n.type === 'AUTO_TRANSFER_SUCCESS' ? 'auto' : n.type === 'AUTO_TRANSFER_FAIL' ? 'failed' : 'login',
        title: n.message, sub: '', read: !!n.read_at,
        to: n.type === 'CARD_PAYMENT' ? '/cards' : n.type.startsWith('AUTO_TRANSFER_') ? '/auto-transfers' : n.type === 'TRANSFER_IN' ? '/' : '/settings' })));
      setUnread(notices.unread); setLoadError('');
      if (!profile.email.endsWith('@demo.naengo.invalid')) {
        setDevice({ name: profile.name, email: profile.email });
        try { localStorage.setItem('naengo-api-device', JSON.stringify({ name: profile.name, email: profile.email })); }
        catch { /* 브라우저에 로그인 정보를 기억할 수 없는 경우 */ }
      }
      return true;
    } catch (error) {
      if (version === epoch.current && getToken()) setLoadError((error as Error).message);
      return false;
    } finally { if (version === epoch.current) setLoading(false); }
  }
  const refreshRef = useRef(refresh); refreshRef.current = refresh;
  const [notices, setNotices] = useState<Notice[]>([]);
  const [unread, setUnread] = useState(0);
  useEffect(() => {
    void refreshRef.current(true);
    const expired = () => { logout(); toast('로그인이 만료됐어요. 다시 로그인해 주세요.'); };
    const active = () => { lastActive.current = Date.now(); };
    window.addEventListener('naengo-auth-expired', expired);
    window.addEventListener('pointerdown', active); window.addEventListener('keydown', active);
    return () => { epoch.current++; lastRefresh.current = 0; window.removeEventListener('naengo-auth-expired', expired); window.removeEventListener('pointerdown', active); window.removeEventListener('keydown', active); clearTimeout(timer.current); };
  }, []);
  useEffect(() => {
    const sync = () => {
      if (!getToken()) return;
      if (Date.now() - lastActive.current >= idleMinutes * 60_000) { logout(); toast('일정 시간 사용이 없어 로그아웃했어요.'); }
      else if (document.visibilityState === 'visible') void refreshRef.current(true);
    };
    const poll = setInterval(sync, SYNC_INTERVAL);
    window.addEventListener('focus', sync); window.addEventListener('online', sync);
    document.addEventListener('visibilitychange', sync);
    return () => { clearInterval(poll); window.removeEventListener('focus', sync); window.removeEventListener('online', sync); document.removeEventListener('visibilitychange', sync); };
  }, [idleMinutes]);

  async function mutate<T>(path: string, body?: unknown, method?: string): Promise<T> {
    let result: T;
    try { result = await api<T>(path, body, method); }
    catch (error) { if (error instanceof BankError && error.code === 'PIN_LOCKED') await refresh(); throw error; }
    await refresh();
    return result;
  }
  async function login(email: string, secret: string, pin = false) {
    const result = await api<{ access_token: string }>(pin ? '/auth/login/pin' : '/auth/login', { email, [pin ? 'pin' : 'password']: secret });
    await enterSession(result.access_token);
  }
  async function enterSession(token: string) {
    logout();
    setLoading(true);
    setToken(token); lastActive.current = Date.now();
    if (!await refresh()) throw new BankError('NETWORK', '로그인 후 정보를 불러오지 못했어요. 다시 시도해 주세요.');
  }
  async function sendCode(email: string, purpose: string) {
    const result = await api<{ dev_code?: string }>('/auth/codes', { email, purpose });
    codeFlow.current = { email, purpose };
    return result.dev_code ?? 'sent';
  }
  async function cardAction(id: string, path: string, pin: string) {
    return mutate<CardResponse>(`/cards/${id}/${path}`, { pin });
  }
  const myAccounts = db.accounts.filter((a) => a.status !== 'closed');
  const myCards = db.cards.filter((c) => c.status !== 'terminated');
  return {
    db, user, deviceUser, myAccounts, myCards, closedAccounts: db.accounts.filter((a) => a.status === 'closed'),
    loading, loadError, refresh, chat, setChat, toastMsg, toast, notices, unread,
    simulateError: false, setSimulateError: (_: boolean) => {}, resetDemo: () => void refresh(),
    login: (email: string, password: string) => login(email, password),
    async startDemo() {
      const result = await api<{ access_token: string }>('/auth/demo', {});
      await enterSession(result.access_token);
    },
    loginWithPin: (email: string, pin: string) => login(email, pin, true), logout,
    forgetDevice,
    idleMinutes, setIdleMinutes(value: number) { setIdle(value); localStorage.setItem('naengo-idle', JSON.stringify(value)); },
    async checkEmail(email: string) { return (await api<{ available: boolean }>(`/auth/email-available?email=${encodeURIComponent(email)}`)).available; },
    sendSignupCode: (email: string) => sendCode(email, 'SIGNUP'),
    sendMyCode: () => sendCode(user!.email, 'UNLOCK_ACCOUNT'),
    startReset: (email: string) => sendCode(email, 'RESET_PW'),
    async confirmCode(email: string, code: string) {
      const flow = codeFlow.current;
      if (!flow || flow.email.toLowerCase() !== email.trim().toLowerCase()) throw new BankError('CODE', '인증번호를 먼저 요청해 주세요.');
      await api('/auth/codes/verify', { email, purpose: flow.purpose, code });
      flow.code = code;
    },
    async signup(input: { name: string; email: string; password: string; pin: string; marketing: boolean; agreedTermIds: number[] }) {
      await api('/auth/signup', { email: input.email, password: input.password, pin: input.pin, user_name: input.name, agreed_term_ids: input.agreedTermIds });
      codeFlow.current = null;
    },
    async resetPassword(email: string, newPassword: string) { await api('/auth/password/reset', { email, code: codeFlow.current?.code, new_password: newPassword }); codeFlow.current = null; },
    async updateName(name: string) { await mutate('/me', { user_name: name }, 'PATCH'); },
    async changePassword(current: string, next: string) { await api('/me/password', { current_password: current, new_password: next }, 'PUT'); },
    async changePin(currentPin: string, newPin: string) { await api('/me/pin', { current_pin: currentPin, new_pin: newPin }, 'PUT'); },
    withdrawBlockers: () => withdrawBlockers(db, user?.email ?? ''),
    async withdraw(pin: string) { await api('/me', { pin }, 'DELETE'); forgetDevice(); logout(); },
    async verifyPin(pin: string, accountId?: string) { await api('/pin/verify', { pin, account_id: accountId }); },
    async unlockAccount(id: string, code: string) { await mutate(`/accounts/${id}/unlock`, { code }); },
    async setLimits(id: string, limits: { daily: number; monthly: number }, pin: string) { await mutate(`/accounts/${id}/limits`, { daily_limit: limits.daily, month_limit: limits.monthly, pin }, 'PUT'); },
    async toggleFavorite(id: string) { await mutate(`/accounts/${id}/favorite`, {}); },
    async closeAccount(id: string, pin: string) { await mutate(`/accounts/${id}/close`, { pin }); },
    async lookupAccount(value: string) { const r = await api<{ account_num: string; holder_name: string; mine: boolean }>(`/transfers/recipient?account_num=${normalizeNumber(value)}`); return { number: r.account_num, name: r.holder_name, mine: r.mine }; },
    async transfer(input: TransferInput, pin: string, key: string): Promise<TransferResult> {
      type Result = { transfer_id: string; amount: number; to_name: string; to_account_num: string; new_balance: number };
      let result: Result;
      try {
        result = await mutate<Result>('/transfers', {
          from_account_id: input.fromId, to_account_num: normalizeNumber(input.toNumber), amount: input.amount, pin, idempotency_key: key,
        });
      } catch (error) {
        if (!(error instanceof BankError) || error.code !== 'NETWORK') throw error;
        try { result = await api<Result>(`/transfers/by-key/${key}`); }
        catch { throw new BankError('NETWORK', '송금 결과를 확인하지 못했어요. 거래내역을 확인한 뒤 다시 시도해 주세요.'); }
        await refresh();
      }
      return { toName: result.to_name, toNumber: result.to_account_num, balanceAfter: result.new_balance,
        tx: { id: result.transfer_id, accountId: input.fromId, date: new Date().toISOString(), type: 'out', amount: result.amount, counterparty: result.to_name, balanceAfter: result.new_balance } };
    },
    async scheduleTransfer(input: TransferInput & { runAt: string }, pin: string) {
      const row = await mutate<ScheduleResponse>('/auto-transfers', { from_account_id: input.fromId, to_account_num: normalizeNumber(input.toNumber), amount: input.amount, cycle: 'ONCE', run_at: input.runAt, pin });
      return scheduledFrom(row, user!.email);
    },
    async cancelScheduled(id: string) { await mutate(`/auto-transfers/${id}`, undefined, 'DELETE'); },
    async markNoticesRead() {
      const ids = notices.filter((n) => !n.read).map((n) => Number(n.id));
      if (!ids.length) return;
      await api('/notifications/read-all', { ids });
      await refresh();
    },
    async issueCard(input: { accountId: string; dailyLimit: number; overseas: boolean; theme: CardTheme }) {
      const row = await mutate<CardResponse>('/cards', { account_id: input.accountId, daily_limit: input.dailyLimit, overseas_enabled: input.overseas });
      const themes = stored<Record<string, CardTheme>>('naengo-card-themes', {});
      try { localStorage.setItem('naengo-card-themes', JSON.stringify({ ...themes, [row.id]: input.theme })); } catch { /* 표현 설정 저장 불가 */ }
      setState((state) => ({ ...state, db: { ...state.db, cards: state.db.cards.map((c) => c.id === row.id ? { ...c, theme: input.theme } : c) } }));
      return { ...cardFrom(row, user!.email), theme: input.theme };
    },
    async updateCard(id: string, patch: Partial<Pick<Card, 'dailyLimit' | 'overseas' | 'notify'>>, pin: string) { await mutate(`/cards/${id}`, { daily_limit: patch.dailyLimit, overseas_enabled: patch.overseas, pin }, 'PATCH'); },
    async setCardPaused(id: string, paused: boolean, pin: string) { await cardAction(id, paused ? 'suspend' : 'resume', pin); },
    async reportLost(id: string, pin: string) { await cardAction(id, 'lost', pin); },
    async reissueCard(id: string, pin: string) { return cardFrom(await cardAction(id, 'reissue', pin), user!.email); },
    async terminateCard(id: string, pin: string) { await cardAction(id, 'cancel', pin); },
    async payWithCard(id: string, input: { merchant: string; category: string; amount: number; overseas: boolean }) {
      const body = { place: input.merchant, category: input.category, amount: input.amount, overseas: input.overseas };
      const storageKey = `naengo-pending-payment:${id}`;
      const pending = JSON.parse(localStorage.getItem(storageKey) ?? 'null') as { key: string; body: typeof body } | null;
      if (pending && JSON.stringify(pending.body) !== JSON.stringify(body)) {
        throw new BankError('PAYMENT_PENDING', `앞선 ${pending.body.place} ${pending.body.amount.toLocaleString()}원 결제 결과를 확인하지 못했어요. 같은 가맹점과 금액으로 다시 시도해 주세요.`);
      }
      const request = pending ?? { key: crypto.randomUUID(), body };
      localStorage.setItem(storageKey, JSON.stringify(request));
      try {
        await mutate(`/cards/${id}/payments`, { ...body, idempotency_key: request.key });
        localStorage.removeItem(storageKey);
      } catch (error) {
        if (error instanceof BankError && error.code !== 'NETWORK') localStorage.removeItem(storageKey);
        throw error;
      }
    },
    async toggleFavRecipient(number: string) { const f = favorites.current.find((r) => r.account_num === number); if (f) await mutate(`/favorite-recipients/${f.id}`, undefined, 'DELETE'); else await mutate('/favorite-recipients', { account_num: number }); },
    async createAutoTransfer(input: Pick<AutoTransfer, 'fromId' | 'toNumber' | 'amount' | 'cycle' | 'day' | 'startDate' | 'endDate' | 'memo'>, pin: string) {
      const row = await mutate<ScheduleResponse>('/auto-transfers', { from_account_id: input.fromId, to_account_num: normalizeNumber(input.toNumber), amount: input.amount, cycle: input.cycle.toUpperCase(), run_day: input.cycle === 'weekly' ? (input.day + 6) % 7 : input.day,
        start_date: input.startDate, end_date: input.endDate || null, memo: input.memo, pin });
      return autoFrom(row, user!.email);
    },
    async stopAutoTransfer(id: string) { await mutate(`/auto-transfers/${id}`, undefined, 'DELETE'); },
    async openAccount(productId: string, input: { password: string; passwordConfirm: string; purpose: string; agreedTermIds: number[] }): Promise<Account> {
      const row = await mutate<AccountResponse>('/accounts', { product_code: productId, password: input.password, password_confirm: input.passwordConfirm, opening_info: { purpose: input.purpose }, agreed_term_ids: input.agreedTermIds });
      return accountFrom(row, user!.email);
    },
    async statement(id: string, from: string, to: string, email: string) { const r = await api<{ status: string }>(`/accounts/${id}/statements`, { from_date: from, to_date: to, email }); if (r.status !== 'SENT') throw new BankError('MAIL', '메일을 발송하지 못했어요. 잠시 후 다시 시도해 주세요.'); },
    getTerms: (category: string) => api<Term[]>(`/terms?category=${category}`),
  };
}

export function cardUsedToday(db: DB, id: string) { const today = new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' }); return db.cardTxs.filter((t) => t.cardId === id && new Date(t.date).toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' }) === today).reduce((s, t) => s + t.amount, 0); }
export function recentRecipients(db: DB, _email: string) { return db.recipients ?? []; }
export function usageOf(db: DB, id: string) { return db.accounts.find((a) => a.id === id)?.usage ?? { today: 0, month: 0 }; }
export function withdrawBlockers(db: DB, email: string) { const n = db.accounts.filter((a) => a.owner === email && a.status !== 'closed').length; return n ? [`계좌 ${n}개를 모두 해지한 뒤 탈퇴할 수 있어요.`] : []; }
export type CloseBlocker = { kind: 'balance' | 'card' | 'scheduled' | 'status'; text: string };
export function closeBlockers(db: DB, id: string): CloseBlocker[] {
  const a = db.accounts.find((a) => a.id === id); if (!a) return [];
  const out: CloseBlocker[] = [];
  if (a.status !== 'active') out.push({ kind: 'status', text: '정상 상태인 계좌만 해지할 수 있어요.' });
  if (a.balance) out.push({ kind: 'balance', text: '잔액을 다른 계좌로 옮겨 주세요.' });
  if (db.cards.some((c) => c.accountId === id && c.status !== 'terminated')) out.push({ kind: 'card', text: '연결된 체크카드를 먼저 해지해 주세요.' });
  if (db.scheduled.some((s) => s.fromId === id && s.status === 'waiting') || db.autoTransfers.some((s) => s.fromId === id && s.status === 'active')) out.push({ kind: 'scheduled', text: '예약·자동이체를 먼저 취소해 주세요.' });
  return out;
}
type Bank = ReturnType<typeof useBankState>;
const Context = createContext<Bank | null>(null);
export function BankProvider({ children }: { children: ReactNode }) { return <Context.Provider value={useBankState()}>{children}</Context.Provider>; }
export function useBank() { const value = useContext(Context); if (!value) throw new Error('BankProvider missing'); return value; }
export function useLoad(_deps: unknown[] = [], _ms = 0) { const bank = useBank(); return { state: bank.loading ? 'loading' as const : !bank.user && bank.loadError ? 'error' as const : 'ready' as const, retry: () => void bank.refresh() }; }
