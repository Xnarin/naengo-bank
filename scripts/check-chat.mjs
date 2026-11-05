// 챗봇 시나리오 회귀 체크: node scripts/check-chat.mjs
import assert from 'node:assert/strict';
import { createServer } from 'vite';

const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' });
const { mockRespond, parseAmount, parsePeriod, periodRange, parseWhen } = await vite.ssrLoadModule('/src/api/mockChat.ts');
const { seed } = await vite.ssrLoadModule('/src/data/mock.ts');

assert.equal(parseAmount('3만원 보내줘'), 30000);
assert.equal(parseAmount('3만 5천원'), 35000);
assert.equal(parseAmount('12,000원'), 12000);
assert.equal(parseAmount('홍길동, 123-456-789012'), null);
assert.equal(parseAmount('5000', true), 5000);

const db = seed();
const mine = db.accounts.filter((a) => a.owner === 'demo@naengo.bank');
const snap = {
  userName: '이도윤', accounts: mine, txs: db.txs, cards: db.cards, cardTxs: db.cardTxs, simulateError: false,
  recipients: [{ name: '홍길동', number: '123-456-789012' }],
  lookup: (n) => { const a = db.accounts.find((x) => x.number === n); return a ? { name: db.users.find((u) => u.email === a.owner).name, number: a.number } : null; },
};
snap.scheduled = [];
const kinds = (r) => r.blocks.map((b) => b.kind);

// 예시 A: 잔액
assert.ok(kinds(mockRespond('내 계좌 잔액 알려줘', {}, snap)).includes('accounts'));
assert.ok(kinds(mockRespond('내 계좌 거래내역 보여줘', {}, snap)).includes('transactions'));

// 예시 B: 송금 슬롯
let r = mockRespond('3만원 보내줘', {}, snap);
assert.equal(r.context.pending.awaiting, 'from');
r = mockRespond('내 입출금통장에서', r.context, snap);
assert.equal(r.context.pending.awaiting, 'to');
assert.equal(r.context.pending.draft.fromId, 'acc-1');
r = mockRespond('홍길동, 123-456-789012', r.context, snap);
const confirm = r.blocks.find((b) => b.kind === 'transferConfirm');
assert.deepEqual(confirm.draft, { fromId: 'acc-1', toNumber: '123-456-789012', toName: '홍길동', amount: 30000 });
assert.equal(r.context.pending, undefined);

// 실패: 없는 계좌, 이름 불일치, 잔액 초과
r = mockRespond('송금하고 싶어', {}, snap);
r = mockRespond('생활비통장에서', r.context, snap);
r = mockRespond('999-999-999999', r.context, snap);
assert.equal(r.context.pending.awaiting, 'to');
r = mockRespond('김철수, 123-456-789012', r.context, snap);
assert.equal(r.context.pending.awaiting, 'to');
r = mockRespond('홍길동, 123-456-789012', r.context, snap);
r = mockRespond('100만원', r.context, snap);
assert.equal(r.context.pending.awaiting, 'amount'); // 412,300원 초과 → 다시 질문

// 예시 C: 상품 RAG + 맥락
// 회귀: "통장에서"를 받는 분 이름으로 오인하지 않음
r = mockRespond('입출금통장에서 123-456-789012로 5000원 보내줘', {}, snap);
assert.ok(r.blocks.some((b) => b.kind === 'transferConfirm'), '한 문장 송금은 바로 확인 카드');
assert.ok(!JSON.stringify(r.blocks).includes('일치하지'));

r = mockRespond('입출금통장 중 금리가 가장 높은 상품이 뭐야?', {}, snap);
assert.deepEqual(r.context.lastProductIds, ['youth', 'parking', 'living']);
r = mockRespond('그럼 두 번째 상품은 가입 조건이 뭐야?', r.context, snap);
assert.equal(r.blocks.find((b) => b.kind === 'productInfo').productId, 'parking');

