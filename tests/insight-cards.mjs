import assert from 'node:assert/strict';
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';

const server = await createServer({ server: { middlewareMode: true, hmr: false } });
try {
  const { InsightCard } = await server.ssrLoadModule('/src/components/InsightCard.tsx');
  const render = (block) => renderToStaticMarkup(createElement(InsightCard, { block }));
  const forecast = { kind: 'forecastInsight', month: '2026-11', asOf: '2026-11-06', balance: 1000,
    sufficient: true, observedDays: 90, observedCount: 30, fixedTotal: 0, scheduled: [], notes: [],
    estimatedExpense: 2000, projectedBalance: -1000, shortage: 1000,
    points: [{ date: '2026-11-06', balance: 1000 }, { date: '2026-11-30', balance: -1000 }] };
  const negative = render(forecast);
  assert.match(negative, /-1,000원/);
  assert.match(negative, /type="range"[^>]*aria-label="날짜별 예상 잔액"/);
  assert.match(negative, /입금이 없으면/);
  assert.doesNotMatch(negative, /NaN|Infinity/);
  assert.doesNotMatch(render({ ...forecast, points: forecast.points.map((point) => ({ ...point, balance: 0 })) }), /NaN|Infinity/);
  const cold = render({ ...forecast, sufficient: false, reason: '기록이 부족해요.', points: undefined, projectedBalance: undefined, estimatedExpense: undefined });
  assert.match(cold, /기록이 부족해요/);
  assert.doesNotMatch(cold, /type="range"/);
  assert.doesNotMatch(cold, /-1,000원/);
  const spending = render({ kind: 'spendingInsight', start: '2026-11-01', end: '2026-11-06', total: 0,
    cardTotal: 0, transferTotal: 0, categories: [], notes: [] });
  assert.match(spending, /이 기간에 나간 돈이 없어요/);
  assert.doesNotMatch(spending, /NaN|Infinity|conic-gradient/);
  const subscriptions = render({ kind: 'subscriptionInsight', start: '2026-08-01', end: '2026-11-06', total: 14900,
    note: '구독 후보', items: [{ name: 'StreamFlix', amount: 14900, count: 3, lastDate: '2026-10-08', billingDay: 8 }] });
  assert.match(subscriptions, /14,900원/);
  assert.match(subscriptions, /매월 8일쯤/);
  const recommendation = render({ kind: 'recommendationInsight', status: '소비패턴기준비교', start: '2026-08-01', end: '2026-11-06',
    cardTotal: 15000, count: 5, recurringCount: 3, notes: [],
    items: [{ code: 'living', name: '내금고 생활비통장', owned: true, reasons: ['카드 소비 15,000원 기준으로 비교해요.'],
      maxRate: 1.2, baseRate: 0.3, conditions: ['월 50만원 이상 급여 실적 확인'], rateTable: [{ label: '기본금리', rate: '연 0.3%' }], notices: [] }] });
  assert.match(recommendation, /15,000원/);
  assert.match(recommendation, /보유 중/);
  assert.match(recommendation, /href="\/products\/living"/);
  assert.match(recommendation, /적용 조건 확인 필요/);
  const coldRecommendation = render({ kind: 'recommendationInsight', status: '데이터부족', start: '', end: '', cardTotal: 0,
    count: 0, recurringCount: 0, items: [], notes: [], question: '어떤 목적으로 쓸 통장인가요?' });
  assert.match(coldRecommendation, /어떤 목적으로 쓸 통장인가요/);
  assert.doesNotMatch(coldRecommendation, /먼저 비교해 보세요/);
  console.log('PASS: negative/flat forecast charts, insufficient data, empty spending, subscription amounts');
} finally {
  await server.close();
}
