import { useState, type ReactNode } from 'react';
import { ArrowDownRight, ArrowUpRight, ChevronDown, CircleAlert } from 'lucide-react';
import type { InsightBlock } from '../api/chat';
import { cn, won } from '../lib/format';

/**
 * 챗봇 인사이트 카드 3종(소비·잔액 예측·정기결제). 한 가지 틀을 같이 쓴다:
 * 머리줄(무엇·기간) → 답이 되는 숫자 하나(Sora) → 그래프 → 장부 줄 → 계산 기준 접기.
 * 색은 브랜드 한 색을 농도로만 나눠 테마(바이올렛·모노·틸·코랄)를 그대로 따른다.
 */

const dateLabel = (date: string) => date.slice(5, 10).replace('-', '.');
const pct = (part: number, total: number) => (total > 0 ? Math.round((part / total) * 100) : 0);
/** 순위대로 진한 → 옅은 브랜드색. 마지막(기타)은 회색 선. */
const SHADES = [100, 72, 52, 38, 27, 18];
const shade = (i: number, n: number) =>
  i === n - 1 && n > SHADES.length ? 'var(--color-line)' : `color-mix(in oklab, var(--color-brand) ${SHADES[Math.min(i, SHADES.length - 1)]}%, var(--color-paper))`;

function Shell({ label, aside, children, notes }: { label: string; aside?: ReactNode; children: ReactNode; notes?: ReactNode }) {
  return (
    <section aria-label={label} className="w-full overflow-hidden rounded-2xl border border-line bg-paper">
      <div className="px-4 pt-4 pb-5">
        <div className="flex items-baseline justify-between gap-3">
          <h3 className="text-[14px] font-semibold text-sub">{label}</h3>
          {aside && <span className="num shrink-0 text-[13px] text-sub">{aside}</span>}
        </div>
        {children}
      </div>
      {notes && (
        <details className="group border-t border-line px-4 py-3 text-[13px] text-sub">
          <summary className="flex cursor-pointer list-none items-center justify-between font-medium">
            계산 기준<ChevronDown className="size-4 transition-transform group-open:rotate-180" />
          </summary>
          <div className="mt-2 space-y-1.5 leading-relaxed">{notes}</div>
        </details>
      )}
    </section>
  );
}

function Big({ children, danger }: { children: ReactNode; danger?: boolean }) {
  return <p className={cn('num mt-2 font-display text-[30px] leading-tight font-bold', danger ? 'text-danger' : 'text-navy')}>{children}</p>;
}

function Delta({ value, suffix }: { value: number; suffix: string }) {
  if (!value) return <span className="text-sub">{suffix} 그대로</span>;
  const up = value > 0;
  return (
    <span className={cn('inline-flex items-center gap-0.5 font-semibold', up ? 'text-danger' : 'text-success')}>
      {up ? <ArrowUpRight className="size-4" /> : <ArrowDownRight className="size-4" />}
      {suffix} {won(Math.abs(value))} {up ? '더' : '덜'}
    </span>
  );
}

export function InsightCard({ block, onGo }: { block: InsightBlock; onGo?: (to: string) => void }) {
  switch (block.kind) {
    case 'recommendationInsight': return <RecommendationCard block={block} onGo={onGo} />;
    case 'spendingInsight': return <SpendingCard block={block} />;
    case 'forecastInsight': return <ForecastCard block={block} />;
    case 'subscriptionInsight': return <SubscriptionCard block={block} />;
  }
}

