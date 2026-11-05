import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import { randomUUID } from 'node:crypto';
import { transformWithOxc } from 'vite';

// Exercise the store's session transitions without adding a browser test dependency.
const cells = [];
let cursor = 0;
let token = null;
let rejectWithdrawal = false;
let releaseMe;
let effects = [];
let poll;
let pollMs;
let failRefresh = false;
const listeners = new Map();
const notice = (id, type) => ({ id, type, message: 'Notice', created_at: '', read_at: null });
let items = [notice(1, 'SUSPICIOUS_LOGIN')];
class BankError extends Error { constructor(code, message) { super(message); this.code = code; } }
let paymentFailure = null;
const paymentRequests = [];
const storage = new Map();
const { code } = await transformWithOxc(await readFile(new URL('../src/store.tsx', import.meta.url), 'utf8'), 'store.tsx');
const useBankState = vm.runInNewContext(
  code.replace(/^import .*;$/gm, '').replace(/^export \{.*\} from .*;$/gm, '').replace(/\bexport (?=(?:function|const)\b)/g, '') + '\nuseBankState;',
  {
    createContext: () => ({}), useContext: () => null, useEffect: (effect) => effects.push(effect),
    useState(initial) {
      const index = cursor++;
      if (!(index in cells)) cells[index] = typeof initial === 'function' ? initial() : initial;
      return [cells[index], (value) => { cells[index] = typeof value === 'function' ? value(cells[index]) : value; }];
    },
    useRef(initial) {
      const index = cursor++;
      return cells[index] ??= { current: initial };
    },
    getToken: () => token, setToken: (value) => { token = value; },
    localStorage: { getItem: (key) => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: (key) => storage.delete(key) },
    accountFrom: (value) => value, autoFrom: (value) => value, cardFrom: (value) => value,
    paymentFrom: (value) => value, scheduledFrom: (value) => value, txFrom: (value) => value,
    BankError, setTimeout, clearTimeout, crypto: { randomUUID },
    setInterval: (fn, ms) => { poll = fn; pollMs = ms; return 1; }, clearInterval: () => { poll = null; },
    window: { addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: (name) => listeners.delete(name) },
    document: { visibilityState: 'visible', addEventListener: (name, fn) => listeners.set(name, fn), removeEventListener: (name) => listeners.delete(name) },
    async api(path, body, method) {
      if (path.endsWith('/payments')) {
        paymentRequests.push(body);
        if (paymentFailure) throw new BankError(paymentFailure, 'Payment request failed');
        return {};
      }
      if (path.startsWith('/auth/login')) return { access_token: body.email };
      if (path === '/me' && method === 'DELETE') { if (rejectWithdrawal) throw new Error('Wrong PIN'); return; }
      if (path === '/me') {
        if (failRefresh) throw new Error('Offline');
        const email = token;
        if (releaseMe) await new Promise((resolve) => { releaseMe = resolve; });
        return { email, user_name: email };
      }
      if (path === '/notifications') return { items, unread: items.filter((n) => !n.read_at).length };
      if (path === '/notifications/read-all') {
        for (const n of items) if (body.ids.includes(n.id)) n.read_at = 'now';
        items.push(notice(99, 'TRANSFER_IN'));
      }
      return [];
    },
  },
);
function render() { cursor = 0; effects = []; return useBankState(); }

await render().login('first@example.com', 'password');
render().setChat({ messages: [{ text: 'Previous account chat' }], context: { thread_id: 'previous' } });
assert.equal(render().unread, 1);
render().logout();
assert.equal(render().user, null);
assert.equal(render().notices.length, 0);
assert.equal(render().unread, 0);
assert.equal(render().chat.messages.length, 0);
assert.equal(render().deviceUser.email, 'first@example.com');

await render().login('second@example.com', 'password');
assert.equal(render().user.email, 'second@example.com');
assert.equal(render().chat.messages.length, 0);
rejectWithdrawal = true;
await assert.rejects(render().withdraw('wrong'));
assert.equal(render().user.email, 'second@example.com');
assert.equal(render().deviceUser.email, 'second@example.com');
rejectWithdrawal = false;
await render().withdraw('correct');
assert.equal(token, null);
assert.equal(render().user, null);
assert.equal(render().deviceUser, null);
assert.equal(storage.has('naengo-api-device'), false);

