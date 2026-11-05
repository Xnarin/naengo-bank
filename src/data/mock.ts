// 모든 계좌·거래·상품·카드 정보는 프로토타입용 가상(예시) 데이터입니다.

export interface User {
  name: string; email: string; password: string;
  /** 간편비밀번호 6자리 */
  pin: string;
  marketing?: boolean;
  /** 비밀번호·간편비밀번호 연속 오류 횟수. 5회면 locked */
  loginFails?: number;
  locked?: boolean;
  withdrawn?: boolean;
  /** 즐겨찾는 받는 계좌번호 */
  favRecipients?: string[];
}
export type AccountStatus = 'active' | 'suspended' | 'closed';
export interface Account {
  id: string; owner: string; productId: string; name: string; number: string; balance: number; openedAt: string;
  /** 정상 / 거래중지(간편비밀번호 5회 오류) / 해지 */
  status: AccountStatus;
  /** 이체한도(원). 내 계좌끼리 옮기는 돈은 한도에 넣지 않는다 */
  limits: { daily: number; monthly: number };
  favorite?: boolean;
  closedAt?: string;
}
export const DEFAULT_LIMITS = { daily: 1_000_000, monthly: 5_000_000 };
/** 한도 변경 시 넘을 수 없는 최대값(예시) */
export const MAX_LIMITS = { daily: 10_000_000, monthly: 50_000_000 };
export interface Tx {
  id: string; accountId: string; date: string; type: 'in' | 'out'; amount: number;
  counterparty: string; counterpartyAccount?: string; memo?: string; balanceAfter: number;
}
export type CardTheme = 'navy' | 'sky' | 'slate';
/** 사용 중 / 일시정지(본인이 잠금, 해제 가능) / 분실 신고(해제 불가, 재발급) / 해지 */
export type CardStatus = 'active' | 'paused' | 'lost' | 'terminated';
export interface Card {
  id: string; owner: string; name: string; last4: string; accountId: string; status: CardStatus; theme: CardTheme;
  /** 1일 사용한도(원) */
  dailyLimit: number;
  overseas: boolean;
  /** 결제 알림 받기 */
  notify: boolean;
  issuedAt?: string;
}
export const CARD_LIMITS = [300_000, 500_000, 1_000_000, 2_000_000, 3_000_000];
export interface CardTx { id: string; cardId: string; merchant: string; category: string; date: string; amount: number }
export interface Product {
  id: string; name: string; tag: string; tagline: string; rate: number; baseRate: number;
  benefits: string[]; rateTable: { label: string; rate: string }[];
  target: string[]; conditions: string[]; notices: string[]; details: { title: string; body: string }[];
}
/** 예약 송금. 실행 시각이 되면 store의 실행기가 송금하고 결과를 남긴다. */
export interface Scheduled {
  id: string; owner: string; fromId: string; toNumber: string; toName: string; amount: number; runAt: string;
  status: 'waiting' | 'done' | 'failed' | 'cancelled'; doneAt?: string; reason?: string;
}
/** 자동이체: 주기마다 오전 9시에 실행. weekly면 day는 요일(0=일), monthly면 날짜(말일 넘으면 그달 말일) */
export interface AutoTransfer {
  id: string; owner: string; fromId: string; toNumber: string; toName: string; amount: number; memo?: string;
  cycle: 'monthly' | 'weekly'; day: number;
  /** YYYY-MM-DD */
  startDate: string; endDate?: string;
  nextRunAt: string;
  status: 'active' | 'stopped' | 'ended';
  runs: { at: string; ok: boolean; reason?: string }[];
}

/** 다음 실행 시각(오전 9시): after보다 뒤이고 시작일 이후인 첫 해당일 */
export function nextRun(cycle: AutoTransfer['cycle'], day: number, startDate: string, after: Date): string {
  const start = new Date(`${startDate}T09:00`);
  const base = start > after ? start : after;
  for (let i = 0; i < 400; i++) {
    const c = new Date(base.getFullYear(), base.getMonth(), base.getDate() + i, 9, 0, 0, 0);
    if (c <= after || c < start) continue;
    const last = new Date(c.getFullYear(), c.getMonth() + 1, 0).getDate();
    if (cycle === 'weekly' ? c.getDay() === day : c.getDate() === Math.min(day, last)) return c.toISOString();
  }
  throw new Error('no next run');
}

