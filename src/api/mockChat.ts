// 시나리오 기반 Mock 응답. 키워드 규칙으로 의도를 고르고, 송금은 슬롯(출금계좌→받는계좌→금액)을 채웁니다.
// ponytail: 정규식 의도 분류 — 실제 자연어 이해는 LangGraph 서버로 교체.
import { products, productById, type Account } from '../data/mock';
import { won, maskAccount, fmtDateTime } from '../lib/format';
import type { BankSnapshot, Block, ChatContext, ChatResponse, Period, TransferDraft } from './chat';

const text = (t: string): Block => ({ kind: 'text', text: t });
const reply = (context: ChatContext, ...blocks: Block[]): ChatResponse => ({ context, blocks });

export const SUGGESTIONS = ['내 계좌 잔액 알려줘', '이번 달 카드 사용내역 보여줘', '입출금통장 추천해 줘', '송금하고 싶어', '이번 달 커피에 얼마 썼지?'];
const suggestionChoices: Block = { kind: 'choices', options: SUGGESTIONS.map((s) => ({ label: s, value: s })) };

export function parseAmount(t: string, allowPlain = false): number | null {
  const s = t.replace(/[,\s]/g, '');
  let m = s.match(/(\d+(?:\.\d+)?)만(?:(\d+)천)?원?/);
  if (m) return Math.round(parseFloat(m[1]) * 10000) + (m[2] ? Number(m[2]) * 1000 : 0);
  if ((m = s.match(/(\d+)천원?/))) return Number(m[1]) * 1000;
  if ((m = s.match(/(\d+)원/))) return Number(m[1]);
  if (allowPlain && (m = s.match(/^(\d+)$/))) return Number(m[1]);
  return null;
}

/**
 * "1분 뒤", "2시간 후", "내일 9시", "모레 오후 3시 반", "11월 10일", "3일 뒤 오전 10시" → 보낼 시각.
 * 날짜만 있으면 오전 9시, 시각만 있고 이미 지났으면 다음 날. 못 찾으면 null.
 */
export function parseWhen(t: string, now = new Date()): { at: Date; rest: string } | null {
  let m = t.match(/(\d+)\s*(분|시간)\s*(뒤|후|있다가)에?/);
  if (m) return { at: new Date(now.getTime() + Number(m[1]) * (m[2] === '분' ? 60_000 : 3_600_000)), rest: t.replace(m[0], ' ') };
  let rest = t;
  const at = new Date(now);
  let day = false, time = false;
  if ((m = rest.match(/(\d{1,2})\s*월\s*(\d{1,2})\s*일에?/))) {
    at.setMonth(Number(m[1]) - 1, Number(m[2]));
    if (at < now) at.setFullYear(at.getFullYear() + 1);
    day = true; rest = rest.replace(m[0], ' ');
  } else if ((m = rest.match(/(\d+)\s*일\s*(뒤|후)에?/))) {
    at.setDate(at.getDate() + Number(m[1])); day = true; rest = rest.replace(m[0], ' ');
  } else if ((m = rest.match(/오늘|내일|모레/))) {
    at.setDate(at.getDate() + ({ 오늘: 0, 내일: 1, 모레: 2 } as Record<string, number>)[m[0]]); day = true; rest = rest.replace(m[0], ' ');
  }
  if ((m = rest.match(/(오전|오후|아침|저녁|밤)?\s*(\d{1,2})\s*시\s*(?:(\d{1,2})\s*분|(반))?에?/))) {
    let h = Number(m[2]);
    if (/오후|저녁|밤/.test(m[1] ?? '') && h < 12) h += 12;
    at.setHours(h, m[4] ? 30 : Number(m[3] ?? 0), 0, 0);
    time = true; rest = rest.replace(m[0], ' ');
  }
  if (!day && !time) return null;
  if (!time) at.setHours(9, 0, 0, 0);
  else at.setSeconds(0, 0);
  if (!day && at <= now) at.setDate(at.getDate() + 1);
  return { at, rest };
}

const ORD: Record<string, number> = { 첫: 0, 두: 1, 세: 2, 네: 3, 다섯: 4 };
function ordinal(t: string): number | null {
  const m = t.match(/(첫|두|세|네|다섯)\s*번째|(\d)\s*번/);
  if (!m) return null;
  return m[1] ? ORD[m[1]] : Number(m[2]) - 1;
}