function RecommendationCard({ block: b, onGo }: { block: Extract<InsightBlock, { kind: 'recommendationInsight' }>; onGo?: (to: string) => void }) {
  const personalized = b.status === '소비패턴기준비교';
  return <Shell label="나에게 맞는 입출금통장" aside={personalized ? '패턴 기반 비교' : '목적 확인'}
    notes={<>{b.notes.map((note) => <p key={note}>{note}</p>)}<p className="num">분석 기간 {b.start} ~ {b.end}</p></>}>
    <p className="mt-3 text-[14px] leading-relaxed text-sub">
      {personalized ? '소비와 보유 통장을 살펴보고 비교 순서를 정했어요.' : b.status === '상품조건확인필요' ? '현재 상품 조건을 확인하지 못해 비교 후보를 표시하지 않았어요.' : b.question ?? '기록이 짧아 말씀하신 사용 목적을 기준으로 비교해요.'}
    </p>
    {personalized && <div className="mt-4 grid grid-cols-2 gap-4 border-y border-line py-3">
      <div><p className="text-[12px] text-sub">분석 기간 카드 소비</p><p className="num mt-1 text-[17px] font-semibold">{won(b.cardTotal)}</p></div>
      <div><p className="text-[12px] text-sub">정기결제 후보</p><p className="num mt-1 text-[17px] font-semibold">{b.recurringCount}개</p></div>
    </div>}
    <ol className="mt-2 divide-y divide-line">
      {b.items.map((item, index) => <li key={item.code} className="py-5 last:pb-0">
        <div className="flex items-center justify-between gap-2 text-[12px]">
          <span className="font-semibold text-brand">{index === 0 ? '먼저 비교해 보세요' : `비교 후보 ${index + 1}`}</span>
          {item.owned && <span className="rounded-full bg-surface px-2 py-1 font-medium text-sub">보유 중</span>}
        </div>
        <h4 className="mt-2 text-[17px] font-bold">{item.name}</h4>
        <p className="num mt-1 text-[14px] text-sub">최고 연 <span className="font-semibold text-ink">{item.maxRate.toFixed(1)}%</span> · 적용 조건 확인 필요</p>
        <ul className="mt-3 space-y-2 text-[14px] leading-relaxed">
          {item.reasons.map((reason) => <li key={reason} className="flex gap-2"><span aria-hidden className="mt-2 size-1 shrink-0 rounded-full bg-brand" /><span>{reason}</span></li>)}
        </ul>
        <details className="mt-3 text-[13px] text-sub">
          <summary className="cursor-pointer font-medium">가입 조건·금리 구간</summary>
          <div className="mt-2 space-y-1.5 leading-relaxed">
            {item.conditions.map((line) => <p key={line}>{line}</p>)}
            {item.rateTable.map((row) => <p key={row.label}>{row.label}: {row.rate}</p>)}
            {item.notices.map((line) => <p key={line}>{line}</p>)}
          </div>
        </details>
        <a href={`/products/${encodeURIComponent(item.code)}`} onClick={onGo ? (event) => { event.preventDefault(); onGo(`/products/${encodeURIComponent(item.code)}`); } : undefined}
          className="mt-4 flex w-full items-center justify-center rounded-full border border-brand/30 py-2.5 text-[14px] font-semibold text-brand hover:bg-brand-soft">상품 자세히 보기</a>
      </li>)}
    </ol>
    <p className="mt-4 text-[12px] leading-relaxed text-sub">가상 상품의 비교 안내예요. 가입·우대 조건은 상품 설명에서 확인해 주세요.</p>
  </Shell>;
}

// ── 소비 분석: 도넛 + 이전 기간 비교 ─────────────────────────────
function Donut({ rows, total, active, onPick }: { rows: { label: string; amount: number }[]; total: number; active: number; onPick: (i: number) => void }) {
  const R = 52, C = 2 * Math.PI * R, GAP = rows.length > 1 ? 2.5 : 0;
  let offset = 0;
  const row = rows[active];
  return (
    <div className="relative mx-auto size-44">
      <svg viewBox="0 0 132 132" className="size-full -rotate-90" role="img"
        aria-label={`출금 비중: ${rows.map((r) => `${r.label} ${pct(r.amount, total)}%`).join(', ')}`}>
        {rows.map((r, i) => {
          const len = (r.amount / total) * C;
          const seg = (
            <circle key={r.label} cx="66" cy="66" r={R} fill="none" strokeWidth={i === active ? 20 : 16}
              stroke={shade(i, rows.length)} strokeDasharray={`${Math.max(0, len - GAP)} ${C}`} strokeDashoffset={-offset}
              className="cursor-pointer transition-[stroke-width] duration-200" onClick={() => onPick(i)} />
          );
          offset += len;
          return seg;
        })}
      </svg>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center">
        <span className="max-w-24 truncate text-[13px] text-sub">{row.label}</span>
        <span className="num font-display text-[22px] leading-tight font-bold text-navy">{pct(row.amount, total)}%</span>
        <span className="num text-[12px] text-sub">{won(row.amount)}</span>
      </div>
    </div>
  );
}