export interface DB {
  users: User[]; accounts: Account[]; txs: Tx[]; cards: Card[]; cardTxs: CardTx[];
  scheduled: Scheduled[];
  autoTransfers: AutoTransfer[];
  /** 사용자별 알림 마지막 확인 시각 */
  readAt: Record<string, string>;
}

/** 프로토타입 데모 로그인 계정 (테스트 전용) */
export const DEMO = { email: 'demo@naengo.bank', password: 'naengo1234!' };
/** 송금 간편비밀번호 (예시 값, 모든 체험 계정 공통) */
export const DEMO_PIN = '123456';
export const BANK_NAME = '내금고';

export const products: Product[] = [
  {
    id: 'basic', name: '내금고 입출금통장', tag: '기본', tagline: '수수료 걱정 없이 매일 쓰는 기본 통장',
    rate: 0.1, baseRate: 0.1,
    benefits: ['이체 수수료 무제한 면제', 'ATM 출금 수수료 면제', '체크카드 바로 연결'],
    rateTable: [{ label: '전 구간', rate: '연 0.1%' }],
    target: ['만 17세 이상 실명의 개인'],
    conditions: ['1인 1계좌 제한 없음', '이메일 인증을 마친 회원'],
    notices: ['이자는 매월 넷째 주 토요일에 지급돼요.', '금융사기 예방을 위해 개설 후 20영업일 이내 다른 입출금통장 개설이 제한될 수 있어요.'],
    details: [
      { title: '상품 특징', body: '이체·출금 수수료 없이 자유롭게 입출금할 수 있는 기본 통장이에요. 내금고 체크카드를 연결해 결제 계좌로 쓸 수 있어요.' },
      { title: '이자 계산 방식', body: '매일 최종 잔액에 연 0.1%를 적용해 일할 계산하고, 매월 넷째 주 토요일에 한 번에 지급해요.' },
      { title: '해지 안내', body: '앱에서 언제든 해지할 수 있어요. 잔액은 본인 명의 다른 계좌로 이체한 뒤 해지돼요.' },
    ],
  },
  {
    id: 'parking', name: '내금고 파킹통장', tag: '매일 이자', tagline: '하루만 맡겨도 이자가 붙는 파킹통장',
    rate: 2.5, baseRate: 1.0,
    benefits: ['매일 이자 받기', '5천만원까지 최고 연 2.5%', '입출금 자유'],
    rateTable: [{ label: '5천만원 이하', rate: '연 2.5%' }, { label: '5천만원 초과분', rate: '연 1.0%' }],
    target: ['만 19세 이상 실명의 개인', '1인 1계좌'],
    conditions: ['내금고 입출금통장 보유', '이메일 인증을 마친 회원', '1인 1계좌만 개설 가능'],
    notices: ['금리는 시장 상황에 따라 바뀔 수 있어요.', '매일 이자 받기는 하루 한 번, 직접 받기를 눌러야 지급돼요.'],
    details: [
      { title: '상품 특징', body: '잠시 쉬어 가는 돈을 보관하기 좋은 통장이에요. 5천만원 이하 금액에는 연 2.5%, 초과분에는 연 1.0%가 적용돼요.' },
      { title: '매일 이자 받기', body: '전날까지 쌓인 이자를 원하는 날 바로 받을 수 있어요. 받은 이자에도 다시 이자가 붙어요.' },
      { title: '해지 안내', body: '언제든 해지할 수 있고, 해지 시 남은 이자는 함께 지급돼요.' },
    ],
  },
  {
    id: 'youth', name: '내금고 청년 입출금통장', tag: '청년 우대', tagline: '사회초년생을 위한 높은 금리 입출금통장',
    rate: 3.0, baseRate: 0.5,
    benefits: ['100만원까지 최고 연 3.0%', '이체·ATM 수수료 면제', '청년 전용 혜택'],
    rateTable: [{ label: '100만원 이하', rate: '연 3.0%' }, { label: '100만원 초과분', rate: '연 0.5%' }],
    target: ['만 19세 ~ 34세 실명의 개인', '1인 1계좌'],
    conditions: ['가입 시점 만 19세 ~ 34세', '내금고 입출금통장 보유', '만 35세가 되는 해 말일까지 우대금리 적용'],
    notices: ['우대금리는 연령 조건을 충족하는 동안만 적용돼요.', '100만원을 넘는 금액에는 기본금리 연 0.5%가 적용돼요.'],
    details: [
      { title: '상품 특징', body: '사회초년생의 비상금 관리를 돕는 통장이에요. 100만원까지는 연 3.0% 금리를 받을 수 있어요.' },
      { title: '연령 확인', body: '가입할 때 본인인증 정보로 나이를 확인해요. 만 35세가 되는 해 말일 이후에는 기본금리로 바뀌어요.' },
      { title: '해지 안내', body: '언제든 해지할 수 있어요. 해지 후 같은 상품은 다시 가입할 수 없어요.' },
    ],
  },
  {
    id: 'living', name: '내금고 생활비통장', tag: '급여 우대', tagline: '급여를 받으면 금리가 올라가는 생활비 통장',
    rate: 1.2, baseRate: 0.3,
    benefits: ['급여 이체 시 연 1.2%', '공과금 자동이체 관리', '생활비 예산 알림'],
    rateTable: [{ label: '기본금리', rate: '연 0.3%' }, { label: '급여 이체 우대', rate: '+ 연 0.9%p' }],
    target: ['만 17세 이상 실명의 개인'],
    conditions: ['우대금리: 월 50만원 이상 급여 이체 실적', '이메일 인증을 마친 회원'],
    notices: ['급여 실적은 전월 기준으로 확인해요.', '우대 조건을 충족하지 못한 달에는 기본금리가 적용돼요.'],
    details: [
      { title: '상품 특징', body: '생활비를 따로 관리하기 좋은 통장이에요. 급여가 들어오면 우대금리를 더해 드려요.' },
      { title: '급여 실적 인정 기준', body: "적요에 '급여', '상여' 등이 포함된 50만원 이상의 입금을 급여 실적으로 인정해요." },
    ],
  },
  {
    id: 'group', name: '내금고 모임통장', tag: '함께 쓰기', tagline: '친구·가족과 회비를 투명하게 관리해요',
    rate: 0.5, baseRate: 0.5,
    benefits: ['모임원 초대·잔액 함께 보기', '회비 자동 알림', '모임 체크카드 발급'],
    rateTable: [{ label: '전 구간', rate: '연 0.5%' }],
    target: ['만 17세 이상 실명의 개인 (모임주)'],
    conditions: ['모임주는 내금고 입출금통장 보유', '모임원은 최대 100명까지 초대 가능'],
    notices: ['계좌의 법적 소유자는 모임주예요.', '모임원은 내역만 조회할 수 있어요.'],
    details: [
      { title: '상품 특징', body: '모임 회비를 함께 확인하고 관리하는 통장이에요. 모임원은 앱에서 잔액과 내역을 볼 수 있어요.' },
      { title: '모임원 초대', body: '초대 링크를 보내면 내금고 회원 누구나 모임원으로 참여할 수 있어요.' },
    ],
  },
];