/** "입출금통장", "파킹" 등으로 내 계좌 찾기 (긴 이름 우선) */
function matchAccount(t: string, accounts: Account[]) {
  const core = (a: Account) => a.name.replace(/^내금고\s*/, '');
  return [...accounts]
    .sort((a, b) => core(b).length - core(a).length)
    .find((a) => t.includes(core(a)) || t.includes(core(a).replace(/통장$/, '')) || t.includes(a.number.slice(-4)));
}

function matchProduct(t: string) {
  return [...products].sort((a, b) => b.name.length - a.name.length).find((p) => t.includes(p.name.replace(/^내금고\s*/, '')));
}

const isThisMonth = (iso: string) => {
  const d = new Date(iso), n = new Date();
  return d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth();
};

// ── 의도별 응답 ─────────────────────────────────────────
function balance(ctx: ChatContext, s: BankSnapshot): ChatResponse {
  if (!s.accounts.length) return reply(ctx, text('아직 보유한 계좌가 없어요. 통장을 먼저 만들어 볼까요?'), { kind: 'links', links: [{ label: '통장 만들기', to: '/products' }] });
  const total = s.accounts.reduce((a, b) => a + b.balance, 0);
  return reply(
    ctx,
    text(`현재 보유한 계좌는 ${s.accounts.length}개이고, 총 잔액은 ${won(total)}이에요.`),
    { kind: 'accounts', items: s.accounts.map(({ id, name, number, balance }) => ({ id, name, number, balance })) },
    { kind: 'links', links: [{ label: '송금하기', to: '/transfer' }, { label: '홈에서 보기', to: '/' }] },
  );
}

function transactions(t: string, ctx: ChatContext, s: BankSnapshot): ChatResponse {
  const acc = matchAccount(t, s.accounts);
  const ids = acc ? [acc.id] : s.accounts.map((a) => a.id);
  const items = s.txs.filter((x) => ids.includes(x.accountId)).sort((a, b) => b.date.localeCompare(a.date)).slice(0, 5);
  if (!items.length) return reply(ctx, text('조회된 거래내역이 없어요.'));
  return reply(
    ctx,
    text(acc ? `${acc.name}의 최근 거래내역 ${items.length}건이에요.` : `전체 계좌의 최근 거래내역 ${items.length}건이에요.`),
    { kind: 'transactions', title: acc?.name ?? '전체 계좌', items: items.map(({ id, accountId, date, type, amount, counterparty }) => ({ id, accountId, date, type, amount, counterparty })) },
    { kind: 'links', links: [{ label: '전체 거래내역 보기', to: `/accounts/${acc?.id ?? items[0].accountId}` }] },
  );
}

function cardUsage(ctx: ChatContext, s: BankSnapshot): ChatResponse {
  if (!s.cards.length) return reply(ctx, text('보유한 카드가 없어요.'));
  const month = `${new Date().getMonth() + 1}월`;
  const mine = s.cardTxs.filter((x) => s.cards.some((c) => c.id === x.cardId) && isThisMonth(x.date)).sort((a, b) => b.date.localeCompare(a.date));
  const cards = s.cards.map((c) => {
    const list = mine.filter((x) => x.cardId === c.id);
    return { id: c.id, name: c.name, last4: c.last4, total: list.reduce((a, b) => a + b.amount, 0), count: list.length };
  });
  const total = cards.reduce((a, b) => a + b.total, 0);
  if (!mine.length) return reply(ctx, text(`${month}에는 아직 카드 사용내역이 없어요.`), { kind: 'links', links: [{ label: '카드 사용내역 보기', to: `/cards/${s.cards[0].id}` }] });
  return reply(
    ctx,
    text(`${month} 카드 사용 금액은 총 ${won(total)}이에요. 최근 사용내역을 함께 보여드릴게요.`),
    { kind: 'cardUsage', month, total, cards, items: mine.slice(0, 5).map(({ id, merchant, date, amount }) => ({ id, merchant, date, amount })) },
    { kind: 'links', links: cards.filter((c) => c.count).map((c) => ({ label: `${c.name} 내역 보기`, to: `/cards/${c.id}` })) },
  );
}

