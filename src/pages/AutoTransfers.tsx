import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { CircleAlert, CircleCheck, Plus, Repeat } from 'lucide-react';
import { PinSheet, RecipientPicker, shortName } from '../components/bank';
import { Button, Checkbox, EmptyState, Field, Page, Row, Sheet } from '../components/ui';
import type { AutoTransfer } from '../data/mock';
import { cn, fmtDateTime, formatAccountInput, won } from '../lib/format';
import { useBank } from '../store';

const WEEK = ['일', '월', '화', '수', '목', '금', '토'];
const ymd = (d: Date) => d.toLocaleDateString('sv-SE');
export const cycleText = (x: Pick<AutoTransfer, 'cycle' | 'day'>) => (x.cycle === 'weekly' ? `매주 ${WEEK[x.day]}요일` : `매월 ${x.day}일`);
const STATUS = { active: { label: '진행 중', cls: 'text-success' }, stopped: { label: '해지함', cls: 'text-sub' }, ended: { label: '기간 끝남', cls: 'text-sub' } };

/** 자동이체 목록: 다음 실행일, 최근 결과, 해지, 체험용 바로 실행 */
export function AutoTransfers() {
  const bank = useBank();
  const [stopId, setStopId] = useState<string | null>(null);
  const mine = bank.db.autoTransfers.filter((x) => x.owner === bank.user?.email);
  const active = mine.filter((x) => x.status === 'active');
  const past = mine.filter((x) => x.status !== 'active');
  const accName = (id: string) => shortName(bank.db.accounts.find((a) => a.id === id)?.name ?? '');
  const toLabel = (x: AutoTransfer) => { const own = bank.myAccounts.find((a) => a.number === x.toNumber); return own ? `내 ${shortName(own.name)}` : `${x.toName}님`; };


  return (
    <Page back title="자동이체" footer={<Link to="/auto-transfers/new" className="flex h-14 w-full items-center justify-center gap-1.5 rounded-full bg-brand text-[16px] font-semibold text-white hover:bg-brand-dark"><Plus className="size-5" />자동이체 등록</Link>}>
      {!mine.length && <EmptyState icon={Repeat} title="등록한 자동이체가 없어요" desc="월세·용돈처럼 정해진 날 보내는 돈을 자동으로 보내 드려요." />}
      {active.length > 0 && <h2 className="pt-2 text-[13px] font-medium text-sub">진행 중 {active.length}건</h2>}
      <ul className="divide-y divide-line">
        {active.map((x) => {
          const last = x.runs.at(-1);
          return (
            <li key={x.id} className="py-5">
              <div className="flex items-baseline justify-between gap-3">
                <p className="min-w-0 truncate text-[16px] font-bold">{toLabel(x)}{x.memo && <span className="ml-1.5 text-[14px] font-medium text-sub">{x.memo}</span>}</p>
                <p className="num shrink-0 font-display text-[18px] font-bold">{won(x.amount)}</p>
              </div>
              <p className="mt-1 text-[13px] text-sub">{cycleText(x)} · {accName(x.fromId)}에서{x.endDate && ` · ${x.endDate}까지`}</p>
              <p className="num mt-2 text-[14px]"><span className="text-sub">다음 이체</span> <b className="font-semibold">{fmtDateTime(x.nextRunAt)}</b></p>
              {last && (
                <p className={cn('mt-1 flex items-center gap-1 text-[13px]', last.ok ? 'text-success' : 'text-danger')}>
                  {last.ok ? <CircleCheck className="size-3.5" /> : <CircleAlert className="size-3.5" />}
                  <span className="num">{fmtDateTime(last.at)}</span> {last.ok ? '보냄' : `실패 · ${last.reason}`}
                </p>
              )}
              <div className="mt-3 flex gap-2">
                <Button size="sm" variant="ghost" className="text-danger" onClick={() => setStopId(x.id)}>해지</Button>
              </div>
            </li>
          );
        })}
      </ul>
      {past.length > 0 && (
        <details className="mt-6 border-t border-line pt-4 text-[14px]">
          <summary className="cursor-pointer list-none text-sub">끝난 자동이체 {past.length}건</summary>
          <ul className="mt-2">
            {past.map((x) => (
              <li key={x.id} className="flex justify-between py-2 text-sub">
                <span>{toLabel(x)} · {cycleText(x)} · <span className="num">{won(x.amount)}</span></span>
                <span className={STATUS[x.status].cls}>{STATUS[x.status].label}</span>
              </li>
            ))}
          </ul>
        </details>
      )}

      <Sheet open={!!stopId} onClose={() => setStopId(null)} title="자동이체 해지">
        <p className="text-[15px] leading-relaxed text-sub">해지하면 다음 회차부터 보내지 않아요. 이미 보낸 돈은 그대로예요.</p>
        <div className="mt-6 grid grid-cols-2 gap-2">
          <Button size="lg" variant="secondary" onClick={() => setStopId(null)}>취소</Button>
          <Button size="lg" variant="navy" onClick={async () => { try { await bank.stopAutoTransfer(stopId!); setStopId(null); bank.toast('자동이체를 해지했어요'); } catch (e) { bank.toast((e as Error).message); } }}>해지하기</Button>
        </div>
      </Sheet>
    </Page>
  );
}