export const productById = (id: string) => products.find((p) => p.id === id);

// ── 시드 데이터 (날짜는 오늘 기준 상대값) ─────────────────────
function at(daysAgo: number, time: string) {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  const [h, m] = time.split(':').map(Number);
  d.setHours(h, m, 0, 0);
  return d.toISOString();
}

type Item = [daysAgo: number, time: string, type: 'in' | 'out', amount: number, counterparty: string, memo?: string, counterpartyAccount?: string];

/** 오래된 순 항목 → 거래 후 잔액이 맞도록 계산 (최신순 반환) */
function ledger(accountId: string, finalBalance: number, items: Item[]): Tx[] {
  let bal = finalBalance - items.reduce((s, i) => s + (i[2] === 'in' ? i[3] : -i[3]), 0);
  return items
    .map(([days, time, type, amount, counterparty, memo, counterpartyAccount], idx) => {
      bal += type === 'in' ? amount : -amount;
      return { id: `${accountId}-t${idx}`, accountId, date: at(days, time), type, amount, counterparty, memo, counterpartyAccount, balanceAfter: bal };
    })
    .reverse();
}

const ME = DEMO.email;
const MAIN = '110-482-305917', PARK = '110-482-771203', LIVE = '110-482-118846';
const HONG = '123-456-789012', MINJI = '220-118-450921', SEOJUN = '330-712-009812';

