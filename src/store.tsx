// Mock 은행 API + 앱 상태. 실제 서버 연동 시 이 파일의 async 함수들을 fetch 호출로 교체하면 됩니다.
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { CARD_LIMITS, DEFAULT_LIMITS, DEMO_PIN, MAX_LIMITS, seed, productById, nextRun, type Account, type AutoTransfer, type Card, type CardTheme, type DB, type Scheduled, type Tx, type User } from './data/mock';
import type { ChatContext, ChatMessage } from './api/chat';

export class BankError extends Error {
  code: string;
  constructor(code: string, message: string) {
    super(message);
    this.code = code;
  }
}

export const wait = (ms = 500) => new Promise((r) => setTimeout(r, ms));
const digits = (s: string) => s.replace(/\D/g, '');
const KEY = 'naengo-v2';

type Persisted = { db: DB; session: string | null };
function load(): Persisted {
  try {
    const raw = localStorage.getItem(KEY);
    if (raw) {
      const p: Persisted = JSON.parse(raw);
      p.db.scheduled ??= []; // 예약 송금 추가 전에 저장된 데이터 보정
      p.db.autoTransfers ??= [];
      p.db.readAt ??= {};
      p.db.cards = p.db.cards.map((c) => ({ ...c, dailyLimit: c.dailyLimit ?? 1_000_000, overseas: c.overseas ?? false, notify: c.notify ?? true, status: (c.status as string) === 'suspended' ? 'lost' : c.status }));
      p.db.users = p.db.users.map((u) => ({ ...u, pin: u.pin ?? DEMO_PIN }));
      p.db.accounts = p.db.accounts.map((a) => ({ ...a, status: a.status ?? 'active', limits: a.limits ?? DEFAULT_LIMITS }));
      return p;
    }
  } catch { /* 저장소 사용 불가 → 시드 사용 */ }
  return { db: seed(), session: null };
}

export interface TransferInput { fromId: string; toNumber: string; amount: number }
export interface TransferResult { tx: Tx; toName: string; toNumber: string; balanceAfter: number }
/** 알림 화면 한 줄. 입금 거래와 예약 송금 결과에서 만든다. */
export interface Notice { id: string; date: string; kind: 'in' | 'scheduled' | 'failed' | 'card' | 'auto'; title: string; sub: string; to: string }
type Chat = { messages: ChatMessage[]; context: ChatContext };
const emptyChat: Chat = { messages: [], context: {} };

