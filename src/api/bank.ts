import type { Account, AutoTransfer, Card, CardTx, Scheduled, Tx } from '../data/mock';

export interface AccountResponse {
  id: string; product_code: string; product_name: string; account_num: string; nickname: string | null;
  balance: number; status: 'ACTIVE' | 'SUSPENDED' | 'CLOSED'; is_favorite: boolean;
  daily_limit: number; month_limit: number; created_at: string; closed_at: string | null;
  today_used?: number; month_used?: number;
}
export interface TransactionResponse {
  id: number; account_id: string; transaction_type: string; transaction_direction: 'IN' | 'OUT';
  amount: number; new_balance: number; counterparty_name: string | null; counterparty_account: string | null;
  memo: string | null; transaction_at: string;
}
export interface CardResponse {
  id: string; account_id: string; last4: string; status: string; daily_limit: number;
  overseas_enabled: boolean; created_at: string;
}
export interface PaymentResponse { id: number; card_id: string; amount: number; place: string; category: string | null; request_at: string }
export interface ScheduleResponse {
  id: string; from_account_id: string; to_account_num: string; holder_name: string; amount: number;
  memo: string | null; cycle: 'ONCE' | 'WEEKLY' | 'MONTHLY'; run_day: number | null;
  start_date: string; end_date: string | null; next_run_at: string; status: 'ACTIVE' | 'CANCELED' | 'ENDED';
  last_run: { status: string; fail_reason: string | null; complete_at: string } | null;
}
export interface Term { id: number; title: string; content: string; required: boolean; version: string }
export interface Favorite { id: number; account_num: string; holder_name: string; alias: string | null }
export interface Recipient { account_num: string; holder_name: string; last_sent_at?: string }

export function accountFrom(a: AccountResponse, owner: string): Account {
  return { id: a.id, owner, productId: a.product_code, name: a.nickname || a.product_name, number: a.account_num,
    balance: a.balance, status: a.status.toLowerCase() as Account['status'], favorite: a.is_favorite,
    limits: { daily: a.daily_limit, monthly: a.month_limit }, openedAt: a.created_at, closedAt: a.closed_at ?? undefined,
    usage: { today: a.today_used ?? 0, month: a.month_used ?? 0 } };
}
export function txFrom(t: TransactionResponse): Tx {
  return { id: String(t.id), accountId: t.account_id, date: t.transaction_at, type: t.transaction_direction === 'IN' ? 'in' : 'out',
    amount: t.amount, counterparty: t.counterparty_name ?? '', counterpartyAccount: t.counterparty_account ?? undefined,
    memo: t.memo ?? undefined, balanceAfter: t.new_balance, kind: t.transaction_type };
}
export function cardFrom(c: CardResponse, owner: string): Card {
  return { id: c.id, accountId: c.account_id, owner, name: '내금고 체크카드', last4: c.last4,
    status: ({ ACTIVE: 'active', SUSPENDED: 'paused', LOST: 'lost', REISSUED: 'terminated', CANCELED: 'terminated' } as const)[c.status as 'ACTIVE'] ?? 'terminated',
    dailyLimit: c.daily_limit, overseas: c.overseas_enabled, notify: true, theme: 'navy', issuedAt: c.created_at };
}
export function paymentFrom(p: PaymentResponse): CardTx {
  return { id: String(p.id), cardId: p.card_id, date: p.request_at, merchant: p.place, category: p.category ?? '기타', amount: p.amount };
}
export function scheduledFrom(s: ScheduleResponse, owner: string): Scheduled {
  return { id: s.id, owner, fromId: s.from_account_id, toNumber: s.to_account_num, toName: s.holder_name, amount: s.amount,
    runAt: s.next_run_at, status: s.status === 'ACTIVE' ? 'waiting' : s.status === 'CANCELED' ? 'cancelled' : s.last_run?.status === 'SUCCESS' ? 'done' : 'failed',
    doneAt: s.last_run?.complete_at, reason: s.last_run?.fail_reason ?? undefined };
}
export function autoFrom(s: ScheduleResponse, owner: string): AutoTransfer {
  return { id: s.id, owner, fromId: s.from_account_id, toNumber: s.to_account_num, toName: s.holder_name, amount: s.amount,
    memo: s.memo ?? undefined, cycle: s.cycle === 'WEEKLY' ? 'weekly' : 'monthly', day: s.cycle === 'WEEKLY' ? ((s.run_day ?? 0) + 1) % 7 : s.run_day ?? 1,
    startDate: s.start_date, endDate: s.end_date ?? undefined, nextRunAt: s.next_run_at,
    status: s.status === 'ACTIVE' ? 'active' : s.status === 'CANCELED' ? 'stopped' : 'ended',
    runs: s.last_run ? [{ at: s.last_run.complete_at, ok: s.last_run.status === 'SUCCESS', reason: s.last_run.fail_reason ?? undefined }] : [] };
}