function recommend(t: string, ctx: ChatContext): ChatResponse {
  const sorted = [...products].sort((a, b) => b.rate - a.rate).slice(0, 3);
  const top = sorted[0];
  const intro = /가장|제일|최고|높/.test(t)
    ? `등록된 입출금통장 ${products.length}개를 금리 기준으로 비교했어요. 금리가 가장 높은 상품은 ${top.name}(최고 연 ${top.rate.toFixed(1)}%)이에요.`
    : '등록된 입출금통장 중 금리가 높은 순서로 3개를 추천해 드릴게요.';
  return reply(
    { ...ctx, lastProductIds: sorted.map((p) => p.id) },
    text(intro),
    { kind: 'products', productIds: sorted.map((p) => p.id) },
    text('표시된 금리와 조건은 예시 데이터예요. 번호로 이어서 물어볼 수 있어요. (예: 두 번째 상품 가입 조건 알려줘)'),
  );
}

const FIELD_LABEL = { conditions: '가입 대상과 조건', benefits: '주요 혜택', rate: '적용 금리', notices: '유의사항' } as const;
function productInfo(t: string, ctx: ChatContext, productId: string, idx: number | null): ChatResponse {
  const p = productById(productId)!;
  const field = /혜택/.test(t) ? 'benefits' : /금리|이율|이자/.test(t) ? 'rate' : /유의|주의/.test(t) ? 'notices' : 'conditions';
  const who = idx !== null ? `앞서 안내한 ${idx + 1}번째 상품인 ${p.name}` : p.name;
  return reply(
    ctx,
    text(`${who}의 ${FIELD_LABEL[field]}이에요.`),
    { kind: 'productInfo', productId, field },
    { kind: 'links', links: [{ label: '상품 상세 보기', to: `/products/${p.id}` }, { label: '이 상품으로 계좌 개설', to: `/products/${p.id}/open` }] },
  );
}

function openGuide(t: string, ctx: ChatContext): ChatResponse {
  const idx = ordinal(t);
  const p = (idx !== null && ctx.lastProductIds?.[idx] && productById(ctx.lastProductIds[idx])) || matchProduct(t);
  const msg = text('계좌 개설은 약관 동의와 최종 확인이 필요해서 개설 화면에서 직접 진행해요.');
  if (p) return reply(ctx, msg, { kind: 'links', links: [{ label: `${p.name} 개설하기`, to: `/products/${p.id}/open` }] });
  return reply(ctx, msg, text('어떤 통장을 만들지 상품 목록에서 골라 주세요.'), { kind: 'links', links: [{ label: '통장 상품 보기', to: '/products' }] });
}

