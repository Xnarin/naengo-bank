// AI 어시스턴트 API 경계.
// - 기본: 시나리오 기반 Mock (./mockChat)
// - VITE_CHAT_API_URL 설정 시: FastAPI + LangGraph 서버로 POST {URL}/chat
//   요청 { message, context } → 응답 { blocks, context } (아래 타입과 동일한 JSON)
// AI는 송금·개설을 "제안"만 하고, 실제 실행은 사용자가 확인 카드를 누른 뒤 은행 API(store)가 수행합니다.
import type { Account, Card, CardTx, Scheduled, Tx } from '../data/mock';
import { mockRespond } from './mockChat';
import { wait } from '../store';

export type Period = 'this-month' | 'last-month' | 'this-week' | 'today';

export interface TransferDraft {
  fromId?: string; toNumber?: string; toName?: string; claimedName?: string; amount?: number;
  /** 예약 송금이면 보낼 시각(ISO). schedule은 "예약"이라고만 하고 시각을 아직 안 정한 상태 */
  runAt?: string; schedule?: boolean;
}
export type ConfirmStatus = 'pending' | 'processing' | 'done' | 'failed' | 'cancelled';

export type Block =
  | { kind: 'text'; text: string }
  | { kind: 'accounts'; items: Pick<Account, 'id' | 'name' | 'number' | 'balance'>[] }
  | { kind: 'transactions'; title: string; items: Pick<Tx, 'id' | 'accountId' | 'date' | 'type' | 'amount' | 'counterparty'>[] }
  | { kind: 'cardUsage'; month: string; total: number; cards: { id: string; name: string; last4: string; total: number; count: number }[]; items: Pick<CardTx, 'id' | 'merchant' | 'date' | 'amount'>[] }
  | { kind: 'spending'; title: string; total: number; count: number; compare?: { label: string; diff: number }; breakdown?: { category: string; total: number }[]; items: Pick<CardTx, 'id' | 'merchant' | 'date' | 'amount'>[] }
  | { kind: 'products'; productIds: string[] }
  | { kind: 'productInfo'; productId: string; field: 'conditions' | 'benefits' | 'rate' | 'notices' }
  | { kind: 'choices'; options: { label: string; value: string }[] }
  | { kind: 'transferConfirm'; draft: Required<Pick<TransferDraft, 'fromId' | 'toNumber' | 'toName' | 'amount'>> & { runAt?: string }; status: ConfirmStatus }
  | { kind: 'scheduledList'; items: { id: string; toName: string; amount: number; runAt: string; fromName: string }[] }
  | { kind: 'links'; links: { label: string; to: string }[] }
  | { kind: 'result'; ok: boolean; title: string; lines: string[] };

export interface ChatMessage { id: string; role: 'user' | 'assistant'; text?: string; blocks?: Block[]; retryText?: string }

/** 대화 맥락: 진행 중인 송금 슬롯, 직전에 추천한 상품 목록 */
export interface ChatContext {
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
export interface ChatResponse { blocks: Block[]; context: ChatContext }
export interface ChatClient { send(req: ChatRequest): Promise<ChatResponse> }

const mockClient: ChatClient = {
  async send({ message, context, snapshot }) {
    await wait(700 + Math.random() * 500);
    if (snapshot.simulateError) throw new Error('mock network error');
    return mockRespond(message, context, snapshot);
  },
};

// 서버 에이전트는 아직 금융 질문(RAG)만 답한다. 조회·송금·카드는 DB 연결 전까지 Mock이 처리:
// 진행 중인 송금은 바로 Mock, 그 외는 서버 라우터가 고른 의도를 보고 나눈다.
// (Mock을 먼저 쓰지 않는 이유: 키워드 매칭이라 "통장 빌려주면 처벌받나요?"를 통장 추천으로 잡는다)
const MOCK_INTENTS = ['ACCOUNT_QUERY', 'TRANSFER', 'CARD_ACTION'];

const httpClient = (baseUrl: string): ChatClient => ({
  async send({ message, context, snapshot }) {
    if (context.pending) return mockRespond(message, context, snapshot);
    const r = await fetch(`${baseUrl}/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ message, context }),
    });
    if (!r.ok) throw new Error(`chat api ${r.status}`);
    const res: ChatResponse & { intent?: string } = await r.json();
    return res.intent && MOCK_INTENTS.includes(res.intent) ? mockRespond(message, context, snapshot) : res;
  },
});

const url = import.meta.env.VITE_CHAT_API_URL as string | undefined;
export const chatClient: ChatClient = url ? httpClient(url) : mockClient;
export const isMockChat = !url;
