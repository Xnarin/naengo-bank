import { useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { ArrowDownUp, Copy, Download, Receipt, Search, SearchX, Settings2, X } from 'lucide-react';
import { TxDetailSheet, TxList, toneOf } from '../components/bank';
import { Button, EmptyState, ErrorState, Field, ListSkeleton, Page, Sheet } from '../components/ui';
import type { Account, Tx } from '../data/mock';
import { cn, fmtDateTime, won } from '../lib/format';
import { useBank, useLoad } from '../store';

const PERIODS = [
  { key: '1w', label: '1주일', days: 7 },
  { key: '1m', label: '1개월', days: 31 },
  { key: '3m', label: '3개월', days: 92 },
  { key: 'custom', label: '직접 설정', days: 0 },
] as const;
const TYPES = [{ key: 'all', label: '전체' }, { key: 'in', label: '입금' }, { key: 'out', label: '출금' }] as const;
const KINDS = [{ key: 'all', label: '전체' }, { key: 'transfer', label: '계좌이체' }, { key: 'auto', label: '자동이체' }, { key: 'card', label: '카드' }, { key: 'etc', label: '기타' }] as const;
type Kind = (typeof KINDS)[number]['key'];
const ymd = (d: Date) => d.toLocaleDateString('sv-SE'); // YYYY-MM-DD (로컬)

/** 서버 거래 유형을 우선하고 이전 표시 데이터도 읽는다. */
export function txKind(t: Tx): Exclude<Kind, 'all'> {
  if (t.kind) return t.kind === 'AUTO_TRANSFER' ? 'auto' : t.kind === 'CARD' ? 'card' : t.kind === 'TRANSFER' ? 'transfer' : 'etc';
  if (t.memo?.includes('자동이체')) return 'auto';
  if (t.memo?.startsWith('체크카드')) return 'card';
  return t.counterpartyAccount ? 'transfer' : 'etc';
}

type Query = { q: string; min: string; max: string; kind: Kind };
const EMPTY_Q: Query = { q: '', min: '', max: '', kind: 'all' };

export function AccountDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { myAccounts, db, toast, user } = useBank();
  // 해지한 계좌도 거래내역은 볼 수 있다
  const account = db.accounts.find((a) => a.id === id && a.owner === user?.email);
  const [period, setPeriod] = useState<(typeof PERIODS)[number]['key']>('3m');
  const [type, setType] = useState<'all' | 'in' | 'out'>('all');
  const [asc, setAsc] = useState(false);
  const [query, setQuery] = useState<Query>(EMPTY_Q);
  const [sheet, setSheet] = useState<null | 'search' | 'download'>(null);
  const [range, setRange] = useState(() => {
    const to = new Date(), from = new Date();
    from.setMonth(from.getMonth() - 3);
    return { from: ymd(from), to: ymd(to) };
  });
  const [selected, setSelected] = useState<Tx | null>(null);
  const { state, retry } = useLoad([period, range.from, range.to]);
  const searching = query.q || query.min || query.max || query.kind !== 'all';

  const txs = useMemo(() => {
    const p = PERIODS.find((x) => x.key === period)!;
    const from = p.key === 'custom' ? new Date(`${range.from}T00:00`) : new Date(Date.now() - p.days * 864e5);
    const to = p.key === 'custom' ? new Date(`${range.to}T23:59:59`) : new Date(8.64e15);
    const q = query.q.trim().toLowerCase();
    const min = Number(query.min || 0), max = Number(query.max || Infinity);
    return db.txs
      .filter((t) => t.accountId === id && (type === 'all' || t.type === type))
      .filter((t) => { const d = new Date(t.date); return d >= from && d <= to; })
      .filter((t) => !q || t.counterparty.toLowerCase().includes(q) || (t.memo ?? '').toLowerCase().includes(q))
      .filter((t) => t.amount >= min && t.amount <= max)
      .filter((t) => query.kind === 'all' || txKind(t) === query.kind)
      .sort((a, b) => (asc ? a.date.localeCompare(b.date) : b.date.localeCompare(a.date)));
  }, [db.txs, id, type, period, range, query, asc]);

  if (!account) {
    return (
      <Page back title="계좌 상세" nav>
        <EmptyState icon={SearchX} title="계좌를 찾을 수 없어요" desc="해지됐거나 내 계좌가 아니에요." action={<Button onClick={() => navigate('/')}>홈으로</Button>} />
      </Page>
    );
  }

  const copy = async () => {
    try { await navigator.clipboard.writeText(account.number); toast('계좌번호가 복사됐어요'); }
    catch { toast('복사하지 못했어요'); }
  };

  return (
    <Page back title={account.name} nav>
      <section className={cn('mt-2 mb-6 rounded-[20px] p-5', account.status === 'closed' ? 'bg-surface' : toneOf(myAccounts, account.id))}>
        <button onClick={copy} className="num inline-flex items-center gap-1.5 text-[14px] text-ink/75 underline-offset-2 hover:underline" aria-label="계좌번호 복사">
          내금고 {account.number}<Copy className="size-3.5" />
        </button>
        <p className="num mt-2 font-display text-[30px] font-bold">{won(account.balance)}</p>
        {account.status === 'closed' ? (
          <p className="mt-4 text-[14px] font-medium text-sub">{fmtDateTime(account.closedAt ?? '')}에 해지한 계좌예요. 거래내역만 볼 수 있어요.</p>
        ) : account.status === 'suspended' ? (
          <>
            <p className="mt-4 text-[14px] font-semibold text-danger">거래중지 · 간편비밀번호를 5회 틀렸어요</p>
            <Button size="lg" full className="mt-3" onClick={() => navigate(`/accounts/${account.id}/manage`)}>본인인증으로 해제하기</Button>
          </>
        ) : (
          <div className="mt-5 grid grid-cols-[auto_1fr] gap-2">
            <Button size="lg" variant="secondary" onClick={() => navigate(`/accounts/${account.id}/manage`)} aria-label="계좌 관리"><Settings2 className="size-5" />관리</Button>
            <Button size="lg" onClick={() => navigate(`/transfer?from=${account.id}`)}>송금</Button>
          </div>
        )}
      </section>

      <section className="sticky top-14 z-20 -mx-5 bg-paper px-5 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <div className="no-scrollbar flex flex-1 gap-2 overflow-x-auto" role="radiogroup" aria-label="조회 기간">
            {PERIODS.map((p) => (
              <button key={p.key} role="radio" aria-checked={period === p.key} onClick={() => setPeriod(p.key)}
                className={cn('h-9 shrink-0 rounded-full px-4 text-[14px] font-medium', period === p.key ? 'bg-navy text-white' : 'bg-surface text-sub')}>
                {p.label}
              </button>
            ))}
          </div>
          <button onClick={() => setSheet('search')} aria-label="거래 검색" className={cn('grid size-9 shrink-0 place-items-center rounded-full', searching ? 'bg-brand text-white' : 'bg-surface text-sub')}><Search className="size-4" /></button>
          <button onClick={() => setSheet('download')} aria-label="거래내역 받기" className="grid size-9 shrink-0 place-items-center rounded-full bg-surface text-sub"><Download className="size-4" /></button>
        </div>
        {period === 'custom' && (
          <div className="mt-3 flex items-center gap-2 text-[14px]">
            <input type="date" aria-label="시작일" value={range.from} max={range.to} onChange={(e) => setRange({ ...range, from: e.target.value })} className="h-10 flex-1 rounded-lg border border-line px-2" />
            <span className="text-mute">~</span>
            <input type="date" aria-label="종료일" value={range.to} min={range.from} max={ymd(new Date())} onChange={(e) => setRange({ ...range, to: e.target.value })} className="h-10 flex-1 rounded-lg border border-line px-2" />
          </div>
        )}
        {searching && (
          <p className="mt-3 flex items-center gap-2 rounded-xl bg-brand-soft px-3 py-2 text-[13px]">
            <Search className="size-3.5 text-brand" />
            <span className="min-w-0 flex-1 truncate">{describe(query)}</span>
            <button onClick={() => setQuery(EMPTY_Q)} aria-label="검색 조건 지우기" className="text-sub"><X className="size-4" /></button>
          </p>
        )}
        <div className="mt-3 flex items-center gap-4 text-[14px]">
          <div className="flex gap-4" role="radiogroup" aria-label="거래 구분">
            {TYPES.map((t) => (
              <button key={t.key} role="radio" aria-checked={type === t.key} onClick={() => setType(t.key)}
                className={cn('pb-1', type === t.key ? 'border-b-2 border-ink font-semibold' : 'text-sub')}>
                {t.label}
              </button>
            ))}
          </div>
          <span className="ml-auto text-[13px] text-sub">{state === 'ready' ? `${txs.length}건` : ''}</span>
          <button onClick={() => setAsc(!asc)} className="inline-flex items-center gap-1 text-[13px] font-medium text-sub" aria-label={`정렬: ${asc ? '오래된순' : '최신순'}, 눌러서 바꾸기`}>
            <ArrowDownUp className="size-3.5" />{asc ? '오래된순' : '최신순'}
          </button>
        </div>
      </section>

      {state === 'loading' && <ListSkeleton />}
      {state === 'error' && <ErrorState onRetry={retry} message="거래내역을 불러오지 못했어요." />}
      {state === 'ready' && (txs.length ? <TxList txs={txs} onSelect={setSelected} />
        : <EmptyState icon={Receipt} title="조회된 거래내역이 없어요" desc={searching ? '검색 조건을 바꾸거나 지워 보세요.' : '기간이나 필터를 바꿔 보세요.'} />)}

      <TxDetailSheet tx={selected} onClose={() => setSelected(null)} />
      <SearchSheet open={sheet === 'search'} onClose={() => setSheet(null)} value={query} onApply={(q) => { setQuery(q); setSheet(null); }} />
      <DownloadSheet open={sheet === 'download'} onClose={() => setSheet(null)} account={account} />
    </Page>
  );
}

