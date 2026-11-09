// AI 어시스턴트 API 경계.
// - 기본: 시나리오 기반 Mock (./mockChat)
// - VITE_CHAT_API_URL 설정 시: FastAPI + LangGraph 서버로 POST {URL}/chat
//   요청 { message, context } → 응답 { blocks, context } (아래 타입과 동일한 JSON)
// AI는 송금·개설을 "제안"만 하고, 실제 실행은 사용자가 확인 카드를 누른 뒤 은행 API(store)가 수행합니다.
import type { Account, Card, CardTx, Scheduled, Tx } from '../data/mock';
import { api } from './http';

export type Period = 'this-month' | 'last-month' | 'this-week' | 'today';

export interface TransferDraft {
  fromId?: string; toNumber?: string; toName?: string; claimedName?: string; amount?: number;
  /** 예약 송금이면 보낼 시각(ISO). schedule은 "예약"이라고만 하고 시각을 아직 안 정한 상태 */
  runAt?: string; schedule?: boolean;
}
export type ConfirmStatus = 'pending' | 'processing' | 'done' | 'failed' | 'cancelled';

export type InsightBlock =
  | { kind: 'recommendationInsight'; status: string; start: string; end: string; cardTotal: number; count: number;
      recurringCount: number; question?: string | null; notes: string[];
      items: { code: string; name: string; owned: boolean; reasons: string[]; maxRate: number; baseRate: number;
        conditions: string[]; rateTable: { label: string; rate: string }[]; notices: string[] }[] }
  | { kind: 'spendingInsight'; start: string; end: string; total: number; cardTotal: number; transferTotal: number;
      categories: { label: string; amount: number; previous?: number }[];
      comparison?: { total: number; delta: number; start: string; end: string }; notes: string[] }
  | { kind: 'forecastInsight'; month: string; asOf: string; balance: number; sufficient: boolean; observedDays: number;
      observedCount: number; fixedTotal: number; reason?: string; estimatedExpense?: number; projectedBalance?: number;
      shortage?: number; dailyBudget?: number; expenseRange?: { min: number; max: number };
      points?: { date: string; balance: number }[]; scheduled: { date: string; amount: number; label: string }[]; notes: string[] }
  | { kind: 'subscriptionInsight'; start: string; end: string; total: number; note: string;
      items: { name: string; amount: number; count: number; lastDate: string; billingDay: number }[] };

export type Block =
  | InsightBlock
  | { kind: 'agentConfirm'; threadId: string; confirmationId: string; actionType?: string | null; display: Record<string, string | number>; status: ConfirmStatus | 'unknown' }
  | { kind: 'text'; text: string }
  | { kind: 'accounts'; items: Pick<Account, 'id' | 'name' | 'number' | 'balance'>[] }
  | { kind: 'transactions'; title: string; items: Pick<Tx, 'id' | 'accountId' | 'date' | 'type' | 'amount' | 'counterparty'>[] }
  | { kind: 'cardUsage'; month: string; total: number; cards: { id: string; name: string; last4: string; total: number; count: number }[]; items: Pick<CardTx, 'id' | 'merchant' | 'date' | 'amount'>[] }
  | { kind: 'spending'; title: string; total: number; count: number; compare?: { label: string; diff: number }; breakdown?: { category: string; total: number }[]; items: Pick<CardTx, 'id' | 'merchant' | 'date' | 'amount'>[] }
  | { kind: 'products'; productIds: string[] }
  | { kind: 'productInfo'; productId: string; field: 'conditions' | 'benefits' | 'rate' | 'notices' }
  | { kind: 'choices'; title?: string; options: { label: string; value?: string }[] }
  | { kind: 'transferConfirm'; draft: Required<Pick<TransferDraft, 'fromId' | 'toNumber' | 'toName' | 'amount'>> & { runAt?: string }; status: ConfirmStatus }
  | { kind: 'scheduledList'; items: { id: string; toName: string; amount: number; runAt: string; fromName: string }[] }
  | { kind: 'links'; links: { label: string; to: string }[] }
  | { kind: 'result'; ok: boolean; title: string; lines: string[] };

export interface ChatMessage { id: string; role: 'user' | 'assistant'; text?: string; blocks?: Block[]; retryText?: string }

/** 대화 맥락: 진행 중인 송금 슬롯, 직전에 추천한 상품 목록 */
export interface ChatContext {
  threadId?: string;
  pending?: { type: 'transfer'; awaiting: 'from' | 'to' | 'amount' | 'when'; draft: TransferDraft };
  lastProductIds?: string[];
  /** 직전 소비 분석 질문 ("그럼 지난달은?" 같은 후속 질문용) */
  lastSpending?: { category?: string; period: Period };
}

/** Mock 전용: 서버라면 자체적으로 조회할 데이터 */
export interface BankSnapshot {
  userName: string;
  accounts: Account[];
  txs: Tx[];
  cards: Card[];
  cardTxs: CardTx[];
  recipients: { name: string; number: string }[];
  /** 대기 중인 예약 송금 */
  scheduled: Scheduled[];
  lookup: (no: string) => { name: string; number: string } | null;
  simulateError: boolean;
}

export interface ChatRequest { message: string; context: ChatContext; snapshot: BankSnapshot }
export interface ChatResponse { blocks: Block[]; context: ChatContext; status?: string }
export interface ChatClient { send(req: ChatRequest): Promise<ChatResponse>; confirm(threadId: string, confirmationId: string, approved: boolean, pin?: string): Promise<ChatResponse> }

interface AgentResponse {
  blocks: Block[]; context: ChatContext; thread_id: string; status: string;
  confirm?: Record<string, string | number>;
  confirmation_id?: string | null;
  confirmation_type?: string | null;
}
function fromAgent(response: AgentResponse): ChatResponse {
  return { blocks: [...response.blocks, ...(response.status === 'confirm' && response.confirm && response.confirmation_id
    ? [{ kind: 'agentConfirm' as const, threadId: response.thread_id, confirmationId: response.confirmation_id,
        actionType: response.confirmation_type, display: response.confirm, status: 'pending' as const }] : [])],
    context: { ...response.context, threadId: response.thread_id }, status: response.status };
}
export const chatClient: ChatClient = {
  async send({ message, context }) {
    return fromAgent(await api<AgentResponse>('/agent/chat', { message, context, thread_id: context.threadId }));
  },
  async confirm(threadId, confirmationId, approved, pin) {
    return fromAgent(await api<AgentResponse>('/agent/confirm', { thread_id: threadId, confirmation_id: confirmationId, approved, pin }));
  },
};
export const lookupAgentTransfer = (confirmationId: string) =>
  api<{ status: string }>(`/agent/transfers/${encodeURIComponent(confirmationId)}`);
export const isMockChat = false;