await render().login('third@example.com', 'password');
releaseMe = true;
const pending = render().refresh();
assert.equal(await render().refresh(true), false, 'background refresh must not interrupt pending refresh');
render().logout();
releaseMe();
assert.equal(await pending, false);
assert.equal(render().user, null);
releaseMe = null;

items = [notice(1, 'TRANSFER_IN'), notice(2, 'AUTO_TRANSFER_SUCCESS'), notice(3, 'AUTO_TRANSFER_FAIL')];
await render().login('fourth@example.com', 'password');
assert.equal(render().notices.map((n) => n.kind).join(','), 'in,auto,failed');
assert.equal(render().notices.map((n) => n.to).join(','), '/,/auto-transfers,/auto-transfers');
await render().markNoticesRead();
assert.equal(render().unread, 1, 'notification arriving while reading must stay unread');
assert.equal(render().notices.find((n) => n.id === '1').read, true);
assert.equal(render().notices.find((n) => n.id === '99').read, false);

render();
const cleanup = effects[1]();
assert.equal(pollMs, 10_000);
for (const trigger of [poll, listeners.get('focus'), listeners.get('online'), listeners.get('visibilitychange')]) {
  items.push(notice(items.length + 100, 'TRANSFER_IN'));
  trigger();
  await new Promise(setImmediate);
  assert.equal(render().notices.length, items.length);
}
failRefresh = true;
assert.equal(await render().refresh(), false);
assert.equal(render().user.email, 'fourth@example.com');
assert.equal(render().loadError, 'Offline');
failRefresh = false;
await render().refresh();
assert.equal(render().loadError, '');
cleanup();
assert.equal(listeners.size, 0);
assert.equal(poll, null);
console.log('PASS: sessions, notification types/read races, 10-second/focus/online/visibility refresh, offline recovery');

const purchase = { merchant: 'Test cafe', category: 'Cafe', amount: 1000, overseas: false };
paymentFailure = 'NETWORK';
await assert.rejects(render().payWithCard('card-1', purchase));
const originalKey = paymentRequests.at(-1).idempotency_key;
const pendingCount = () => [...storage.keys()].filter((key) => key.startsWith('naengo-pending-payment:')).length;
assert.equal(pendingCount(), 1);
cells.length = 0; // Reload the store while keeping persistent browser storage.
await assert.rejects(render().payWithCard('card-1', { ...purchase, amount: 2000 }), (e) => e.code === 'PAYMENT_PENDING');
paymentFailure = null;
await render().payWithCard('card-1', purchase);
assert.equal(paymentRequests.at(-1).idempotency_key, originalKey);
assert.equal(pendingCount(), 0);
await render().payWithCard('card-1', purchase);
assert.notEqual(paymentRequests.at(-1).idempotency_key, originalKey);
paymentFailure = 'INSUFFICIENT';
await assert.rejects(render().payWithCard('card-1', purchase));
assert.equal(pendingCount(), 0);
console.log('PASS: lost payment responses retain request keys; retries reuse keys; new purchases get new keys');

// An expired background request from a previous account must not log out the next account.
let sessionToken = 'old';
let finishRequest;
let expired = 0;
const httpCode = await transformWithOxc(await readFile(new URL('../src/api/http.ts', import.meta.url), 'utf8'), 'http.ts');
const http = vm.runInNewContext(httpCode.code.replace(/\bexport (?=(?:function|async|const|class)\b)/g, '') + '\napi;', {
  sessionStorage: { getItem: () => sessionToken, setItem: (_, value) => { sessionToken = value; }, removeItem: () => { sessionToken = null; } },
  fetch: () => new Promise((resolve) => { finishRequest = resolve; }),
  window: { dispatchEvent: () => { expired++; } }, Event,
});
const unauthorized = { status: 401, ok: false, json: async () => ({ code: 'AUTH', message: 'Expired' }) };
const oldRequest = http('/me');
sessionToken = 'new';
finishRequest(unauthorized);
await assert.rejects(oldRequest);
assert.equal(sessionToken, 'new');
assert.equal(expired, 0);
const currentRequest = http('/me');
finishRequest(unauthorized);
await assert.rejects(currentRequest);
assert.equal(sessionToken, null);
assert.equal(expired, 1);
console.log('PASS: stale authentication errors cannot clear a new login');