function describe(q: Query) {
  const parts = [];
  if (q.q) parts.push(`"${q.q}"`);
  if (q.min || q.max) parts.push(`${q.min ? won(Number(q.min)) : ''}~${q.max ? won(Number(q.max)) : ''}`);
  if (q.kind !== 'all') parts.push(KINDS.find((k) => k.key === q.kind)!.label);
  return parts.join(' · ');
}

const digits = (v: string) => v.replace(/\D/g, '').slice(0, 10);

function SearchSheet({ open, onClose, value, onApply }: { open: boolean; onClose: () => void; value: Query; onApply: (q: Query) => void }) {
  const [q, setQ] = useState(value);
  const bad = q.min && q.max && Number(q.min) > Number(q.max);
  return (
    <Sheet open={open} onClose={onClose} title="거래 검색">
      <div className="space-y-4">
        <Field label="보낸 분·받는 분 또는 메모" placeholder="예: 홍길동, 월세" value={q.q} onChange={(e) => setQ({ ...q, q: e.target.value })} />
        <div>
          <span className="mb-2 block text-[13px] font-medium text-sub">금액</span>
          <div className="flex items-center gap-2">
            <input inputMode="numeric" aria-label="최소 금액" placeholder="최소" value={q.min ? Number(q.min).toLocaleString('ko-KR') : ''} onChange={(e) => setQ({ ...q, min: digits(e.target.value) })}
              className="num h-12 min-w-0 flex-1 rounded-xl border border-line px-3 text-[15px] outline-none focus:border-brand" />
            <span className="text-mute">~</span>
            <input inputMode="numeric" aria-label="최대 금액" placeholder="최대" value={q.max ? Number(q.max).toLocaleString('ko-KR') : ''} onChange={(e) => setQ({ ...q, max: digits(e.target.value) })}
              className="num h-12 min-w-0 flex-1 rounded-xl border border-line px-3 text-[15px] outline-none focus:border-brand" />
            <span className="text-[14px] text-sub">원</span>
          </div>
          {bad && <p role="alert" className="mt-1.5 text-[13px] text-danger">최소 금액이 최대 금액보다 커요.</p>}
        </div>
        <div>
          <span className="mb-2 block text-[13px] font-medium text-sub">거래 유형</span>
          <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="거래 유형">
            {KINDS.map((k) => (
              <button key={k.key} role="radio" aria-checked={q.kind === k.key} onClick={() => setQ({ ...q, kind: k.key })}
                className={cn('h-9 rounded-full px-3.5 text-[14px] font-medium', q.kind === k.key ? 'bg-navy text-white' : 'bg-surface text-sub')}>{k.label}</button>
            ))}
          </div>
        </div>
      </div>
      <div className="mt-6 grid grid-cols-[auto_1fr] gap-2">
        <Button size="lg" variant="secondary" onClick={() => setQ(EMPTY_Q)}>초기화</Button>
        <Button size="lg" disabled={!!bad} onClick={() => onApply(q)}>검색</Button>
      </div>
    </Sheet>
  );
}

