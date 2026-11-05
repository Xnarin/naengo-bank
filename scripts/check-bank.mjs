// 계좌 관리 규칙 점검: 이체한도 사용액, 해지 가능 여부
import assert from 'node:assert/strict';
import { createServer } from 'vite';

const vite = await createServer({ server: { middlewareMode: true }, appType: 'custom', logLevel: 'error' });
const { usageOf, closeBlockers, withdrawBlockers, EMAIL_RE } = await vite.ssrLoadModule('/src/store.tsx');
const { weakPin } = await vite.ssrLoadModule('/src/pages/Auth.tsx');
const { seed, nextRun } = await vite.ssrLoadModule('/src/data/mock.ts');
const { recentRecipients } = await vite.ssrLoadModule('/src/store.tsx');
const db = seed();

// 내 계좌끼리 옮긴 돈은 한도에서 빠진다
const now = new Date().toISOString();
const t = (accountId, amount, counterpartyAccount) => ({ id: Math.random().toString(), accountId, date: now, type: 'out', amount, counterparty: 'x', counterpartyAccount, balanceAfter: 0 });
const before = usageOf(db, 'acc-1');
db.txs.push(t('acc-1', 70_000, '123-456-789012'), t('acc-1', 500_000, '110-482-771203'));
const after = usageOf(db, 'acc-1');
assert.equal(after.today - before.today, 70_000);
assert.equal(after.month - before.month, 70_000);

// 시드 계좌는 잔액·카드가 있어 해지 불가
assert.deepEqual(closeBlockers(db, 'acc-1').map((b) => b.kind).sort(), ['balance', 'card', 'scheduled']);
// 잔액 0, 카드·예약 없음 → 해지 가능
db.accounts.push({ ...db.accounts[0], id: 'acc-new', number: '110-000-000001', balance: 0 });
assert.deepEqual(closeBlockers(db, 'acc-new'), []);
db.accounts.at(-1).status = 'suspended';
assert.deepEqual(closeBlockers(db, 'acc-new').map((b) => b.kind), ['status']);

// 회원: 이메일 형식, 약한 간편비밀번호, 탈퇴 조건
assert.ok(EMAIL_RE.test('haneul@example.com') && !EMAIL_RE.test('haneul@example') && !EMAIL_RE.test('a b@x.com'));
assert.ok(weakPin('111111') && weakPin('123456') && weakPin('654321') && !weakPin('258014'));
assert.equal(withdrawBlockers(db, 'demo@naengo.bank').length, 3, '잔액·예약·자동이체가 있으면 탈퇴 불가');
assert.deepEqual(withdrawBlockers(db, 'nobody@example.com'), []);

// 자동이체 다음 실행일(오전 9시)
const d = (s) => new Date(s);
const day = (iso) => { const x = new Date(iso); return [x.getMonth() + 1, x.getDate(), x.getHours()].join('/'); };
assert.equal(day(nextRun('monthly', 25, '2026-11-01', d('2026-11-05T10:00'))), '11/25/9');
assert.equal(day(nextRun('monthly', 25, '2026-11-01', d('2026-11-25T09:00'))), '12/25/9', '같은 시각이면 다음 달');
assert.equal(day(nextRun('monthly', 31, '2026-11-01', d('2026-11-05T10:00'))), '11/30/9', '31일이 없는 달은 말일');
assert.equal(day(nextRun('weekly', 5, '2026-11-05', d('2026-11-05T10:00'))), '11/6/9', '2026-11-06은 금요일');
assert.equal(day(nextRun('monthly', 3, '2026-12-01', d('2026-11-05T10:00'))), '12/3/9', '시작일 이전은 건너뜀');

// 최근 보낸 계좌: 내 계좌 제외, 즐겨찾기 먼저
const r0 = recentRecipients(db, 'demo@naengo.bank');
assert.ok(r0.length >= 3 && r0.every((r) => !r.number.startsWith('110-482')));
db.users[0].favRecipients = ['330-712-009812'];
assert.equal(recentRecipients(db, 'demo@naengo.bank')[0].name, '이서준');

console.log('bank rules OK');
await vite.close();