assert.ok(kinds(mockRespond('이번 달 카드 사용내역 보여줘', {}, snap)).some((k) => k === 'cardUsage' || k === 'text'));
// 소비 분석: 기대값은 시드에서 직접 계산 (날짜가 오늘 기준 상대값이라)
assert.equal(parsePeriod('이번 달에 커피에 얼마 썼지?'), 'this-month');
assert.equal(parsePeriod('그럼 지난달은?'), 'last-month');
const sumCafe = (p) => { const r = periodRange(p); return db.cardTxs.filter((x) => x.category === '카페' && new Date(x.date) >= r.from && new Date(x.date) < r.to).reduce((a, b) => a + b.amount, 0); };
r = mockRespond('이번 달에 커피에 얼마 썼지?', {}, snap);
let sp = r.blocks.find((b) => b.kind === 'spending');
if (sumCafe('this-month')) { assert.equal(sp.total, sumCafe('this-month')); assert.equal(sp.compare.diff, sumCafe('this-month') - sumCafe('last-month')); }
assert.deepEqual(r.context.lastSpending, { category: '카페', period: 'this-month' });
r = mockRespond('그럼 지난달은?', r.context, snap);
sp = r.blocks.find((b) => b.kind === 'spending');
assert.equal(sp.total, sumCafe('last-month'));
assert.equal(r.context.lastSpending.period, 'last-month');
r = mockRespond('이번 달 어디에 제일 많이 썼어?', {}, snap);
sp = r.blocks.find((b) => b.kind === 'spending');
if (sp) assert.ok(sp.breakdown.length && sp.breakdown[0].total >= sp.breakdown.at(-1).total);
assert.ok(kinds(mockRespond('이번 달 카드 사용내역 보여줘', { lastSpending: { period: 'this-month' } }, snap)).some((k) => k === 'cardUsage' || k === 'text'));



// 예약 송금: 시각 해석 (기준 2026-11-05 15:00)
const base = new Date(2026, 10, 5, 15, 0);
const hm = (d) => [d.getMonth() + 1, d.getDate(), d.getHours(), d.getMinutes()].join('/');
assert.equal(hm(parseWhen('내일 9시에 보내줘', base).at), '11/6/9/0');
assert.equal(hm(parseWhen('모레 오후 3시 반', base).at), '11/7/15/30');
assert.equal(hm(parseWhen('11월 10일', base).at), '11/10/9/0');
assert.equal(hm(parseWhen('10시', base).at), '11/6/10/0', '지난 시각만 말하면 다음 날');
assert.equal(hm(parseWhen('오후 8시', base).at), '11/5/20/0');
assert.equal(parseWhen('30분 뒤', base).at.getTime() - base.getTime(), 30 * 60_000);
assert.equal(parseWhen('홍길동에게 3만원', base), null);

// 한 문장 예약 → 시각이 담긴 확인 카드
r = mockRespond('내일 오전 9시에 입출금통장에서 123-456-789012로 3만원 보내줘', {}, snap);
let c = r.blocks.find((b) => b.kind === 'transferConfirm');
assert.ok(c && c.draft.runAt && c.draft.amount === 30000 && c.draft.fromId === 'acc-1');
assert.equal(new Date(c.draft.runAt).getHours(), 9);

// "예약"만 말하면 마지막에 시각을 묻고, 답하면 확인 카드
r = mockRespond('홍길동에게 5만원 예약 송금해줘', {}, snap);
r = mockRespond('입출금통장에서', r.context, snap);
assert.equal(r.context.pending.awaiting, 'when');
r = mockRespond('모레 오전 9시', r.context, snap);
c = r.blocks.find((b) => b.kind === 'transferConfirm');
assert.ok(c?.draft.runAt);
// "지금 바로"는 즉시 송금으로
r = mockRespond('홍길동에게 5만원 예약 송금해줘', {}, snap);
r = mockRespond('입출금통장에서', r.context, snap);
r = mockRespond('지금 바로', r.context, snap);
assert.equal(r.blocks.find((b) => b.kind === 'transferConfirm')?.draft.runAt, undefined);

// 회귀: 출금 계좌와 받는 분 이름을 한 문장에
r = mockRespond('내일 오전 9시에 입출금통장에서 홍길동에게 2만원 보내줘', {}, snap);
c = r.blocks.find((b) => b.kind === 'transferConfirm');
assert.equal(c?.draft.toName, '홍길동');
assert.equal(c?.draft.fromId, 'acc-1');

// 예약 목록
assert.ok(mockRespond('예약 송금 목록 보여줘', {}, snap).blocks.some((b) => b.kind === 'text' && b.text.includes('없어요')));
const withSch = { ...snap, scheduled: [{ id: 's', owner: 'x', fromId: 'acc-1', toNumber: '123-456-789012', toName: '홍길동', amount: 50000, runAt: base.toISOString(), status: 'waiting' }] };
assert.ok(kinds(mockRespond('예약된 송금 있어?', {}, withSch)).includes('scheduledList'));

console.log('chat scenarios OK');
await vite.close();