/** 자동이체 등록: 출금 계좌·받는 계좌·금액·주기·기간 → 확인 → 간편비밀번호 */
export function NewAutoTransfer() {
  const bank = useBank();
  const navigate = useNavigate();
  const accounts = bank.myAccounts.filter((a) => a.status === 'active');
  const today = ymd(new Date());
  const [f, setF] = useState({ fromId: accounts[0]?.id ?? '', acct: '', amount: '', cycle: 'monthly' as AutoTransfer['cycle'], day: 25, startDate: today, endDate: '', noEnd: true, memo: '' });
  const [to, setTo] = useState<{ name: string; number: string } | null>(null);
  const [lookup, setLookup] = useState({ loading: false, error: '' });
  const [confirm, setConfirm] = useState(false);
  const [pin, setPin] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const set = (patch: Partial<typeof f>) => setF((p) => ({ ...p, ...patch }));
  const amount = Number(f.amount || 0);
  const from = accounts.find((a) => a.id === f.fromId);
  const dateErr = !f.noEnd && f.endDate && f.endDate < f.startDate ? '종료일은 시작일보다 뒤여야 해요.' : '';
  const ready = from && to && amount > 0 && f.startDate >= today && (f.noEnd || (f.endDate && !dateErr));

  async function verify(no = f.acct) {
    setLookup({ loading: true, error: '' }); setTo(null);
    try {
      const r = await bank.lookupAccount(no);
      if (from && r.number === from.number) throw new Error('출금 계좌와 같은 계좌예요.');
      setTo(r); setLookup({ loading: false, error: '' });
    } catch (e) { setLookup({ loading: false, error: (e as Error).message }); }
  }

  async function save(pinValue: string) {
    setBusy(true); setError('');
    try {
      await bank.createAutoTransfer({ fromId: f.fromId, toNumber: to!.number, amount, cycle: f.cycle, day: f.day, startDate: f.startDate, endDate: f.noEnd ? undefined : f.endDate, memo: f.memo.trim() || undefined }, pinValue);
      setPin(false);
      bank.toast('자동이체를 등록했어요');
      navigate('/auto-transfers', { replace: true });
    } catch (e) { if (['PIN', 'PIN_LOCKED', 'AUTH', 'LOGIN_LOCKED'].includes((e as { code?: string }).code ?? '')) throw e; setPin(false); setError((e as Error).message); setConfirm(true); } finally { setBusy(false); }
  }

  if (!accounts.length) return <Page back title="자동이체 등록"><EmptyState icon={Repeat} title="출금할 계좌가 없어요" desc="정상 상태인 내 계좌가 있어야 해요." /></Page>;

  return (
    <Page back title="자동이체 등록" footer={<Button size="lg" full disabled={!ready} loading={busy} onClick={() => setConfirm(true)}>다음</Button>}>
      <p className="pt-2 mb-2 text-[13px] font-medium text-sub">출금 계좌</p>
      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="출금 계좌">
        {accounts.map((a) => (
          <button key={a.id} role="radio" aria-checked={f.fromId === a.id} onClick={() => { set({ fromId: a.id }); setTo(null); }}
            className={cn('h-10 rounded-full px-4 text-[14px] font-medium', f.fromId === a.id ? 'bg-navy text-white' : 'bg-surface text-sub')}>{shortName(a.name)}</button>
        ))}
      </div>

      <label className="mt-6 block">
        <span className="mb-2 block text-[13px] font-medium text-sub">받는 계좌 (내금고)</span>
        <span className="flex gap-2">
          <input inputMode="numeric" placeholder="123-4567-8901" value={f.acct} aria-invalid={!!lookup.error}
            onChange={(e) => { set({ acct: formatAccountInput(e.target.value) }); setTo(null); setLookup({ loading: false, error: '' }); }}
            className={cn('num h-13 min-w-0 flex-1 rounded-xl border px-4 text-[17px] outline-none focus:border-brand', lookup.error ? 'border-danger' : 'border-line')} />
          <Button variant="navy" className="h-13" onClick={() => verify()} loading={lookup.loading} disabled={f.acct.length !== 13}>확인</Button>
        </span>
      </label>
      {lookup.error && <p role="alert" className="mt-2 text-[13px] text-danger">{lookup.error}</p>}
      {to && <p className="mt-2 flex items-center gap-1.5 text-[14px] text-success"><CircleCheck className="size-4" /><b>{to.name}</b>님 계좌예요</p>}
      {!to && <RecipientPicker excludeId={f.fromId} onPick={(n) => { set({ acct: n }); verify(n); }} />}

      <div className="mt-6">
        <span className="mb-2 block text-[13px] font-medium text-sub">금액</span>
        <label className="flex items-baseline gap-1 border-b-2 border-line pb-1 focus-within:border-brand">
          <input inputMode="numeric" placeholder="0" aria-label="금액" value={amount ? amount.toLocaleString('ko-KR') : ''} onChange={(e) => set({ amount: e.target.value.replace(/\D/g, '').slice(0, 10).replace(/^0+/, '') })}
            className="num w-full bg-transparent font-display text-[24px] font-bold outline-none placeholder:text-line" />
          <span className="font-display text-[20px] font-bold">원</span>
        </label>
      </div>

      <p className="mt-6 mb-2 text-[13px] font-medium text-sub">주기</p>
      <div className="grid grid-cols-2 gap-1 rounded-full bg-surface p-1" role="radiogroup" aria-label="주기">
        {([['monthly', '매월'], ['weekly', '매주']] as const).map(([v, l]) => (
          <button key={v} role="radio" aria-checked={f.cycle === v} onClick={() => set({ cycle: v, day: v === 'weekly' ? 5 : 25 })}
            className={cn('h-10 rounded-full text-[14px] font-semibold', f.cycle === v ? 'bg-paper text-ink shadow-sm' : 'text-sub')}>{l}</button>
        ))}
      </div>
      {f.cycle === 'monthly' ? (
        <label className="mt-3 flex items-center gap-2 text-[15px]">
          매월
          <select value={f.day} onChange={(e) => set({ day: Number(e.target.value) })} className="num h-11 rounded-xl border border-line px-3 outline-none focus:border-brand" aria-label="이체 날짜">
            {Array.from({ length: 31 }, (_, i) => <option key={i + 1} value={i + 1}>{i + 1}</option>)}
          </select>
          일 오전 9시
          {f.day > 28 && <span className="text-[12px] text-sub">· 그날이 없는 달은 말일</span>}
        </label>
      ) : (
        <div className="mt-3 flex gap-1.5" role="radiogroup" aria-label="요일">
          {WEEK.map((w, i) => (
            <button key={w} role="radio" aria-checked={f.day === i} onClick={() => set({ day: i })}
              className={cn('size-10 rounded-full text-[14px] font-semibold', f.day === i ? 'bg-navy text-white' : 'bg-surface text-sub')}>{w}</button>
          ))}
        </div>
      )}

      <div className="mt-6 grid grid-cols-2 gap-2">
        <Field label="시작일" type="date" min={today} value={f.startDate} onChange={(e) => set({ startDate: e.target.value })} />
        <Field label="종료일" type="date" min={f.startDate} value={f.endDate} disabled={f.noEnd} onChange={(e) => set({ endDate: e.target.value })} error={dateErr || undefined} />
      </div>
      <Checkbox checked={f.noEnd} onChange={(v) => set({ noEnd: v })}>종료일 없이 계속</Checkbox>
      <div className="mt-3"><Field label="메모 (선택)" maxLength={10} placeholder="예: 월세" value={f.memo} onChange={(e) => set({ memo: e.target.value })} /></div>
      <p className="mt-3 text-[12px] text-sub">보내는 날 잔액이나 이체한도가 모자라면 그 회차는 보내지 않고 알림으로 알려 드려요.</p>

      <Sheet open={confirm} onClose={() => setConfirm(false)} title="자동이체 확인">
        {from && to && (
          <div className="border-y border-line py-1">
            <Row label="받는 분">{to.name}</Row>
            <Row label="금액"><span className="num">{won(amount)}</span></Row>
            <Row label="주기">{cycleText(f)} 오전 9시</Row>
            <Row label="기간"><span className="num">{f.startDate} ~ {f.noEnd ? '종료일 없음' : f.endDate}</span></Row>
            <Row label="출금 계좌">{from.name}</Row>
          </div>
        )}
        {error && <p role="alert" className="mt-3 text-[13px] text-danger">{error}</p>}
        <Button full size="lg" className="mt-5" onClick={() => { setConfirm(false); setPin(true); }}>등록하기</Button>
      </Sheet>
      <PinSheet open={pin} onClose={() => setPin(false)} onPass={save} accountId={f.fromId} purpose="등록하려면" />
    </Page>
  );
}