// ── 송금 슬롯 채우기 ─────────────────────────────────────
function transferFlow(t: string, ctx: ChatContext, s: BankSnapshot, start: boolean): ChatResponse & { filled: boolean } {
  const awaiting = ctx.pending?.awaiting;
  const d: TransferDraft = { ...ctx.pending?.draft };
  let filled = false;
  const notes: Block[] = start ? [text('송금을 도와드릴게요.')] : [];

  const when = parseWhen(t);
  if (when) {
    t = when.rest;
    if (when.at.getTime() <= Date.now()) notes.push(text('이미 지난 시각이에요. 보낼 시각을 다시 알려 주세요.'));
    else { d.runAt = when.at.toISOString(); d.schedule = true; filled = true; }
  } else if (/예약/.test(t)) { d.schedule = true; filled = true; }
  else if (awaiting === 'when' && /지금|바로|즉시/.test(t)) { d.schedule = false; d.runAt = undefined; filled = true; }

  const amount = parseAmount(t, awaiting === 'amount');
  if (amount) { d.amount = amount; filled = true; }

  const num = t.match(/(\d{3})-?(\d{3})-?(\d{6})/);
  const mine = matchAccount(t.replace(num?.[0] ?? '', ''), s.accounts);
  if (num) {
    d.toNumber = `${num[1]}-${num[2]}-${num[3]}`;
    d.toName = undefined;
    const claimed = t.match(/([가-힣]{2,4})\s*(?:님)?\s*[,，]?\s*(?:에게|한테)?\s*\d/)?.[1];
    d.claimedName = claimed && !/에서$|통장|계좌/.test(claimed) ? claimed : undefined; // "입출금통장에서 123-…" 오인 방지
    if (mine) d.fromId = mine.id; // 한 문장에 출금 계좌까지 말한 경우
    filled = true;
  } else if (mine && awaiting === 'to') {
    d.toNumber = mine.number; d.toName = undefined; d.claimedName = undefined;
    filled = true;
  } else {
    if (mine) { d.fromId = mine.id; filled = true; } // "입출금통장에서 김민지에게…"처럼 이름이 같이 올 수 있다
    const name = t.match(/([가-힣]{2,4})(?:님)?(?:에게|한테)/)?.[1] ?? (awaiting === 'to' && !mine ? t.trim() : undefined);
    const known = name && s.recipients.find((r) => r.name === name);
    if (known) { d.toNumber = known.number; d.toName = undefined; d.claimedName = known.name; filled = true; }
  }

  const from = s.accounts.find((a) => a.id === d.fromId);
  if (d.toNumber && !d.toName) {
    const found = s.lookup(d.toNumber);
    if (!found) notes.push(text(`${d.toNumber}은(는) 존재하지 않는 계좌예요. MVP에서는 내금고 계좌로만 송금할 수 있어요.`));
    else if (from && found.number === from.number) notes.push(text('출금 계좌와 같은 계좌로는 보낼 수 없어요.'));
    else if (d.claimedName && d.claimedName !== found.name) notes.push(text(`입력하신 이름(${d.claimedName})과 예금주가 일치하지 않아요. 계좌번호를 다시 확인해 주세요.`));
    else d.toName = found.name;
    if (!d.toName) { d.toNumber = undefined; d.claimedName = undefined; }
  }
  if (from && d.amount && !d.runAt && !d.schedule && d.amount > from.balance) {
    notes.push(text(`잔액이 부족해요. ${from.name}의 출금 가능 금액은 ${won(from.balance)}이에요.`));
    d.amount = undefined;
  }

  const ask = (awaitingNext: 'from' | 'to' | 'amount' | 'when', ...blocks: Block[]) =>
    ({ filled, context: { ...ctx, pending: { type: 'transfer' as const, awaiting: awaitingNext, draft: d } }, blocks: [...notes, ...blocks] });

  if (!from) {
    if (!s.accounts.length) return { filled, context: { ...ctx, pending: undefined }, blocks: [text('송금할 수 있는 계좌가 없어요. 통장을 먼저 만들어 주세요.'), { kind: 'links', links: [{ label: '통장 만들기', to: '/products' }] }] };
    return ask('from', text(d.amount ? `${won(d.amount)}을 어느 계좌에서 보낼까요?` : '어느 계좌에서 보낼까요?'), {
      kind: 'choices', options: s.accounts.map((a) => ({ label: `${a.name} · ${won(a.balance)}`, value: `${a.name}에서` })),
    });
  }
  if (!d.toNumber || !d.toName) {
    return ask('to', text('누구에게 보낼까요? 받는 분 이름과 계좌번호를 알려 주세요. (예: 홍길동, 123-4567-8901)'), {
      kind: 'choices', options: s.recipients.slice(0, 3).map((r) => ({ label: `${r.name} · ${maskAccount(r.number)}`, value: `${r.name}, ${r.number}` })),
    });
  }
  if (!d.amount) {
    return ask('amount', text(`${d.toName}님에게 얼마를 보낼까요? 출금 가능 금액은 ${won(from.balance)}이에요.`), {
      kind: 'choices', options: [10000, 30000, 50000, 100000].filter((v) => v <= from.balance).map((v) => ({ label: won(v), value: `${v / 10000}만원` })),
    });
  }
  if (d.schedule && !d.runAt) {
    return ask('when', text(`${d.toName}님에게 ${won(d.amount)}을 언제 보낼까요? (예: 내일 오전 9시, 11월 10일 오후 3시)`), {
      kind: 'choices', options: ['1분 뒤', '내일 오전 9시', '모레 오전 9시', '지금 바로'].map((v) => ({ label: v, value: v })),
    });
  }
  return {
    filled,
    context: { ...ctx, pending: undefined },
    blocks: [
      ...notes,
      text(d.runAt
        ? `${fmtDateTime(d.runAt)}에 보내도록 예약할게요. 아래 예약하기 버튼을 눌러야 예약돼요. 잔액은 보내는 시점에 확인해요.`
        : '송금 정보를 확인해 주세요. 아래 송금하기 버튼을 눌러야 실제로 송금돼요.'),
      { kind: 'transferConfirm', status: 'pending', draft: { fromId: from.id, toNumber: d.toNumber, toName: d.toName, amount: d.amount, ...(d.runAt && { runAt: d.runAt }) } },
    ],
  };
}