function useBankState() {
  const [{ db, session }, setState] = useState(load);
  const ref = useRef({ db, session });
  const [simulateError, setSimulateError] = useState(false);
  const simRef = useRef(false);
  simRef.current = simulateError;
  const [chat, setChat] = useState<Chat>(emptyChat);
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const toastTimer = useRef<number>(undefined);
  const pinFails = useRef(0);
  /** Mock 이메일 인증: 마지막으로 보낸 주소·코드, 인증을 마친 주소 */
  const mail = useRef<{ to: string; code: string } | null>(null);
  const verifiedEmail = useRef<string | null>(null);
  const [device, setDevice] = useState(savedDevice);
  const [idleMinutes, setIdleState] = useState(savedIdle);
  const lastActive = useRef(Date.now());

  useEffect(() => {
    try { localStorage.setItem(KEY, JSON.stringify({ db, session })); } catch { /* noop */ }
  }, [db, session]);

  const commit = (next: Partial<Persisted>) => {
    ref.current = { ...ref.current, ...next };
    setState(ref.current);
  };
  function showToast(msg: string) {
    setToastMsg(msg);
    clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToastMsg(null), 2200);
  }
  const failIfSimulated = () => {
    if (simRef.current) throw new BankError('NETWORK', '일시적인 네트워크 오류가 발생했어요. 잠시 후 다시 시도해 주세요.');
  };
  const nameOf = (email: string) => ref.current.db.users.find((u) => u.email === email)?.name ?? '알 수 없음';
  const findByNumber = (no: string) => ref.current.db.accounts.find((a) => digits(a.number) === digits(no));
  const myCard = (id: string) => {
    const c = ref.current.db.cards.find((x) => x.id === id && x.owner === ref.current.session);
    if (!c) throw new BankError('NO_CARD', '카드를 찾을 수 없어요.');
    return c;
  };
  const patchCard = (id: string, patch: Partial<Card>) => {
    const cur = ref.current.db;
    commit({ db: { ...cur, cards: cur.cards.map((c) => (c.id === id ? { ...c, ...patch } : c)) } });
  };
  const findUser = (email: string) => ref.current.db.users.find((u) => !u.withdrawn && u.email.toLowerCase() === email.trim().toLowerCase());
  const patchUser = (email: string, patch: Partial<User>) => {
    const cur = ref.current.db;
    commit({ db: { ...cur, users: cur.users.map((u) => (u.email === email ? { ...u, ...patch } : u)) } });
  };

  async function confirmCode(email: string, code: string) {
    await wait(400);
    failIfSimulated();
    if (!mail.current || mail.current.to !== normEmail(email) || mail.current.code !== code) throw new BankError('CODE', '인증번호가 맞지 않아요. 다시 확인해 주세요.');
    verifiedEmail.current = mail.current.to;
    mail.current = null;
  }
  function issueCode(email: string) {
    mail.current = { to: normEmail(email), code: String(Math.floor(100000 + Math.random() * 900000)) };
    verifiedEmail.current = null;
    return mail.current.code;
  }

  /** 로그인 공통: 잠금 확인 → 자격 확인(5회 실패 시 잠금) → 세션 + 이 기기 기억 */
  function signIn(email: string, ok: (u: User) => boolean, failMsg: string) {
    const u = findUser(email);
    if (!u) throw new BankError('AUTH', '이메일 또는 비밀번호가 일치하지 않아요.');
    if (u.locked) throw new BankError('LOGIN_LOCKED', '비밀번호를 5회 틀려 로그인이 잠겼어요. 비밀번호 재설정으로 풀 수 있어요.');
    if (!ok(u)) {
      const fails = (u.loginFails ?? 0) + 1;
      patchUser(u.email, { loginFails: fails, locked: fails >= 5 });
      if (fails >= 5) throw new BankError('LOGIN_LOCKED', '비밀번호를 5회 틀려 로그인이 잠겼어요. 비밀번호 재설정으로 풀 수 있어요.');
      throw new BankError('AUTH', `${failMsg} (${fails}/5)`);
    }
    patchUser(u.email, { loginFails: 0 });
    commit({ session: u.email });
    lastActive.current = Date.now();
    try { localStorage.setItem(DEVICE_KEY, u.email); } catch { /* noop */ }
    setDevice(u.email);
  }

  // 무활동 자동 로그아웃
  useEffect(() => {
    const touch = () => { lastActive.current = Date.now(); };
    const evs = ['pointerdown', 'keydown', 'scroll', 'touchstart'] as const;
    evs.forEach((e) => window.addEventListener(e, touch, { passive: true }));
    const t = setInterval(() => {
      if (ref.current.session && Date.now() - lastActive.current > idleMinutes * 60_000) {
        commit({ session: null });
        setChat(emptyChat);
        showToast(`${idleMinutes}분 동안 사용이 없어 로그아웃했어요`);
      }
    }, 5000);
    return () => { evs.forEach((e) => window.removeEventListener(e, touch)); clearInterval(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [idleMinutes]);

  /** 송금 실행(검증 + 양쪽 계좌·거래 반영). 즉시 송금과 예약 실행기가 같이 쓴다. */
  function applyTransfer({ fromId, toNumber, amount }: TransferInput, owner: string, memo: string): TransferResult {
    const cur = ref.current.db;
    const from = cur.accounts.find((a) => a.id === fromId && a.owner === owner);
    const to = findByNumber(toNumber);
    if (!from) throw new BankError('INVALID_FROM', '출금 계좌를 찾을 수 없어요.');
    if (!Number.isInteger(amount) || amount <= 0) throw new BankError('INVALID_AMOUNT', '송금 금액을 확인해 주세요.');
    if (!to) throw new BankError('INVALID_ACCOUNT', '존재하지 않는 계좌예요. 계좌번호를 다시 확인해 주세요.');
    if (to.id === from.id) throw new BankError('SAME_ACCOUNT', '출금 계좌와 같은 계좌로는 보낼 수 없어요.');
    if (from.status === 'suspended') throw new BankError('SUSPENDED', '거래가 중지된 계좌예요. 계좌 관리에서 본인인증으로 해제해 주세요.');
    if (from.status === 'closed') throw new BankError('INVALID_FROM', '해지된 계좌에서는 보낼 수 없어요.');
    if (to.status !== 'active') throw new BankError('INVALID_ACCOUNT', '받을 수 없는 계좌예요(거래중지 또는 해지). 받는 분께 확인해 주세요.');
    if (to.owner !== from.owner) {
      const u = usageOf(cur, from.id);
      if (u.today + amount > from.limits.daily) throw new BankError('LIMIT', `1일 이체한도를 넘어요. 오늘 ${(from.limits.daily - u.today).toLocaleString()}원까지 보낼 수 있어요.`);
      if (u.month + amount > from.limits.monthly) throw new BankError('LIMIT', `1달 이체한도를 넘어요. 이번 달 ${(from.limits.monthly - u.month).toLocaleString()}원까지 보낼 수 있어요.`);
    }
    if (amount > from.balance) throw new BankError('INSUFFICIENT', `잔액이 부족해요. 출금 가능 금액은 ${from.balance.toLocaleString()}원이에요.`);

    const now = new Date().toISOString();
    const toName = nameOf(to.owner);
    const sameOwner = to.owner === from.owner;
    const txId = `tx-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const outTx: Tx = { id: `${txId}-o`, accountId: from.id, date: now, type: 'out', amount, counterparty: sameOwner ? to.name : toName, counterpartyAccount: to.number, memo, balanceAfter: from.balance - amount };
    const inTx: Tx = { id: `${txId}-i`, accountId: to.id, date: now, type: 'in', amount, counterparty: sameOwner ? from.name : nameOf(from.owner), counterpartyAccount: from.number, memo, balanceAfter: to.balance + amount };
    commit({
      db: {
        ...cur,
        accounts: cur.accounts.map((a) => (a.id === from.id ? { ...a, balance: a.balance - amount } : a.id === to.id ? { ...a, balance: a.balance + amount } : a)),
        txs: [outTx, inTx, ...cur.txs],
      },
    });
    return { tx: outTx, toName, toNumber: to.number, balanceAfter: outTx.balanceAfter };
  }

  /** 실행 시각이 지난 예약 송금을 처리한다. 실제 서버라면 배치가 하는 일. */
  function runDue() {
    const due = ref.current.db.scheduled.filter((x) => x.status === 'waiting' && new Date(x.runAt).getTime() <= Date.now());
    let mineDone = 0, mineFailed = 0;
    for (const x of due) {
      let patch: Partial<Scheduled>;
      try {
        applyTransfer(x, x.owner, '예약 송금');
        patch = { status: 'done', doneAt: new Date().toISOString() };
        if (x.owner === ref.current.session) mineDone++;
      } catch (e) {
        patch = { status: 'failed', doneAt: new Date().toISOString(), reason: (e as Error).message };
        if (x.owner === ref.current.session) mineFailed++;
      }
      const cur = ref.current.db;
      commit({ db: { ...cur, scheduled: cur.scheduled.map((y) => (y.id === x.id ? { ...y, ...patch } : y)) } });
    }
    // 자동이체: 시각이 지난 것을 한 번 실행하고 다음 회차를 잡는다(놓친 회차는 몰아서 실행하지 않음)
    const autos = ref.current.db.autoTransfers.filter((x) => x.status === 'active' && new Date(x.nextRunAt).getTime() <= Date.now());
    for (const x of autos) {
      const run = runAuto(x);
      const now = new Date();
      const next = nextRun(x.cycle, x.day, x.startDate, now);
      const ended = !!x.endDate && new Date(next) > new Date(`${x.endDate}T23:59:59`);
      const cur = ref.current.db;
      commit({ db: { ...cur, autoTransfers: cur.autoTransfers.map((y) => (y.id === x.id ? { ...y, runs: [...y.runs, run], nextRunAt: next, status: ended ? 'ended' : y.status } : y)) } });
      if (x.owner === ref.current.session) { if (run.ok) mineDone++; else mineFailed++; }
    }
    if (mineFailed) showToast('예약·자동이체가 실패했어요. 알림에서 확인해 주세요');
    else if (mineDone) showToast('예약·자동이체가 실행됐어요');
  }
  /** 자동이체 1회 실행 → 결과 기록용 */
  function runAuto(x: AutoTransfer) {
    const at = new Date().toISOString();
    try {
      applyTransfer(x, x.owner, `자동이체${x.memo ? ` · ${x.memo}` : ''}`);
      return { at, ok: true };
    } catch (e) {
      return { at, ok: false, reason: (e as Error).message };
    }
  }
  const runDueRef = useRef(runDue);
  runDueRef.current = runDue;
  useEffect(() => {
    runDueRef.current();
    const t = setInterval(() => runDueRef.current(), 5000);
    return () => clearInterval(t);
  }, []);

  const user: User | null = db.users.find((u) => u.email === session) ?? null;
  // 즐겨찾기 먼저, 해지 계좌 제외
  const myAccounts = db.accounts.filter((a) => a.owner === session && a.status !== 'closed').sort((a, b) => Number(!!b.favorite) - Number(!!a.favorite));
  const deviceUser = db.users.find((u) => u.email === device && !u.withdrawn) ?? null;
  const closedAccounts = db.accounts.filter((a) => a.owner === session && a.status === 'closed');
  const myCards = db.cards.filter((c) => c.owner === session && c.status !== 'terminated');
  const notices = buildNotices(db, session);
  const readAt = (session && db.readAt[session]) || '';
  const unread = notices.filter((n) => n.date > readAt).length;

  return {
    db, user, deviceUser, myAccounts, closedAccounts, myCards, chat, setChat, simulateError, setSimulateError, toastMsg,

    toast: showToast,

    async checkEmail(email: string) {
      await wait(400);
      failIfSimulated();
      return !findUser(email);
    },

    /** 가입용 이메일 인증번호 발송(Mock: 메일 대신 코드를 돌려줘 화면에 보여 준다). 이미 가입된 주소면 거절. */
    async sendSignupCode(email: string) {
      await wait(600);
      failIfSimulated();
      if (!EMAIL_RE.test(email.trim())) throw new BankError('EMAIL', '올바른 이메일 형식이 아니에요.');
      if (findUser(email)) throw new BankError('DUPLICATE_EMAIL', '이미 가입된 이메일이에요.');
      return issueCode(email);
    },

    /** 로그인한 본인의 이메일로 인증번호 발송(거래중지 해제 등) */
    async sendMyCode() {
      await wait(600);
      failIfSimulated();
      return issueCode(ref.current.session ?? '');
    },
    confirmCode,

    async signup(input: { name: string; email: string; password: string; pin: string; marketing: boolean }) {
      await wait(700);
      failIfSimulated();
      const cur = ref.current.db;
      if (findUser(input.email)) throw new BankError('DUPLICATE_EMAIL', '이미 가입된 이메일이에요.');
      if (verifiedEmail.current !== normEmail(input.email)) throw new BankError('EMAIL', '이메일 인증을 먼저 해 주세요.');
      if (!/^\d{6}$/.test(input.pin)) throw new BankError('PIN_FORMAT', '간편비밀번호는 숫자 6자리예요.');
      // 신규 회원에게 체험용 기본 통장 + 가상 잔액 지급
      const id = `acc-${Date.now()}`;
      const number = newAccountNumber(cur.accounts);
      const now = new Date().toISOString();
      commit({
        db: {
          ...cur,
          users: [...cur.users, input],
          accounts: [...cur.accounts, { id, owner: input.email, productId: 'basic', name: '내금고 입출금통장', number, balance: 1_000_000, openedAt: now, status: 'active', limits: DEFAULT_LIMITS }],
          txs: [{ id: `${id}-t0`, accountId: id, date: now, type: 'in', amount: 1_000_000, counterparty: '내금고', memo: '가입 축하 가상머니', balanceAfter: 1_000_000 }, ...cur.txs],
        },
      });
      verifiedEmail.current = null;
    },

    /** 이메일+비밀번호 로그인. 5회 연속 틀리면 잠기고 비밀번호 재설정으로 푼다. */
    async login(email: string, password: string) {
      await wait(600);
      failIfSimulated();
      signIn(email, (u) => u.password === password, '이메일 또는 비밀번호가 일치하지 않아요.');
    },

    /** 이 기기에 기억된 계정의 간편비밀번호 로그인. 오류 횟수는 비밀번호와 함께 센다. */
    async loginWithPin(email: string, pin: string) {
      await wait(500);
      failIfSimulated();
      signIn(email, (u) => u.pin === pin, '간편비밀번호가 맞지 않아요.');
    },

    forgetDevice() {
      try { localStorage.removeItem(DEVICE_KEY); } catch { /* noop */ }
      setDevice(null);
    },

    logout() {
      commit({ session: null });
      setChat(emptyChat);
    },

    /** 비밀번호 재설정 1단계: 가입한 이메일인지 확인하고 그 주소로 인증번호를 보낸다 */
    async startReset(email: string) {
      await wait(500);
      failIfSimulated();
      if (!findUser(email)) throw new BankError('NO_MATCH', '이 이메일로 가입한 회원이 없어요.');
      return issueCode(email);
    },

    async resetPassword(email: string, password: string) {
      await wait(600);
      failIfSimulated();
      const u = findUser(email);
      if (!u || verifiedEmail.current !== normEmail(u.email)) throw new BankError('EMAIL', '이메일 인증을 먼저 해 주세요.');
      patchUser(u.email, { password, locked: false, loginFails: 0 });
      verifiedEmail.current = null;
    },

    async updateName(name: string) {
      await wait(400);
      failIfSimulated();
      patchUser(ref.current.session!, { name });
    },

    async changePassword(current: string, next: string) {
      await wait(500);
      failIfSimulated();
      const me = findUser(ref.current.session ?? '');
      if (!me || me.password !== current) throw new BankError('AUTH', '지금 비밀번호가 맞지 않아요.');
      if (current === next) throw new BankError('SAME', '지금과 다른 비밀번호를 정해 주세요.');
      patchUser(me.email, { password: next });
    },

    /** 화면에서 지금 간편비밀번호를 확인한 뒤 부른다 */
    async changePin(pin: string) {
      await wait(400);
      failIfSimulated();
      if (!/^\d{6}$/.test(pin)) throw new BankError('PIN_FORMAT', '간편비밀번호는 숫자 6자리예요.');
      patchUser(ref.current.session!, { pin });
    },

    idleMinutes,
    setIdleMinutes(m: number) {
      try { localStorage.setItem(IDLE_KEY, String(m)); } catch { /* noop */ }
      setIdleState(m);
    },

    withdrawBlockers: () => withdrawBlockers(ref.current.db, ref.current.session ?? ''),

    /** 회원 탈퇴: 잔액이 남은 계좌·예약 송금이 없어야 한다. 계좌는 해지, 카드는 해지(삭제)된다. */
    async withdraw() {
      await wait(800);
      failIfSimulated();
      const email = ref.current.session ?? '';
      const blockers = withdrawBlockers(ref.current.db, email);
      if (blockers.length) throw new BankError('WITHDRAW_BLOCKED', blockers[0]);
      const cur = ref.current.db;
      const now = new Date().toISOString();
      commit({
        session: null,
        db: {
          ...cur,
          users: cur.users.map((u) => (u.email === email ? { ...u, withdrawn: true } : u)),
          accounts: cur.accounts.map((a) => (a.owner === email && a.status !== 'closed' ? { ...a, status: 'closed', favorite: false, closedAt: now } : a)),
          cards: cur.cards.map((c) => (c.owner === email ? { ...c, status: 'terminated' as const } : c)),
        },
      });
      setChat(emptyChat);
      if (device === email) { try { localStorage.removeItem(DEVICE_KEY); } catch { /* noop */ } setDevice(null); }
    },

    resetDemo() {
      pinFails.current = 0;
      commit({ db: seed() });
      setChat(emptyChat);
    },

    /** 송금 전 간편비밀번호 확인. 5회 틀리면 잠김(데모 초기화로 해제) */
    /** 간편비밀번호 확인. 5회 틀리면 해당 계좌를 거래중지한다(본인인증으로 해제). */
    async verifyPin(pin: string, accountId?: string) {
      await wait(400);
      failIfSimulated();
      const acc = ref.current.db.accounts.find((a) => a.id === accountId);
      if (acc?.status === 'suspended') throw new BankError('PIN_LOCKED', '거래가 중지된 계좌예요. 계좌 관리에서 본인인증으로 해제해 주세요.');
      const me = ref.current.db.users.find((u) => u.email === ref.current.session);
      if (pin !== (me?.pin ?? DEMO_PIN)) {
        pinFails.current += 1;
        if (pinFails.current >= 5) {
          pinFails.current = 0;
          if (acc) {
            const cur = ref.current.db;
            commit({ db: { ...cur, accounts: cur.accounts.map((a) => (a.id === acc.id ? { ...a, status: 'suspended' } : a)) } });
          }
          throw new BankError('PIN_LOCKED', '비밀번호를 5회 틀려 이 계좌의 거래가 중지됐어요. 계좌 관리에서 본인인증으로 해제할 수 있어요.');
        }
        throw new BankError('PIN', `비밀번호가 맞지 않아요. (${pinFails.current}/5)`);
      }
      pinFails.current = 0;
    },

    /** 거래중지 해제: 가입한 이메일로 받은 인증번호 확인 후 해제 */
    async unlockAccount(accountId: string, code: string) {
      await confirmCode(ref.current.session ?? '', code);
      const cur = ref.current.db;
      commit({ db: { ...cur, accounts: cur.accounts.map((a) => (a.id === accountId && a.owner === ref.current.session && a.status === 'suspended' ? { ...a, status: 'active' } : a)) } });
    },

    async setLimits(accountId: string, limits: { daily: number; monthly: number }) {
      await wait(600);
      failIfSimulated();
      const { daily, monthly } = limits;
      if (!(daily > 0 && monthly > 0)) throw new BankError('INVALID_LIMIT', '한도는 0원보다 커야 해요.');
      if (daily > MAX_LIMITS.daily || monthly > MAX_LIMITS.monthly) throw new BankError('INVALID_LIMIT', `최대 1일 ${MAX_LIMITS.daily.toLocaleString()}원, 1달 ${MAX_LIMITS.monthly.toLocaleString()}원까지 정할 수 있어요.`);
      if (daily > monthly) throw new BankError('INVALID_LIMIT', '1일 한도는 1달 한도보다 클 수 없어요.');
      const cur = ref.current.db;
      const acc = cur.accounts.find((a) => a.id === accountId && a.owner === ref.current.session);
      if (!acc || acc.status !== 'active') throw new BankError('INVALID_FROM', '정상 상태인 계좌만 한도를 바꿀 수 있어요.');
      commit({ db: { ...cur, accounts: cur.accounts.map((a) => (a.id === accountId ? { ...a, limits: { daily, monthly } } : a)) } });
    },

    toggleFavorite(accountId: string) {
      const cur = ref.current.db;
      commit({ db: { ...cur, accounts: cur.accounts.map((a) => (a.id === accountId && a.owner === ref.current.session ? { ...a, favorite: !a.favorite } : a)) } });
    },

    async closeAccount(accountId: string) {
      await wait(800);
      failIfSimulated();
      const cur = ref.current.db;
      const acc = cur.accounts.find((a) => a.id === accountId && a.owner === ref.current.session);
      if (!acc) throw new BankError('INVALID_FROM', '계좌를 찾을 수 없어요.');
      const blockers = closeBlockers(cur, accountId);
      if (blockers.length) throw new BankError('CLOSE_BLOCKED', blockers[0].text);
      commit({ db: { ...cur, accounts: cur.accounts.map((a) => (a.id === accountId ? { ...a, status: 'closed', favorite: false, closedAt: new Date().toISOString() } : a)) } });
    },

    /** 받는 계좌 조회 (MVP: 내금고 내부 계좌만) */
    async lookupAccount(no: string) {
      await wait(500);
      failIfSimulated();
      const a = findByNumber(no);
      if (!a) throw new BankError('INVALID_ACCOUNT', '존재하지 않는 계좌예요. 계좌번호를 다시 확인해 주세요.');
      return { name: nameOf(a.owner), number: a.number, mine: a.owner === ref.current.session };
    },

    async transfer(input: TransferInput): Promise<TransferResult> {
      await wait(900);
      failIfSimulated();
      return applyTransfer(input, ref.current.session ?? '', '송금');
    },

    /** 예약 송금 등록. 잔액은 실행 시점에 확인한다. */
    async scheduleTransfer({ fromId, toNumber, amount, runAt }: TransferInput & { runAt: string }) {
      await wait(700);
      failIfSimulated();
      const cur = ref.current.db;
      const owner = ref.current.session ?? '';
      const to = findByNumber(toNumber);
      if (!cur.accounts.some((a) => a.id === fromId && a.owner === owner)) throw new BankError('INVALID_FROM', '출금 계좌를 찾을 수 없어요.');
      if (!to) throw new BankError('INVALID_ACCOUNT', '존재하지 않는 계좌예요. 계좌번호를 다시 확인해 주세요.');
      if (!(amount > 0)) throw new BankError('INVALID_AMOUNT', '송금 금액을 확인해 주세요.');
      if (new Date(runAt).getTime() <= Date.now()) throw new BankError('INVALID_TIME', '예약 시각은 지금 이후로 골라 주세요.');
      const item: Scheduled = { id: `sch-${Date.now()}`, owner, fromId, toNumber: to.number, toName: nameOf(to.owner), amount, runAt, status: 'waiting' };
      commit({ db: { ...cur, scheduled: [...cur.scheduled, item] } });
      return item;
    },

    cancelScheduled(id: string) {
      const cur = ref.current.db;
      commit({ db: { ...cur, scheduled: cur.scheduled.map((x) => (x.id === id && x.status === 'waiting' ? { ...x, status: 'cancelled' } : x)) } });
    },

    notices, unread,
    markNoticesRead() {
      const cur = ref.current.db;
      if (session) commit({ db: { ...cur, readAt: { ...cur.readAt, [session]: new Date().toISOString() } } });
    },

    /** 체크카드 발급: 정상 계좌에 연결, 1일 한도·해외결제 설정 */
    async issueCard(input: { accountId: string; dailyLimit: number; overseas: boolean; theme: CardTheme }) {
      await wait(900);
      failIfSimulated();
      const cur = ref.current.db;
      const acc = cur.accounts.find((a) => a.id === input.accountId && a.owner === ref.current.session);
      if (!acc || acc.status !== 'active') throw new BankError('INVALID_FROM', '정상 상태인 내 계좌에만 카드를 연결할 수 있어요.');
      if (!CARD_LIMITS.includes(input.dailyLimit)) throw new BankError('INVALID_LIMIT', '1일 사용한도를 다시 골라 주세요.');
      const card: Card = { id: `card-${Date.now()}`, owner: acc.owner, name: '내금고 체크카드', last4: newLast4(cur.cards), status: 'active', notify: true, issuedAt: new Date().toISOString(), ...input };
      commit({ db: { ...cur, cards: [...cur.cards, card] } });
      return card;
    },

    /** 카드 설정 변경(1일 한도·해외결제·결제 알림). 해지·분실 카드는 못 바꾼다. */
    async updateCard(id: string, patch: Partial<Pick<Card, 'dailyLimit' | 'overseas' | 'notify'>>) {
      await wait(400);
      failIfSimulated();
      const c = myCard(id);
      if (c.status === 'lost' || c.status === 'terminated') throw new BankError('CARD_STATE', '분실 신고했거나 해지한 카드는 설정을 바꿀 수 없어요.');
      if (patch.dailyLimit !== undefined && !CARD_LIMITS.includes(patch.dailyLimit)) throw new BankError('INVALID_LIMIT', '1일 사용한도를 다시 골라 주세요.');
      patchCard(id, patch);
    },

    /** 일시정지(바로) / 해제. 분실 신고 카드는 해제할 수 없다. */
    async setCardPaused(id: string, paused: boolean) {
      await wait(400);
      failIfSimulated();
      const c = myCard(id);
      if (c.status !== (paused ? 'active' : 'paused')) throw new BankError('CARD_STATE', paused ? '사용 중인 카드만 일시정지할 수 있어요.' : '일시정지한 카드만 다시 쓸 수 있어요.');
      patchCard(id, { status: paused ? 'paused' : 'active' });
    },

    async reportLost(id: string) {
      await wait(600);
      failIfSimulated();
      const c = myCard(id);
      if (c.status === 'lost' || c.status === 'terminated') throw new BankError('CARD_STATE', '이미 분실 신고했거나 해지한 카드예요.');
      patchCard(id, { status: 'lost' });
    },

    /** 재발급: 기존 카드는 해지하고 같은 설정으로 새 번호 카드를 만든다 */
    async reissueCard(id: string) {
      await wait(900);
      failIfSimulated();
      const c = myCard(id);
      if (c.status === 'terminated') throw new BankError('CARD_STATE', '해지한 카드는 재발급할 수 없어요. 새로 발급해 주세요.');
      const acc = ref.current.db.accounts.find((a) => a.id === c.accountId);
      if (acc?.status !== 'active') throw new BankError('INVALID_FROM', '연결 계좌가 정상 상태일 때만 재발급할 수 있어요.');
      const cur = ref.current.db;
      const next: Card = { ...c, id: `card-${Date.now()}`, last4: newLast4(cur.cards), status: 'active', issuedAt: new Date().toISOString() };
      commit({ db: { ...cur, cards: [...cur.cards.map((x) => (x.id === id ? { ...x, status: 'terminated' as const } : x)), next] } });
      return next;
    },

    async terminateCard(id: string) {
      await wait(600);
      failIfSimulated();
      myCard(id);
      patchCard(id, { status: 'terminated' });
    },

    /**
     * 가상 결제(체험용): 카드 상태 → 해외결제 → 1일 한도 → 연결 계좌 상태·잔액 순으로 확인하고,
     * 통과하면 카드 사용내역과 계좌 출금 거래를 함께 남긴다.
     */
    async payWithCard(id: string, input: { merchant: string; category: string; amount: number; overseas: boolean }) {
      await wait(700);
      failIfSimulated();
      const c = myCard(id);
      const cur = ref.current.db;
      if (c.status !== 'active') throw new BankError('CARD_STATE', c.status === 'paused' ? '일시정지한 카드예요. 해제하면 결제할 수 있어요.' : '쓸 수 없는 카드예요.');
      if (input.overseas && !c.overseas) throw new BankError('OVERSEAS', '해외결제가 꺼져 있어 승인되지 않았어요.');
      const used = cardUsedToday(cur, id);
      if (used + input.amount > c.dailyLimit) throw new BankError('CARD_LIMIT', `1일 사용한도를 넘어요. 오늘 ${(c.dailyLimit - used).toLocaleString()}원까지 쓸 수 있어요.`);
      const acc = cur.accounts.find((a) => a.id === c.accountId);
      if (!acc || acc.status !== 'active') throw new BankError('SUSPENDED', '연결 계좌가 거래중지 또는 해지 상태예요.');
      if (input.amount > acc.balance) throw new BankError('INSUFFICIENT', `연결 계좌 잔액이 부족해요. 잔액은 ${acc.balance.toLocaleString()}원이에요.`);
      const now = new Date().toISOString();
      const tid = `ct-${Date.now()}`;
      commit({
        db: {
          ...cur,
          accounts: cur.accounts.map((a) => (a.id === acc.id ? { ...a, balance: a.balance - input.amount } : a)),
          txs: [{ id: `${tid}-tx`, accountId: acc.id, date: now, type: 'out', amount: input.amount, counterparty: input.merchant, memo: `체크카드 ··${c.last4}`, balanceAfter: acc.balance - input.amount }, ...cur.txs],
          cardTxs: [...cur.cardTxs, { id: tid, cardId: id, merchant: input.merchant, category: input.category, date: now, amount: input.amount }],
        },
      });
    },

    /** 받는 계좌 즐겨찾기 */
    toggleFavRecipient(number: string) {
      const me = findUser(ref.current.session ?? '');
      if (!me) return;
      const favs = me.favRecipients ?? [];
      patchUser(me.email, { favRecipients: favs.includes(number) ? favs.filter((n) => n !== number) : [...favs, number] });
    },

    /** 자동이체 등록: 첫 실행일은 시작일 이후 첫 해당일 오전 9시 */
    async createAutoTransfer(input: Pick<AutoTransfer, 'fromId' | 'toNumber' | 'amount' | 'cycle' | 'day' | 'startDate' | 'endDate' | 'memo'>) {
      await wait(800);
      failIfSimulated();
      const cur = ref.current.db;
      const owner = ref.current.session ?? '';
      const from = cur.accounts.find((a) => a.id === input.fromId && a.owner === owner);
      const to = findByNumber(input.toNumber);
      const today = new Date().toLocaleDateString('sv-SE');
      if (!from || from.status !== 'active') throw new BankError('INVALID_FROM', '정상 상태인 내 계좌에서만 자동이체할 수 있어요.');
      if (!to || to.status !== 'active') throw new BankError('INVALID_ACCOUNT', '받는 계좌를 확인해 주세요.');
      if (to.id === from.id) throw new BankError('SAME_ACCOUNT', '출금 계좌와 같은 계좌로는 보낼 수 없어요.');
      if (!Number.isInteger(input.amount) || input.amount <= 0) throw new BankError('INVALID_AMOUNT', '금액을 확인해 주세요.');
      if (input.startDate < today) throw new BankError('INVALID_DATE', '시작일은 오늘 이후로 골라 주세요.');
      if (input.endDate && input.endDate < input.startDate) throw new BankError('INVALID_DATE', '종료일은 시작일보다 뒤여야 해요.');
      const nextRunAt = nextRun(input.cycle, input.day, input.startDate, new Date());
      if (input.endDate && new Date(nextRunAt) > new Date(`${input.endDate}T23:59:59`)) throw new BankError('INVALID_DATE', '기간 안에 실행되는 날이 없어요. 날짜를 다시 골라 주세요.');
      const item: AutoTransfer = { ...input, id: `auto-${Date.now()}`, owner, toNumber: to.number, toName: nameOf(to.owner), nextRunAt, status: 'active', runs: [] };
      commit({ db: { ...cur, autoTransfers: [...cur.autoTransfers, item] } });
      return item;
    },

    stopAutoTransfer(id: string) {
      const cur = ref.current.db;
      commit({ db: { ...cur, autoTransfers: cur.autoTransfers.map((x) => (x.id === id && x.owner === ref.current.session && x.status === 'active' ? { ...x, status: 'stopped' } : x)) } });
    },

    /** 체험용: 다음 회차를 기다리지 않고 지금 한 번 실행해 결과를 남긴다(일정은 그대로) */
    async runAutoNow(id: string) {
      await wait(700);
      failIfSimulated();
      const x = ref.current.db.autoTransfers.find((y) => y.id === id && y.owner === ref.current.session && y.status === 'active');
      if (!x) throw new BankError('NO_AUTO', '진행 중인 자동이체가 아니에요.');
      const run = runAuto(x);
      const cur = ref.current.db;
      commit({ db: { ...cur, autoTransfers: cur.autoTransfers.map((y) => (y.id === id ? { ...y, runs: [...y.runs, run] } : y)) } });
      if (!run.ok) throw new BankError('AUTO_FAILED', run.reason ?? '자동이체를 실행하지 못했어요.');
    },

    async openAccount(productId: string): Promise<Account> {
      await wait(1000);
      failIfSimulated();
      const p = productById(productId);
      const cur = ref.current.db;
      if (!p || !ref.current.session) throw new BankError('INVALID_PRODUCT', '상품 정보를 찾을 수 없어요.');
      const acc: Account = { id: `acc-${Date.now()}`, owner: ref.current.session, productId, name: p.name, number: newAccountNumber(cur.accounts), balance: 0, openedAt: new Date().toISOString(), status: 'active', limits: DEFAULT_LIMITS };
      commit({ db: { ...cur, accounts: [...cur.accounts, acc] } });
      return acc;
    },
  };
}

const DEVICE_KEY = 'naengo-device';
const IDLE_KEY = 'naengo-idle';
export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const normEmail = (e: string) => e.trim().toLowerCase();
function savedDevice(): string | null { try { return localStorage.getItem(DEVICE_KEY); } catch { return null; } }
function savedIdle(): number { try { return Number(localStorage.getItem(IDLE_KEY)) || 10; } catch { return 10; } }

/** 오늘 이 카드로 결제한 금액 */
export function cardUsedToday(db: DB, cardId: string) {
  const n = new Date();
  const day = new Date(n.getFullYear(), n.getMonth(), n.getDate()).toISOString();
  return db.cardTxs.filter((t) => t.cardId === cardId && t.date >= day).reduce((s, t) => s + t.amount, 0);
}
function newLast4(cards: Card[]) {
  let n: string;
  do n = String(Math.floor(Math.random() * 10_000)).padStart(4, '0');
  while (cards.some((c) => c.last4 === n));
  return n;
}

/** 최근·자주 보낸 받는 계좌(내 계좌 제외). 즐겨찾기 먼저, 그다음 최근 순 */
export function recentRecipients(db: DB, email: string) {
  const mine = db.accounts.filter((a) => a.owner === email);
  const ids = new Set(mine.map((a) => a.id));
  const own = new Set(mine.map((a) => a.number));
  const favs = db.users.find((u) => u.email === email)?.favRecipients ?? [];
  const map = new Map<string, { number: string; name: string; count: number; last: string; fav: boolean }>();
  for (const t of db.txs) {
    if (!ids.has(t.accountId) || t.type !== 'out' || !t.counterpartyAccount || own.has(t.counterpartyAccount)) continue;
    const r = map.get(t.counterpartyAccount) ?? { number: t.counterpartyAccount, name: t.counterparty, count: 0, last: '', fav: favs.includes(t.counterpartyAccount) };
    r.count++;
    if (t.date > r.last) { r.last = t.date; r.name = t.counterparty; }
    map.set(t.counterpartyAccount, r);
  }
  return [...map.values()].sort((a, b) => Number(b.fav) - Number(a.fav) || b.last.localeCompare(a.last));
}

/** 탈퇴할 수 없는 이유들 */
export function withdrawBlockers(db: DB, email: string): string[] {
  const out: string[] = [];
  const rich = db.accounts.filter((a) => a.owner === email && a.status !== 'closed' && a.balance > 0);
  if (rich.length) out.push(`잔액이 남은 계좌가 ${rich.length}개 있어요(${rich.map((a) => a.name.replace(/^내금고\s*/, '')).join(', ')}). 잔액을 모두 옮긴 뒤 탈퇴할 수 있어요.`);
  const sch = db.scheduled.filter((x) => x.owner === email && x.status === 'waiting');
  if (sch.length) out.push(`예약 송금 ${sch.length}건이 남아 있어요. 알림 화면에서 취소해 주세요.`);
  const autos = (db.autoTransfers ?? []).filter((x) => x.owner === email && x.status === 'active');
  if (autos.length) out.push(`자동이체 ${autos.length}건이 남아 있어요. 자동이체 화면에서 해지해 주세요.`);
  return out;
}

/** 오늘·이번 달 이체한도 사용액. 내 계좌끼리 옮긴 돈은 빼고 센다. */
export function usageOf(db: DB, accountId: string) {
  const acc = db.accounts.find((a) => a.id === accountId);
  const own = new Set(db.accounts.filter((a) => a.owner === acc?.owner).map((a) => a.number));
  const now = new Date();
  const day = new Date(now.getFullYear(), now.getMonth(), now.getDate()).toISOString();
  const month = new Date(now.getFullYear(), now.getMonth(), 1).toISOString();
  let today = 0, m = 0;
  for (const t of db.txs) {
    if (t.accountId !== accountId || t.type !== 'out' || (t.counterpartyAccount && own.has(t.counterpartyAccount))) continue;
    if (t.date >= month) m += t.amount;
    if (t.date >= day) today += t.amount;
  }
  return { today, month: m };
}

export type CloseBlocker = { kind: 'balance' | 'card' | 'scheduled' | 'status'; text: string };
/** 해지할 수 없는 이유들. 비어 있으면 해지 가능. */
export function closeBlockers(db: DB, accountId: string): CloseBlocker[] {
  const acc = db.accounts.find((a) => a.id === accountId);
  if (!acc) return [];
  const out: CloseBlocker[] = [];
  if (acc.status === 'suspended') out.push({ kind: 'status', text: '거래가 중지된 계좌예요. 먼저 본인인증으로 해제해 주세요.' });
  if (acc.balance > 0) out.push({ kind: 'balance', text: `잔액 ${acc.balance.toLocaleString()}원이 남아 있어요. 다른 계좌로 옮긴 뒤 해지할 수 있어요.` });
  const cards = db.cards.filter((c) => c.accountId === accountId && c.status !== 'terminated');
  if (cards.length) out.push({ kind: 'card', text: `체크카드 ${cards.length}장이 연결돼 있어요(${cards.map((c) => c.name).join(', ')}). 카드를 해지하면 계좌도 해지할 수 있어요.` });
  const sch = db.scheduled.filter((x) => x.fromId === accountId && x.status === 'waiting');
  const autos = (db.autoTransfers ?? []).filter((x) => x.fromId === accountId && x.status === 'active');
  if (sch.length || autos.length) out.push({ kind: 'scheduled', text: `이 계좌에서 나갈 ${[sch.length && `예약 송금 ${sch.length}건`, autos.length && `자동이체 ${autos.length}건`].filter(Boolean).join(', ')}이 있어요. 먼저 해지하거나 취소해 주세요.` });
  return out;
}

const won = (n: number) => `${n.toLocaleString('ko-KR')}원`;
const MONTH = 30 * 86_400_000;

const inTitle = (t: Tx) =>
  t.counterparty === '내금고' ? `${t.memo ?? '입금'} ${won(t.amount)}이 들어왔어요`
  : /^[가-힣]{2,4}$/.test(t.counterparty) ? `${t.counterparty}님이 ${won(t.amount)}을 보냈어요`
  : `${t.counterparty}에서 ${won(t.amount)}이 들어왔어요`;

/** 최근 30일 입금(내 계좌끼리 옮긴 돈 제외)과 예약 송금 결과를 최신순으로 */
function buildNotices(db: DB, session: string | null): Notice[] {
  if (!session) return [];
  const mine = db.accounts.filter((a) => a.owner === session);
  const ids = new Set(mine.map((a) => a.id));
  const numbers = new Set(mine.map((a) => a.number));
  const since = new Date(Date.now() - MONTH).toISOString();
  const nameOf = (id: string) => mine.find((a) => a.id === id)?.name ?? '';
  const ins: Notice[] = db.txs
    .filter((t) => t.type === 'in' && ids.has(t.accountId) && t.date >= since && !(t.counterpartyAccount && numbers.has(t.counterpartyAccount)))
    .map((t) => ({ id: t.id, date: t.date, kind: 'in', title: inTitle(t), sub: `${nameOf(t.accountId)}${t.memo ? ` · ${t.memo}` : ''}`, to: `/accounts/${t.accountId}` }));
  const sch: Notice[] = db.scheduled
    .filter((x) => x.owner === session && (x.status === 'done' || x.status === 'failed') && (x.doneAt ?? '') >= since)
    .map((x) => x.status === 'done'
      ? { id: x.id, date: x.doneAt!, kind: 'scheduled', title: `예약한 ${won(x.amount)}을 ${x.toName}님에게 보냈어요`, sub: nameOf(x.fromId), to: `/accounts/${x.fromId}` }
      : { id: x.id, date: x.doneAt!, kind: 'failed', title: `${x.toName}님에게 예약한 ${won(x.amount)}을 보내지 못했어요`, sub: x.reason ?? '', to: `/transfer?from=${x.fromId}` });
  const notifyCards = db.cards.filter((c) => c.owner === session && c.notify);
  const pays: Notice[] = db.cardTxs
    .filter((t) => t.date >= since && notifyCards.some((c) => c.id === t.cardId))
    .map((t) => {
      const c = notifyCards.find((x) => x.id === t.cardId)!;
      return { id: t.id, date: t.date, kind: 'card', title: `${t.merchant}에서 ${won(t.amount)}을 결제했어요`, sub: `${c.name} ··${c.last4}`, to: `/cards/${c.id}` };
    });
  const autoNotices: Notice[] = (db.autoTransfers ?? []).filter((x) => x.owner === session).flatMap((x) => {
    const ownAcc = mine.find((a) => a.number === x.toNumber);
    const to = ownAcc ? `${ownAcc.name}에` : `${x.toName}님에게`;
    return x.runs.filter((r) => r.at >= since).map((r): Notice => r.ok
      ? { id: `${x.id}-${r.at}`, date: r.at, kind: 'auto', title: `자동이체로 ${to} ${won(x.amount)}을 보냈어요`, sub: `${nameOf(x.fromId)}${x.memo ? ` · ${x.memo}` : ''}`, to: '/auto-transfers' }
      : { id: `${x.id}-${r.at}`, date: r.at, kind: 'failed', title: `자동이체 ${won(x.amount)}을 보내지 못했어요`, sub: r.reason ?? '', to: '/auto-transfers' });
  });
  return [...ins, ...sch, ...pays, ...autoNotices].sort((a, b) => b.date.localeCompare(a.date));
}

function newAccountNumber(existing: Account[]) {
  let n: string;
  do n = `110-${String(Math.floor(100 + Math.random() * 900))}-${String(Math.floor(Math.random() * 1e6)).padStart(6, '0')}`;
  while (existing.some((a) => a.number === n));
  return n;
}

type Bank = ReturnType<typeof useBankState>;
const Ctx = createContext<Bank | null>(null);

export function BankProvider({ children }: { children: ReactNode }) {
  return <Ctx.Provider value={useBankState()}>{children}</Ctx.Provider>;
}

export function useBank() {
  const v = useContext(Ctx);
  if (!v) throw new Error('BankProvider missing');
  return v;
}

/** 화면 단위 Mock API 로딩/오류 상태 */
export function useLoad(deps: unknown[] = [], ms = 450) {
  const { simulateError } = useBank();
  const [state, setState] = useState<'loading' | 'error' | 'ready'>('loading');
  const [n, setN] = useState(0);
  useEffect(() => {
    setState('loading');
    const t = setTimeout(() => setState(simulateError ? 'error' : 'ready'), ms);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [n, ...deps]);
  return { state, retry: () => setN((x) => x + 1) };
}