export function seed(): DB {
  const accounts: Account[] = ([
    { id: 'acc-1', owner: ME, productId: 'basic', name: '내금고 입출금통장', number: MAIN, balance: 1_284_500, openedAt: at(400, '10:00') },
    { id: 'acc-2', owner: ME, productId: 'parking', name: '내금고 파킹통장', number: PARK, balance: 5_020_000, openedAt: at(300, '10:00') },
    { id: 'acc-3', owner: ME, productId: 'living', name: '내금고 생활비통장', number: LIVE, balance: 412_300, openedAt: at(200, '10:00') },
    { id: 'acc-hong', owner: 'hong@example.com', productId: 'basic', name: '내금고 입출금통장', number: HONG, balance: 850_000, openedAt: at(500, '10:00') },
    { id: 'acc-minji', owner: 'minji@example.com', productId: 'basic', name: '내금고 입출금통장', number: MINJI, balance: 430_000, openedAt: at(500, '10:00') },
    { id: 'acc-seojun', owner: 'seojun@example.com', productId: 'basic', name: '내금고 입출금통장', number: SEOJUN, balance: 1_120_000, openedAt: at(500, '10:00') },
  ] as Omit<Account, 'status' | 'limits'>[]).map((a) => ({ ...a, status: 'active', limits: DEFAULT_LIMITS, favorite: a.id === 'acc-1' }));
  const txs = [
    ...ledger('acc-1', 1_284_500, [
      [34, '09:10', 'in', 3_200_000, '(주)새벽테크', '급여'],
      [33, '08:30', 'out', 2_000_000, '이도윤', '파킹통장 저축', PARK],
      [33, '08:31', 'out', 300_000, '이도윤', '자동이체 · 생활비', LIVE],
      [31, '10:00', 'out', 650_000, '박영수', '월세'],
      [28, '19:42', 'out', 45_000, '김민지', '저녁값', MINJI],
      [25, '12:05', 'in', 30_000, '이서준', '커피값', SEOJUN],
      [20, '07:00', 'out', 89_000, '별빛통신', '통신요금 자동이체'],
      [16, '14:20', 'out', 120_000, '안심손해보험', '보험료'],
      [12, '21:11', 'in', 52_000, '홍길동', '중고거래', HONG],
      [6, '10:00', 'out', 650_000, '박영수', '월세'],
      [4, '09:05', 'in', 3_200_000, '(주)새벽테크', '급여'],
      [3, '08:30', 'out', 2_000_000, '이도윤', '파킹통장 저축', PARK],
      [3, '08:31', 'out', 300_000, '이도윤', '자동이체 · 생활비', LIVE],
      [2, '09:00', 'out', 30_000, '김민지', '예약 송금', MINJI],
      [2, '13:40', 'out', 18_500, '이서준', '점심', SEOJUN],
      [1, '18:25', 'in', 100_000, '홍길동', '모임비 정산', HONG],
    ]),
    ...ledger('acc-2', 5_020_000, [
      [40, '00:05', 'in', 7_820, '내금고', '이자'],
      [33, '08:30', 'in', 2_000_000, '이도윤', '파킹통장 저축', MAIN],
      [10, '00:05', 'in', 8_230, '내금고', '이자'],
      [3, '08:30', 'in', 2_000_000, '이도윤', '파킹통장 저축', MAIN],
    ]),
    ...ledger('acc-3', 412_300, [
      [33, '08:31', 'in', 300_000, '이도윤', '생활비', MAIN],
      [27, '09:00', 'out', 82_000, '푸른아파트관리', '관리비'],
      [22, '09:00', 'out', 38_600, '푸른도시가스', '가스요금'],
      [3, '08:31', 'in', 300_000, '이도윤', '생활비', MAIN],
      [1, '09:00', 'out', 78_400, '푸른아파트관리', '관리비'],
    ]),
  ];
  const cardItems: [string, number, string, string, string, number][] = [
    ['card-1', 1, '08:12', '하늘커피 역삼점', '카페', 5_800],
    ['card-1', 1, '12:30', '동네분식', '식비', 9_000],
    ['card-1', 2, '19:05', '마켓온라인', '쇼핑', 32_800],
    ['card-1', 3, '08:40', '시내교통', '교통', 1_550],
    ['card-1', 4, '21:10', '24편의점 강남점', '편의점', 4_300],
    ['card-1', 8, '13:00', '북스토어 강남', '문화', 18_000],
    ['card-1', 11, '19:30', '고기한판', '식비', 46_000],
    ['card-1', 15, '10:20', '마켓온라인', '쇼핑', 27_400],
    ['card-1', 19, '08:10', '하늘커피 역삼점', '카페', 5_800],
    ['card-1', 26, '20:00', '별빛시네마', '문화', 15_000],
    ['card-1', 33, '12:10', '동네분식', '식비', 8_500],
    ['card-1', 38, '18:45', '24편의점 강남점', '편의점', 6_200],
    ['card-1', 45, '11:00', '헬스핏', '운동', 99_000],
    ['card-1', 52, '09:30', '시내교통', '교통', 1_550],
    ['card-2', 2, '10:00', '동네마트', '장보기', 64_200],
    ['card-2', 9, '18:00', '동네마트', '장보기', 38_900],
    ['card-2', 24, '17:30', '동네약국', '의료', 12_000],
    ['card-2', 36, '11:20', '동네마트', '장보기', 51_700],
    ['card-1', 3, '09:10', '하늘커피 역삼점', '카페', 4_800],
    ['card-2', 4, '15:20', '온기로스터리', '카페', 6_500],
    ['card-1', 12, '08:50', '하늘커피 역삼점', '카페', 5_800],
    ['card-2', 22, '14:05', '온기로스터리', '카페', 7_200],
    ['card-1', 30, '10:15', '하늘커피 역삼점', '카페', 5_300],
    ['card-1', 41, '16:40', '온기로스터리', '카페', 6_500],
  ];
  return {
    users: [
      { name: '이도윤', ...DEMO, pin: DEMO_PIN },
      { name: '홍길동', email: 'hong@example.com', password: 'x-unused-1', pin: DEMO_PIN },
      { name: '김민지', email: 'minji@example.com', password: 'x-unused-2', pin: DEMO_PIN },
      { name: '이서준', email: 'seojun@example.com', password: 'x-unused-3', pin: DEMO_PIN },
    ],
    accounts,
    txs,
    cards: [
      { id: 'card-1', owner: ME, name: '내금고 체크카드', last4: '4821', accountId: 'acc-1', status: 'active', theme: 'navy', dailyLimit: 1_000_000, overseas: false, notify: true },
      { id: 'card-2', owner: ME, name: '내금고 체크카드 라이트', last4: '7305', accountId: 'acc-3', status: 'active', theme: 'sky', dailyLimit: 500_000, overseas: false, notify: true },
      { id: 'card-3', owner: ME, name: '내금고 트래블 체크', last4: '1190', accountId: 'acc-2', status: 'lost', theme: 'slate', dailyLimit: 2_000_000, overseas: true, notify: false },
    ],
    cardTxs: cardItems.map(([cardId, days, time, merchant, category, amount], i) => ({ id: `ct-${i}`, cardId, date: at(days, time), merchant, category, amount })),
    scheduled: [
      { id: 'sch-1', owner: ME, fromId: 'acc-1', toNumber: MINJI, toName: '김민지', amount: 30_000, runAt: at(2, '09:00'), status: 'done', doneAt: at(2, '09:00') },
      { id: 'sch-2', owner: ME, fromId: 'acc-3', toNumber: HONG, toName: '홍길동', amount: 500_000, runAt: at(9, '09:00'), status: 'failed', doneAt: at(9, '09:00'), reason: '잔액이 부족했어요' },
      { id: 'sch-3', owner: ME, fromId: 'acc-1', toNumber: HONG, toName: '홍길동', amount: 50_000, runAt: at(-3, '09:00'), status: 'waiting' },
    ],
    readAt: { [ME]: at(2, '08:00') },
    autoTransfers: (() => {
      const day = new Date(at(3, '09:00')).getDate();
      return [{
        id: 'auto-1', owner: ME, fromId: 'acc-1', toNumber: LIVE, toName: '이도윤', amount: 300_000, memo: '생활비',
        cycle: 'monthly' as const, day, startDate: at(60, '09:00').slice(0, 10), nextRunAt: nextRun('monthly', day, at(60, '09:00').slice(0, 10), new Date(at(3, '09:00'))),
        status: 'active' as const, runs: [{ at: at(33, '08:31'), ok: true }, { at: at(3, '08:31'), ok: true }],
      }];
    })(),
  };
}