// ── 소비 분석 ───────────────────────────────────────────
// ponytail: 체크카드 결제의 카테고리만 본다. 계좌 이체 지출은 분류 정보가 없어 제외.
const CATEGORIES: [RegExp, string][] = [
  [/커피|카페/, '카페'], [/식비|밥|음식|식사|점심|저녁|외식/, '식비'], [/쇼핑|온라인/, '쇼핑'],
  [/교통|버스|지하철|택시/, '교통'], [/편의점/, '편의점'], [/문화|영화|책|도서/, '문화'],
  [/운동|헬스/, '운동'], [/장보기|마트/, '장보기'], [/병원|약국|의료/, '의료'],
];
const matchCategory = (t: string) => CATEGORIES.find(([re]) => re.test(t))?.[1];

export function parsePeriod(t: string): Period | null {
  if (/지난\s?달|저번\s?달|전\s?달/.test(t)) return 'last-month';
  if (/이번\s?주|금주/.test(t)) return 'this-week';
  if (/오늘/.test(t)) return 'today';
  if (/이번\s?달|이달/.test(t)) return 'this-month';
  return null;
}

/** [from, to) 범위 */
export function periodRange(p: Period, now = new Date()) {
  const y = now.getFullYear(), m = now.getMonth(), d = now.getDate();
  switch (p) {
    case 'this-month': return { from: new Date(y, m, 1), to: new Date(y, m + 1, 1), label: '이번 달' };
    case 'last-month': return { from: new Date(y, m - 1, 1), to: new Date(y, m, 1), label: '지난달' };
    case 'today': return { from: new Date(y, m, d), to: new Date(y, m, d + 1), label: '오늘' };
    case 'this-week': {
      const from = new Date(y, m, d - ((now.getDay() + 6) % 7));
      return { from, to: new Date(from.getFullYear(), from.getMonth(), from.getDate() + 7), label: '이번 주' };
    }
  }
}

function spending(ctx: ChatContext, s: BankSnapshot, period: Period, category?: string): ChatResponse {
  const next = { ...ctx, lastSpending: { category, period } };
  if (!s.cards.length) return reply(next, text('보유한 카드가 없어서 소비 내역을 분석할 수 없어요.'));
  const mine = s.cardTxs.filter((x) => s.cards.some((c) => c.id === x.cardId) && (!category || x.category === category));
  const pick = (p: Period) => {
    const r = periodRange(p);
    return mine.filter((x) => { const d = new Date(x.date); return d >= r.from && d < r.to; });
  };
  const r = periodRange(period);
  const list = pick(period).sort((a, b) => b.date.localeCompare(a.date));
  const total = list.reduce((a, b) => a + b.amount, 0);
  const prevTotal = period === 'this-month' ? pick('last-month').reduce((a, b) => a + b.amount, 0) : null;
  const compare = prevTotal !== null && (total || prevTotal) ? { label: '지난달', diff: total - prevTotal } : undefined;
  const items = list.slice(0, 5).map(({ id, merchant, date, amount }) => ({ id, merchant, date, amount }));
  const cardWithItems = s.cards.find((c) => list.some((x) => x.cardId === c.id)) ?? s.cards[0];
  const links: Block = { kind: 'links', links: [{ label: '카드 사용내역 보기', to: `/cards/${cardWithItems.id}` }] };

  if (category) {
    if (!list.length) return reply(next, text(`${r.label}에는 ${category} 결제가 없어요.`), links);
    return reply(
      next,
      text(`${r.label} ${category}에 ${won(total)} 썼어요. 체크카드 결제 ${list.length}건 기준이에요.`),
      { kind: 'spending', title: `${r.label} ${category}`, total, count: list.length, compare, items },
      links,
    );
  }
  if (!list.length) return reply(next, text(`${r.label}에는 체크카드 결제가 없어요.`), links);
  const byCat = new Map<string, number>();
  for (const x of list) byCat.set(x.category, (byCat.get(x.category) ?? 0) + x.amount);
  const breakdown = [...byCat].map(([cat, sum]) => ({ category: cat, total: sum })).sort((a, b) => b.total - a.total);
  return reply(
    next,
    text(`${r.label} 체크카드로 총 ${won(total)} 썼어요. ${breakdown[0].category}에 가장 많이 썼어요(${won(breakdown[0].total)}).`),
    { kind: 'spending', title: `${r.label} 소비`, total, count: list.length, compare, breakdown, items },
    links,
  );
}