function SpendingCard({ block: b }: { block: Extract<InsightBlock, { kind: 'spendingInsight' }> }) {
  const [view, setView] = useState<'share' | 'compare'>('share');
  const rows = b.categories.filter((r) => r.amount > 0).sort((x, y) => y.amount - x.amount);
  const [active, setActive] = useState(0);
  const max = Math.max(1, ...b.categories.flatMap((r) => [r.amount, r.previous ?? 0]));
  const compareRows = [...b.categories].sort((x, y) => Math.max(y.amount, y.previous ?? 0) - Math.max(x.amount, x.previous ?? 0));

  return (
    <Shell label="소비 분석" aside={`${dateLabel(b.start)} ~ ${dateLabel(b.end)}`}
      notes={<>{b.notes.map((n) => <p key={n}>{n}</p>)}<p className="num">카드 {won(b.cardTotal)} · 이체·기타 {won(b.transferTotal)}</p></>}>
      <Big>{won(b.total)}</Big>
      {b.comparison && <p className="num mt-1 text-[14px]"><Delta value={b.comparison.delta} suffix="지난 기간보다" /></p>}

      {b.comparison && (
        <div className="mt-5 grid grid-cols-2 gap-1 rounded-full bg-surface p-1" role="tablist" aria-label="보기 방식">
          {([['share', '어디에 썼나'], ['compare', '지난 기간과 비교']] as const).map(([v, l]) => (
            <button key={v} type="button" role="tab" aria-selected={view === v} onClick={() => setView(v)}
              className={cn('h-9 rounded-full text-[13px] font-semibold transition-colors', view === v ? 'bg-paper text-ink shadow-sm' : 'text-sub')}>{l}</button>
          ))}
        </div>
      )}

      {b.total === 0 ? (
        <p className="py-8 text-center text-[14px] text-sub">이 기간에 나간 돈이 없어요.</p>
      ) : view === 'share' ? (
        <>
          <div className="mt-6"><Donut rows={rows} total={b.total} active={Math.min(active, rows.length - 1)} onPick={setActive} /></div>
          <ul className="mt-5 divide-y divide-line/60">
            {rows.map((r, i) => (
              <li key={r.label}>
                <button type="button" onClick={() => setActive(i)} aria-pressed={i === active}
                  className={cn('flex w-full items-center gap-3 py-2.5 text-left text-[14px]', i === active ? 'font-semibold text-ink' : 'text-ink/80')}>
                  <span aria-hidden className="h-3.5 w-1.5 shrink-0 rounded-full" style={{ background: shade(i, rows.length) }} />
                  <span className="min-w-0 flex-1 truncate">{r.label}</span>
                  <span className="num w-10 shrink-0 text-right text-[13px] text-sub">{pct(r.amount, b.total)}%</span>
                  <span className="num w-24 shrink-0 text-right">{won(r.amount)}</span>
                </button>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <>
          <div className="mt-5 flex justify-end gap-4 text-[12px] text-sub" aria-hidden>
            <span className="flex items-center gap-1.5"><span className="h-2 w-3 rounded-full bg-brand" />이번 기간</span>
            <span className="flex items-center gap-1.5"><span className="h-2 w-3 rounded-full bg-mute/50" />지난 기간</span>
          </div>
          <ul className="mt-2 space-y-4">
            {compareRows.map((r) => {
              const prev = r.previous ?? 0;
              return (
                <li key={r.label} aria-label={`${r.label}: 이번 ${won(r.amount)}, 지난 ${won(prev)}`}>
                  <div className="flex items-baseline justify-between gap-2 text-[14px]">
                    <span className="min-w-0 truncate font-medium">{r.label}</span>
                    <span className="num shrink-0 text-[13px]"><Delta value={r.amount - prev} suffix="" /></span>
                  </div>
                  <div className="mt-1.5 space-y-1" aria-hidden>
                    <div className="flex items-center gap-2">
                      <div className="h-2.5 flex-1 rounded-full bg-surface"><div className="h-full rounded-full bg-brand" style={{ width: `${(r.amount / max) * 100}%` }} /></div>
                      <span className="num w-[84px] text-right text-[13px] font-semibold">{won(r.amount)}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <div className="h-2.5 flex-1 rounded-full bg-surface"><div className="h-full rounded-full bg-mute/50" style={{ width: `${(prev / max) * 100}%` }} /></div>
                      <span className="num w-[84px] text-right text-[13px] text-sub">{won(prev)}</span>
                    </div>
                  </div>
                </li>
              );
            })}
          </ul>
          {b.comparison && <p className="num mt-4 text-[13px] text-sub">비교 기간 {dateLabel(b.comparison.start)} ~ {dateLabel(b.comparison.end)} · {won(b.comparison.total)}</p>}
        </>
      )}
    </Shell>
  );
}

// ── 잔액 예측: 날짜를 밀어 보는 선 그래프 ─────────────────────────
function BalanceChart({ points, scheduled }: { points: { date: string; balance: number }[]; scheduled: { date: string }[] }) {
  const [sel, setSel] = useState(points.length - 1);
  if (points.length < 2) return null;
  const i = Math.min(sel, points.length - 1);
  const W = 320, H = 150, L = 4, R = 4, T = 12, B = 22;
  const vals = points.map((p) => p.balance);
  const lo = Math.min(0, ...vals), hi = Math.max(...vals);
  const pad = Math.max(1, hi - lo) * 0.08;
  const x = (k: number) => L + (k / (points.length - 1)) * (W - L - R);
  const y = (v: number) => T + ((hi + pad - v) / (hi - lo + pad * 2)) * (H - T - B);
  const line = points.map((p, k) => `${k ? 'L' : 'M'}${x(k).toFixed(1)},${y(p.balance).toFixed(1)}`).join(' ');
  const area = `${line} L${x(points.length - 1)},${H - B} L${x(0)},${H - B} Z`;
  const p = points[i];
  const neg = p.balance < 0;
  const marks = new Set(scheduled.map((s) => s.date.slice(0, 10)));

  return (
    <div className="mt-5">
      <div className="flex items-baseline justify-between">
        <span className="text-[13px] text-sub">{i === 0 ? '오늘' : `${dateLabel(p.date)}`} 예상 잔액</span>
        <span className={cn('num font-display text-[18px] font-bold', neg ? 'text-danger' : 'text-navy')}>{won(p.balance)}</span>
      </div>
      <div className="relative mt-2">
        <svg viewBox={`0 0 ${W} ${H}`} className="block w-full" aria-hidden>
          <path d={area} fill="var(--color-brand)" opacity="0.08" />
          {lo < 0 && (
            <>
              <rect x={L} y={y(0)} width={W - L - R} height={H - B - y(0)} fill="var(--color-danger)" opacity="0.06" />
              <line x1={L} x2={W - R} y1={y(0)} y2={y(0)} stroke="var(--color-danger)" strokeDasharray="3 4" />
              <text x={L + 2} y={y(0) - 5} fontSize="11" fill="var(--color-danger)">0원</text>
            </>
          )}
          <path d={line} fill="none" stroke="var(--color-brand)" strokeWidth="2.5" strokeLinejoin="round" strokeLinecap="round" />
          {points.map((pt, k) => marks.has(pt.date.slice(0, 10)) && <circle key={pt.date} cx={x(k)} cy={y(pt.balance)} r="3" fill="var(--color-paper)" stroke="var(--color-brand)" strokeWidth="1.5" />)}
          <line x1={x(i)} x2={x(i)} y1={T - 6} y2={H - B} stroke="var(--color-ink)" strokeOpacity="0.25" />
          <circle cx={x(i)} cy={y(p.balance)} r="6" fill={neg ? 'var(--color-danger)' : 'var(--color-brand)'} stroke="var(--color-paper)" strokeWidth="2.5" />
          <text x={L} y={H - 4} fontSize="11" fill="var(--color-sub)">오늘 {dateLabel(points[0].date)}</text>
          <text x={W - R} y={H - 4} textAnchor="end" fontSize="11" fill="var(--color-sub)">월말 {dateLabel(points.at(-1)!.date)}</text>
        </svg>
        {/* 그래프 전체가 손잡이: 좌우로 밀거나 키보드 화살표로 날짜를 고른다 */}
        <input type="range" min={0} max={points.length - 1} value={i} onChange={(e) => setSel(Number(e.target.value))}
          aria-label="날짜별 예상 잔액" aria-valuetext={`${dateLabel(p.date)} ${won(p.balance)}`}
          className="absolute inset-x-0 top-0 h-[calc(100%-22px)] w-full cursor-ew-resize opacity-0" />
      </div>
      <p className="mt-1 text-[12px] text-sub">그래프를 좌우로 밀면 날짜별 잔액이 보여요. 동그라미는 예정된 이체·결제일이에요.</p>
    </div>
  );
}

function ForecastCard({ block: b }: { block: Extract<InsightBlock, { kind: 'forecastInsight' }> }) {
  const ok = b.sufficient && b.estimatedExpense !== undefined && b.projectedBalance !== undefined;
  const month = Number(b.month.slice(-2));
  const neg = (b.projectedBalance ?? 0) < 0;
  return (
    <Shell label={`${month}월 말 예상 잔액`} aside={ok ? '과거 패턴 추정' : '기록 모으는 중'}
      notes={<>{b.notes.map((n) => <p key={n}>{n}</p>)}<p>앞으로 들어올 돈은 0원으로 가정해요. 확정 잔액이 아니에요.</p><p className="num">관측 {b.observedDays}일 · 출금 {b.observedCount}건 · {dateLabel(b.asOf)} 기준</p></>}>
      {ok ? (
        <>
          <Big danger={neg}>{won(b.projectedBalance!)}</Big>
          <p className="num mt-1 text-[14px] text-sub">지금 {won(b.balance)}에서 {won(b.estimatedExpense!)} 더 나갈 것 같아요</p>
          {!!b.shortage && (
            <p className="mt-3 flex items-start gap-1.5 rounded-xl bg-danger-soft px-3 py-2.5 text-[14px] text-danger">
              <CircleAlert className="mt-0.5 size-4 shrink-0" />입금이 없으면 {won(b.shortage)} 모자랄 수 있어요.
            </p>
          )}
          <BalanceChart points={b.points ?? []} scheduled={b.scheduled} />
          {b.expenseRange && <p className="num mt-3 text-[13px] text-sub">예상 출금 범위 {won(b.expenseRange.min)} ~ {won(b.expenseRange.max)}</p>}
        </>
      ) : (
        <>
          <p className="mt-3 text-[18px] leading-snug font-bold">아직 예측할 기록이 부족해요</p>
          <p className="mt-1.5 text-[14px] leading-relaxed text-sub">{b.reason}</p>
          <div className="mt-4">
            <div className="flex justify-between text-[13px] text-sub"><span>모인 기록</span><span className="num">{b.observedDays}일 · {b.observedCount}건</span></div>
            <div className="mt-1.5 h-2 rounded-full bg-surface"><div className="h-full rounded-full bg-brand" style={{ width: `${Math.min(1, b.observedDays / 28, b.observedCount / 5) * 100}%` }} /></div>
          </div>
          <p className="num mt-3 text-[14px]">지금 잔액 <b className="font-semibold">{won(b.balance)}</b></p>
        </>
      )}
      {b.scheduled.length > 0 && (
        <div className="mt-5 border-t border-line pt-4">
          <p className="flex justify-between text-[13px] text-sub"><span>남은 예정 이체·정기결제</span><span className="num font-semibold text-ink">{won(b.fixedTotal)}</span></p>
          <ul className="mt-1">
            {b.scheduled.map((r, k) => (
              <li key={`${r.date}-${k}`} className="flex items-center gap-3 py-1.5 text-[14px]">
                <span className="num w-11 shrink-0 text-[13px] text-sub">{dateLabel(r.date)}</span>
                <span className="min-w-0 flex-1 truncate">{r.label}</span>
                <span className="num shrink-0">{won(r.amount)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Shell>
  );
}

// ── 정기결제 후보: 월 합계 + 서비스별 줄 ─────────────────────────
function SubscriptionCard({ block: b }: { block: Extract<InsightBlock, { kind: 'subscriptionInsight' }> }) {
  const items = [...b.items].sort((x, y) => y.amount - x.amount);
  return (
    <Shell label="정기결제 후보" aside={`${items.length}개`} notes={<><p>{b.note}</p><p className="num">조회 기간 {b.start} ~ {b.end}</p><p>실제 구독 여부와 해지는 가맹점에서 확인해 주세요.</p></>}>
      <Big>{won(b.total)}<span className="ml-1 text-[16px] font-semibold text-sub">/ 월</span></Big>
      <p className="num mt-1 text-[14px] text-sub">1년이면 {won(b.total * 12)}</p>
      {items.length ? (
        <>
          {/* 합계 안에서 서비스별 몫 */}
          <div className="mt-5 flex h-2.5 gap-0.5 overflow-hidden rounded-full" aria-hidden>
            {items.map((it, i) => <span key={it.name} style={{ flex: it.amount, background: shade(i, items.length) }} />)}
          </div>
          <ul className="mt-3 divide-y divide-line/60">
            {items.map((it, i) => (
              <li key={it.name} className="flex items-center gap-3 py-3">
                <span aria-hidden className="h-8 w-1.5 shrink-0 rounded-full" style={{ background: shade(i, items.length) }} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[15px] font-semibold">{it.name}</span>
                  <span className="block text-[13px] text-sub">매월 {it.billingDay}일쯤 · {it.count}번 결제</span>
                </span>
                <span className="text-right">
                  <span className="num block text-[15px] font-semibold">{won(it.amount)}</span>
                  <span className="num block text-[12px] text-sub">최근 {dateLabel(it.lastDate)}</span>
                </span>
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p className="mt-4 text-[14px] leading-relaxed text-sub">반복 결제를 찾지 못했어요. 기록이 적거나 1년에 한 번 내는 결제는 안 보일 수 있어요.</p>
      )}
    </Shell>
  );
}