const csvCell = (v: string | number) => {
  const text = typeof v === 'string' && /^[\s]*[=+\-@]/.test(v) ? `'${v}` : String(v);
  return `"${text.replace(/"/g, '""')}"`;
};

/** 서버에서 조회한 거래를 CSV로 받거나 이메일 발송을 신청한다. */
function DownloadSheet({ open, onClose, account }: { open: boolean; onClose: () => void; account: Account }) {
  const { db, user, toast, statement } = useBank();
  const [range, setRange] = useState(() => { const t = new Date(), f = new Date(); f.setMonth(f.getMonth() - 3); return { from: ymd(f), to: ymd(t) }; });
  const email = user?.email ?? '';
  const [sent, setSent] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const validRange = !!range.from && !!range.to && range.from <= range.to;
  const list = db.txs
    .filter((t) => validRange && t.accountId === account.id && new Date(t.date) >= new Date(`${range.from}T00:00`) && new Date(t.date) <= new Date(`${range.to}T23:59:59.999`))
    .sort((a, b) => a.date.localeCompare(b.date));

  async function send() {
    setBusy(true); setError('');
    try { await statement(account.id, range.from, range.to, email); setSent(email); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  function download() {
    const rows = [['거래일시', '구분', '유형', '상대', '금액', '거래 후 잔액', '메모', '거래번호'],
      ...list.map((t) => [fmtDateTime(t.date), t.type === 'in' ? '입금' : '출금', KINDS.find((k) => k.key === txKind(t))!.label, t.counterparty, t.type === 'in' ? t.amount : -t.amount, t.balanceAfter, t.memo ?? '', t.id.toUpperCase()])];
    const csv = '﻿' + rows.map((r) => r.map(csvCell).join(',')).join('\r\n'); // BOM: 엑셀에서 한글이 안 깨지게
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
    a.download = `내금고_${account.number}_${range.from}_${range.to}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    toast(`${list.length}건을 파일로 받았어요`);
  }

  return (
    <Sheet open={open} onClose={() => { setSent(''); setError(''); onClose(); }} title="거래내역 받기">
      <span className="mb-2 block text-[13px] font-medium text-sub">기간</span>
      <div className="flex items-center gap-2 text-[14px]">
        <input type="date" aria-label="시작일" value={range.from} max={range.to} onChange={(e) => setRange({ ...range, from: e.target.value })} className="h-11 flex-1 rounded-lg border border-line px-2" />
        <span className="text-mute">~</span>
        <input type="date" aria-label="종료일" value={range.to} min={range.from} max={ymd(new Date())} onChange={(e) => setRange({ ...range, to: e.target.value })} className="h-11 flex-1 rounded-lg border border-line px-2" />
      </div>
      <p className="mt-2 text-[13px] text-sub">이 기간 거래 {list.length}건</p>
      <Button full size="lg" variant="secondary" className="mt-4" disabled={!list.length} onClick={download}><Download className="size-4" />CSV 파일로 바로 받기</Button>

      <div className="mt-6 border-t border-line pt-5">
        <Field label="가입한 이메일로 받기" type="email" value={email} readOnly
          hint={sent ? <span className="text-success">{sent}로 거래내역을 발송했어요.</span> : undefined} />
        {error && <p role="alert" className="mt-2 text-[13px] text-danger">{error}</p>}
        <Button full size="lg" className="mt-3" loading={busy} disabled={!email || !validRange || !list.length || !!sent} onClick={() => void send()}>이메일로 신청</Button>
      </div>
    </Sheet>
  );
}