function answer(t: string, ctx: ChatContext, s: BankSnapshot): ChatResponse | null {
  const period = parsePeriod(t);
  const cat = matchCategory(t);
  if (/(얼마|몇).*(썼|쓴|나갔|지출|소비|결제)|소비|지출|썼(어|지|나|니)|쓴\s?(돈|곳)/.test(t)) {
    return spending(ctx, s, period ?? 'this-month', cat);
  }
  // 후속 질문: "그럼 지난달은?", "식비는?"
  if (ctx.lastSpending && (period || cat) && /(은|는)\s*\??$/.test(t)) {
    return spending(ctx, s, period ?? ctx.lastSpending.period, cat ?? ctx.lastSpending.category);
  }
  const idx = ordinal(t);
  if (/개설|만들/.test(t)) return openGuide(t, ctx);
  if (idx !== null && ctx.lastProductIds?.[idx]) return productInfo(t, ctx, ctx.lastProductIds[idx], idx);
  if (idx !== null && /상품|통장|조건|혜택|금리/.test(t)) return reply(ctx, text('어떤 상품 목록을 기준으로 할지 모르겠어요. 먼저 상품을 추천받아 볼까요?'), { kind: 'choices', options: [{ label: '입출금통장 추천해 줘', value: '입출금통장 추천해 줘' }] });
  if (/카드/.test(t)) return cardUsage(ctx, s);
  const p = matchProduct(t);
  if (p && /조건|대상|혜택|금리|이율|유의|알려|뭐/.test(t) && !/추천|가장|제일|비교/.test(t)) return productInfo(t, ctx, p.id, null);
  if (/통장|상품|금리|이율|추천/.test(t) && !/잔액|잔고/.test(t)) return recommend(t, ctx);
  if (/거래|내역/.test(t)) return transactions(t, ctx, s);
  if (/잔액|잔고|얼마.*있|계좌/.test(t)) return balance(ctx, s);
  return null;
}

function scheduledList(ctx: ChatContext, s: BankSnapshot): ChatResponse {
  const items = [...s.scheduled].sort((a, b) => a.runAt.localeCompare(b.runAt));
  if (!items.length) return reply(ctx, text('예약된 송금이 없어요. "내일 오전 9시에 홍길동에게 3만원 보내줘"처럼 말하면 예약할 수 있어요.'));
  return reply(ctx,
    text(`보낼 예정인 송금이 ${items.length}건 있어요. 취소는 알림 화면에서 할 수 있어요.`),
    { kind: 'scheduledList', items: items.map((x) => ({ id: x.id, toName: x.toName, amount: x.amount, runAt: x.runAt, fromName: s.accounts.find((a) => a.id === x.fromId)?.name ?? '' })) },
    { kind: 'links', links: [{ label: '알림에서 관리하기', to: '/notifications' }] },
  );
}

export function mockRespond(message: string, ctx: ChatContext, s: BankSnapshot): ChatResponse {
  const t = message.trim();

  if (ctx.pending) {
    if (/취소|그만|안\s?할래/.test(t)) return reply({ ...ctx, pending: undefined }, text('송금 요청을 취소했어요. 다른 도움이 필요하면 말씀해 주세요.'));
    const r = transferFlow(t, ctx, s, false);
    if (r.filled) return r;
    const other = answer(t, { ...ctx, pending: undefined }, s);
    if (other) return { context: { ...other.context, pending: ctx.pending }, blocks: [...other.blocks, text("진행 중이던 송금은 이어서 할 수 있어요. 그만두려면 '취소'라고 말씀해 주세요.")] };
    return r;
  }

  if (/예약/.test(t) && /내역|목록|뭐|있|보여|확인|알려/.test(t) && !parseAmount(t)) return scheduledList(ctx, s);
  if ((/송금|보내|이체/.test(t) && !/내역/.test(t)) || (/예약/.test(t) && parseAmount(t))) return transferFlow(t, ctx, s, true);

  const r = answer(t, ctx, s);
  if (r) return r;
  if (/안녕|반가|하이|hello/i.test(t)) return reply(ctx, text(`안녕하세요, ${s.userName}님! 계좌 조회, 송금, 상품 안내를 도와드릴 수 있어요.`), suggestionChoices);
  return reply(ctx, text('아직 이해하지 못한 요청이에요. 이런 요청을 도와드릴 수 있어요.'), suggestionChoices);
}
