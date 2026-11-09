import { useRef, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { CalendarClock, Check, CircleAlert, CircleCheck, Landmark, Wallet } from 'lucide-react';
import { Button, EmptyState, Page, Row, Steps } from '../components/ui';
import { PinSheet, RecipientPicker, toneOf } from '../components/bank';
import { cn, fmtDateTime, formatAccountInput, won } from '../lib/format';
import { BankError, usageOf, useBank, type TransferResult } from '../store';

const STEP_LABELS = ['출금 계좌', '받는 계좌', '금액', '확인'];
type Recipient = { name: string; number: string; mine: boolean };

/** datetime-local 값(로컬 시각) */
const localInput = (d: Date) => new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
const tomorrow9 = () => { const d = new Date(); d.setDate(d.getDate() + 1); d.setHours(9, 0, 0, 0); return localInput(d); };

const FAIL_COPY: Record<string, { title: string; back: number; cta: string }> = {
  INVALID_TIME: { title: '예약 시각을 다시 골라 주세요', back: 3, cta: '시각 다시 고르기' },
  LIMIT: { title: '이체한도를 넘었어요', back: 2, cta: '금액 다시 입력' },
  SUSPENDED: { title: '거래가 중지된 계좌예요', back: 0, cta: '다른 계좌 고르기' },
  INSUFFICIENT: { title: '잔액이 부족해요', back: 2, cta: '금액 다시 입력' },
  INVALID_ACCOUNT: { title: '유효하지 않은 계좌예요', back: 1, cta: '계좌 다시 입력' },
  SAME_ACCOUNT: { title: '같은 계좌로는 보낼 수 없어요', back: 1, cta: '계좌 다시 입력' },
  NETWORK: { title: '송금하지 못했어요', back: 3, cta: '다시 시도' },
};

export function Transfer() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const bank = useBank();
  const preset = bank.myAccounts.find((a) => a.id === params.get('from') && a.status === 'active');

  const [step, setStep] = useState(preset ? 1 : 0); // 0~3 입력, 4 완료, 5 실패
  const [fromId, setFromId] = useState(preset?.id ?? '');
  const [acctInput, setAcctInput] = useState('');
  const [recipient, setRecipient] = useState<Recipient | null>(null);
  const [lookup, setLookup] = useState<{ loading: boolean; error?: string }>({ loading: false });
  const [amountStr, setAmountStr] = useState('');
  const [sending, setSending] = useState(false);
  const [pinOpen, setPinOpen] = useState(false);
  const [when, setWhen] = useState<'now' | 'later'>('now');
  const [runAt, setRunAt] = useState(tomorrow9);
  const [scheduledAt, setScheduledAt] = useState<string | null>(null);
  const [result, setResult] = useState<TransferResult | null>(null);
  const [fail, setFail] = useState<BankError | null>(null);
  const request = useRef({ fingerprint: '', key: '' });

  const from = bank.myAccounts.find((a) => a.id === fromId);
  const amount = Number(amountStr || 0);
  const usage = from ? usageOf(bank.db, from.id) : { today: 0, month: 0 };
  const left = from ? Math.min(from.limits.daily - usage.today, from.limits.monthly - usage.month) : 0;
  const over = !!from && amount > from.balance;
  // 내 계좌로 옮길 때는 한도를 보지 않는다
  const overLimit = !!from && !recipient?.mine && amount > left;

  const back = step > 0 && step < 4 ? () => setStep(step - 1) : true;

  if (!bank.myAccounts.length) {
    return <Page back title="송금"><EmptyState icon={Wallet} title="송금할 계좌가 없어요" action={<Button onClick={() => navigate('/products')}>통장 만들기</Button>} /></Page>;
  }

  async function verify() {
    setLookup({ loading: true });
    setRecipient(null);
    try {
      const r = await bank.lookupAccount(acctInput);
      if (from && r.number === from.number) throw new BankError('SAME_ACCOUNT', '출금 계좌와 같은 계좌예요. 다른 계좌를 입력해 주세요.');
      setRecipient(r);
      setLookup({ loading: false });
    } catch (e) {
      setLookup({ loading: false, error: (e as Error).message });
    }
  }

  async function send(pin: string) {
    if (!from || !recipient) return;
    const fingerprint = JSON.stringify({ fromId: from.id, toNumber: recipient.number, amount, when, runAt });
    if (request.current.fingerprint !== fingerprint) request.current = { fingerprint, key: crypto.randomUUID() };
    setSending(true);
    try {
      if (when === 'later') {
        const r = await bank.scheduleTransfer({ fromId: from.id, toNumber: recipient.number, amount, runAt: new Date(runAt).toISOString() }, pin, request.current.key);
        setScheduledAt(r.runAt);
      } else {
        setResult(await bank.transfer({ fromId: from.id, toNumber: recipient.number, amount }, pin, request.current.key));
      }
      setPinOpen(false); setStep(4);
    } catch (e) {
      if (e instanceof BankError && ['PIN', 'PIN_LOCKED', 'AUTH', 'LOGIN_LOCKED'].includes(e.code)) throw e;
      setPinOpen(false);
      setFail(e instanceof BankError ? e : new BankError('NETWORK', '알 수 없는 오류가 발생했어요.'));
      setStep(5);
    } finally {
      setSending(false);
    }
  }

  // ── 완료 / 실패 ──
  if (step === 4 && scheduledAt && from && recipient) {
    return (
      <Page footer={
        <div className="grid grid-cols-2 gap-2">
          <Button size="lg" variant="secondary" onClick={() => navigate('/notifications', { replace: true })}>예약 목록</Button>
          <Button size="lg" onClick={() => navigate('/', { replace: true })}>홈으로</Button>
        </div>
      }>
        <div className="rise flex flex-col items-center pt-28 text-center">
          <span className="grid size-16 place-items-center rounded-full bg-brand text-white"><CalendarClock className="size-8" /></span>
          <p className="mt-6 font-display text-[22px] leading-snug font-bold">{recipient.name}님에게<br /><span className="num">{won(amount)}</span> 송금을 예약했어요</p>
          <div className="mt-8 w-full rounded-2xl bg-surface px-5 py-3 text-left">
            <Row label="보낼 시각"><span className="num">{fmtDateTime(scheduledAt)}</span></Row>
            <Row label="받는 계좌"><span className="num">내금고 {recipient.number}</span></Row>
            <Row label="보낼 계좌">{from.name}</Row>
          </div>
          <p className="mt-4 text-[13px] text-sub">그때 잔액이 부족하면 보내지 않고 알림으로 알려 드려요.</p>
        </div>
      </Page>
    );
  }
  if (step === 4 && result && from) {
    return (
      <Page footer={
        <div className="grid grid-cols-2 gap-2">
          <Button size="lg" variant="secondary" onClick={() => navigate(`/accounts/${from.id}`, { replace: true })}>거래내역</Button>
          <Button size="lg" onClick={() => navigate('/', { replace: true })}>홈으로</Button>
        </div>
      }>
        <div className="rise flex flex-col items-center pt-28 text-center">
          <span className="grid size-16 place-items-center rounded-full bg-brand text-white"><Check className="size-8" strokeWidth={3} /></span>
          <p className="mt-6 font-display text-[22px] leading-snug font-bold">{result.toName}님에게<br /><span className="num">{won(amount)}</span>을 보냈어요</p>
          <div className="mt-8 w-full rounded-2xl bg-surface px-5 py-3 text-left">
            <Row label="받는 계좌"><span className="num">내금고 {result.toNumber}</span></Row>
            <Row label="보낸 계좌">{from.name}</Row>
            <Row label="출금 후 잔액"><span className="num">{won(result.balanceAfter)}</span></Row>
          </div>
        </div>
      </Page>
    );
  }
  if (step === 5 && fail) {
    const copy = FAIL_COPY[fail.code] ?? FAIL_COPY.NETWORK;
    return (
      <Page footer={
        <div className="grid grid-cols-2 gap-2">
          <Button size="lg" variant="secondary" onClick={() => navigate('/', { replace: true })}>홈으로</Button>
          <Button size="lg" onClick={() => { setFail(null); setStep(copy.back); }}>{copy.cta}</Button>
        </div>
      }>
        <div className="rise flex flex-col items-center pt-28 text-center">
          <span className="grid size-16 place-items-center rounded-full bg-danger-soft text-danger"><CircleAlert className="size-8" /></span>
          <p className="mt-6 font-display text-[22px] font-bold">{copy.title}</p>
          <p className="mt-2 text-[15px] text-sub">{fail.message}</p>
          <p className="mt-6 text-[13px] text-sub">{fail.code === 'NETWORK' ? '통신이 끊겨 결과가 아직 확인되지 않았어요. 거래내역을 먼저 확인해 주세요.' : '송금이 실행되지 않았고, 잔액은 그대로예요.'}</p>
        </div>
      </Page>
    );
  }

  // ── 입력 단계 ──
  const footer = [
    <Button size="lg" full disabled={!from || from.status !== 'active'} onClick={() => setStep(1)}>다음</Button>,
    <Button size="lg" full disabled={!recipient} onClick={() => setStep(2)}>다음</Button>,
    <Button size="lg" full disabled={!amount || over || overLimit} onClick={() => setStep(3)}>다음</Button>,
    <Button size="lg" full loading={sending} disabled={when === 'later' && !runAt} onClick={() => setPinOpen(true)}>{when === 'later' ? `${won(amount)} 예약하기` : `${won(amount)} 송금하기`}</Button>,
  ][step];

  return (
    <Page back={back} title="송금" footer={footer}>
      <Steps steps={STEP_LABELS} current={step} />

      {step === 0 && (
        <>
          <h2 className="mb-5 font-display text-[22px] font-bold">어느 계좌에서 보낼까요?</h2>
          <div className="space-y-2" role="radiogroup" aria-label="출금 계좌">
            {bank.myAccounts.map((a) => (
              <button key={a.id} role="radio" aria-checked={fromId === a.id} onClick={() => setFromId(a.id)} disabled={a.status !== 'active'}
                className={cn('flex w-full items-center gap-3 rounded-2xl border-2 p-4 text-left transition-colors disabled:opacity-50', fromId === a.id ? 'border-brand bg-brand-soft' : 'border-transparent bg-surface')}>
                <span className={cn('grid size-10 place-items-center rounded-full text-navy', toneOf(bank.myAccounts, a.id))}><Wallet className="size-5" /></span>
                <span className="flex-1">
                  <span className="block text-[15px] font-semibold">{a.name}</span>
                  <span className="num block text-[13px] text-sub">{a.number}{a.status === 'suspended' && <span className="ml-1.5 font-semibold text-danger">거래중지</span>}</span>
                </span>
                <span className="num text-[15px] font-semibold">{won(a.balance)}</span>
              </button>
            ))}
          </div>
        </>
      )}

      {step === 1 && (
        <>
          <h2 className="mb-5 font-display text-[22px] font-bold">어디로 보낼까요?</h2>
          <p className="mb-2 text-[13px] font-medium text-sub">은행</p>
          <div className="grid grid-cols-2 gap-2">
            <span className="flex h-12 items-center gap-2 rounded-xl border-2 border-brand bg-brand-soft px-4 text-[15px] font-semibold"><Landmark className="size-4 text-brand" />내금고</span>
            <span className="flex h-12 items-center justify-between rounded-xl bg-surface px-4 text-[14px] text-sub" aria-disabled="true">다른 은행<span className="text-[12px]">준비 중</span></span>
          </div>
          <p className="mt-2 text-[12px] text-sub">MVP에서는 내금고 계좌로만 송금할 수 있어요.</p>

          <label className="mt-6 block">
            <span className="mb-2 block text-[13px] font-medium text-sub">계좌번호</span>
            <span className="flex gap-2">
              <input inputMode="numeric" placeholder="123-4567-8901" value={acctInput}
                onChange={(e) => { setAcctInput(formatAccountInput(e.target.value)); setRecipient(null); setLookup({ loading: false }); }}
                onKeyDown={(e) => e.key === 'Enter' && acctInput.length === 13 && verify()}
                aria-invalid={!!lookup.error}
                className={cn('num h-13 min-w-0 flex-1 rounded-xl border px-4 text-[17px] outline-none focus:border-brand', lookup.error ? 'border-danger' : 'border-line')} />
              <Button variant="navy" className="h-13" onClick={verify} loading={lookup.loading} disabled={acctInput.length !== 13}>확인</Button>
            </span>
          </label>

          {lookup.error && <p role="alert" className="mt-3 flex items-center gap-1.5 rounded-xl bg-danger-soft px-4 py-3 text-[14px] text-danger"><CircleAlert className="size-4 shrink-0" />{lookup.error}</p>}
          {recipient && (
            <div className="rise mt-3 flex items-center gap-3 rounded-2xl bg-success-soft px-4 py-3">
              <CircleCheck className="size-5 text-success" />
              <span className="text-[15px]"><b>{recipient.name}</b>님의 계좌가 맞나요?{recipient.mine && <span className="ml-1 text-[13px] text-sub">(내 계좌)</span>}</span>
            </div>
          )}

          <RecipientPicker excludeId={fromId} testChip onPick={(n) => { setAcctInput(n); setRecipient(null); setLookup({ loading: false }); }} />
        </>
      )}

      {step === 2 && from && recipient && (
        <>
          <h2 className="font-display text-[22px] font-bold">{recipient.name}님에게<br />얼마를 보낼까요?</h2>
          <label className="mt-8 block border-b-2 border-line pb-2 focus-within:border-brand">
            <span className="sr-only">송금 금액</span>
            <span className="flex items-baseline gap-1">
              <input inputMode="numeric" autoFocus placeholder="0" value={amount ? amount.toLocaleString('ko-KR') : ''}
                onChange={(e) => setAmountStr(e.target.value.replace(/\D/g, '').slice(0, 10).replace(/^0+/, ''))}
                className={cn('num w-full min-w-0 bg-transparent font-display text-[34px] font-bold outline-none placeholder:text-line', over && 'text-danger')} />
              <span className="font-display text-[24px] font-bold">원</span>
            </span>
          </label>
          {over ? (
            <p role="alert" className="mt-2 flex items-center gap-1 text-[14px] text-danger"><CircleAlert className="size-4" />출금 가능 금액을 초과했어요.</p>
          ) : overLimit ? (
            <p role="alert" className="num mt-2 flex items-center gap-1 text-[14px] text-danger"><CircleAlert className="size-4" />이체한도를 넘어요. 지금은 {won(Math.max(0, left))}까지 보낼 수 있어요.</p>
          ) : (
            <p className="num mt-2 text-[14px] text-sub">출금 가능 금액 {won(from.balance)}{!recipient.mine && <> · 남은 한도 {won(Math.max(0, left))}</>}</p>
          )}
          <div className="mt-6 grid grid-cols-5 gap-2">
            {[10000, 50000, 100000, 1000000].map((v) => (
              <button key={v} onClick={() => setAmountStr(String(amount + v))} className="h-10 rounded-full bg-surface text-[13px] font-medium hover:bg-line">+{v >= 10000 ? `${v / 10000}만` : v}</button>
            ))}
            <button onClick={() => setAmountStr(String(from.balance))} className="h-10 rounded-full bg-brand-soft text-[13px] font-semibold text-brand">전액</button>
          </div>
          {amount > 0 && <button onClick={() => setAmountStr('')} className="mt-3 text-[13px] text-sub underline">금액 지우기</button>}
        </>
      )}

      {step === 3 && from && recipient && (
        <>
          <h2 className="font-display text-[22px] leading-snug font-bold">{recipient.name}님에게<br /><span className="num text-brand">{won(amount)}</span>을 보낼까요?</h2>
          <div className="mt-8 rounded-2xl bg-surface px-5 py-3">
            <Row label="보내는 계좌"><span className="block">{from.name}</span><span className="num block text-[13px] font-normal text-sub">{from.number}</span></Row>
            <Row label="받는 분">{recipient.name}</Row>
            <Row label="받는 계좌"><span className="num">내금고 {recipient.number}</span></Row>
            <Row label="송금 금액"><span className="num">{won(amount)}</span></Row>
            <Row label="수수료"><span className="num">0원</span></Row>
            <div className="my-1 border-t border-line" />
            <Row label="송금 후 잔액"><span className="num">{won(from.balance - amount)}</span></Row>
          </div>

          <p className="mt-6 mb-2 text-[13px] font-medium text-sub">보내는 시점</p>
          <div className="grid grid-cols-2 gap-1 rounded-full bg-surface p-1" role="radiogroup" aria-label="보내는 시점">
            {([['now', '지금 보내기'], ['later', '예약하기']] as const).map(([v, label]) => (
              <button key={v} role="radio" aria-checked={when === v} onClick={() => setWhen(v)}
                className={cn('h-10 rounded-full text-[14px] font-semibold transition-colors', when === v ? 'bg-paper text-ink shadow-sm' : 'text-sub')}>{label}</button>
            ))}
          </div>
          {when === 'later' && (
            <div className="rise mt-3">
              <input type="datetime-local" value={runAt} min={localInput(new Date())} onChange={(e) => setRunAt(e.target.value)} aria-label="보낼 날짜와 시각"
                className="num h-12 w-full rounded-xl border border-line px-4 text-[16px] outline-none focus:border-brand" />
              <div className="mt-2 flex gap-2">
                {[['1분 뒤', 1], ['내일 9시', 0]].map(([label, min]) => (
                  <button key={label} onClick={() => setRunAt(min ? localInput(new Date(Date.now() + 90_000)) : tomorrow9())}
                    className="h-8 rounded-full bg-surface px-3 text-[13px] text-sub hover:bg-line">{label}</button>
                ))}
              </div>
              <p className="mt-2 text-[12px] text-sub">"1분 뒤"는 예약이 실행되는 걸 바로 보는 체험용이에요.</p>
            </div>
          )}
          <p className="mt-4 text-[13px] text-sub">가상 송금이에요. 실제 돈은 이동하지 않아요.</p>
          <PinSheet accountId={from.id} open={pinOpen} onClose={() => setPinOpen(false)} onPass={send} />
        </>
      )}
    </Page>
  );
}
