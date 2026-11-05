import { useRef, useState, type ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Check, ChevronLeft, ChevronRight, CreditCard, Plus, ReceiptText, SearchX, Settings2, Wallet } from 'lucide-react';
import { CARD_STATUS, CheckCard, PinSheet, markOf, shortName } from '../components/bank';
import { Button, EmptyState, ErrorState, ListSkeleton, Page, Sheet, Steps } from '../components/ui';
import { CARD_LIMITS, type Card, type CardTheme } from '../data/mock';
import { cn, fmtDay, fmtTime, groupByDay, won } from '../lib/format';
import { cardUsedToday, useBank, useLoad } from '../store';
import { Meter } from './AccountManage';

const STATUS_CLS: Record<Card['status'], string> = { active: 'text-success', paused: 'text-sub', lost: 'text-danger', terminated: 'text-sub' };
const DOT_CLS: Record<Card['status'], string> = { active: 'bg-success', paused: 'bg-mute', lost: 'bg-danger', terminated: 'bg-mute' };
const short = (n: number) => `${n / 10_000}만원`;

function StatusText({ card }: { card: Card }) {
  return (
    <span className={cn('inline-flex items-center gap-1 text-[13px] font-semibold', STATUS_CLS[card.status])}>
      <span aria-hidden className={cn('size-1.5 rounded-full', DOT_CLS[card.status])} />{CARD_STATUS[card.status]}
    </span>
  );
}

export function CardList() {
  const { myCards, myAccounts, db } = useBank();
  const navigate = useNavigate();
  return (
    <Page title="카드" nav>
      {!myCards.length && <EmptyState icon={CreditCard} title="보유한 카드가 없어요" desc="계좌에 연결해 체크카드를 바로 발급할 수 있어요." />}
      <ul className="space-y-9 pt-2">
        {myCards.map((c) => {
          const acc = db.accounts.find((a) => a.id === c.accountId);
          return (
            <li key={c.id}>
              <CheckCard card={c} />
              <div className="mt-3 flex items-center justify-between gap-3">
                <div className="min-w-0">
                  <p className="flex items-center gap-2 text-[16px] font-bold">{c.name}<StatusText card={c} /></p>
                  <p className="mt-0.5 flex items-center gap-1.5 text-[13px] text-sub">
                    <span className="num">•••• {c.last4}</span>
                    {acc && <>· <span aria-hidden className={cn('h-3 w-1 rounded-full', markOf(myAccounts, acc.id))} />{shortName(acc.name)} 연결</>}
                  </p>
                </div>
                <Button size="sm" variant="outline" onClick={() => navigate(`/cards/${c.id}`)}>사용내역<ChevronRight className="-mr-1 size-4" /></Button>
              </div>
            </li>
          );
        })}
      </ul>
      <Link to="/cards/new" className="mt-9 flex items-center justify-center gap-1.5 rounded-2xl border border-dashed border-line py-4 text-[15px] font-semibold text-sub hover:bg-surface">
        <Plus className="size-5" />체크카드 발급
      </Link>
    </Page>
  );
}

type PinAction = { purpose: string; run: (pin: string) => Promise<void> };

/** 카드 상세: 상태 관리(일시정지·분실 신고·재발급·해지), 한도·해외결제·알림 설정, 가상 결제, 사용내역 */
export function CardDetail() {
  const { id } = useParams();
  const bank = useBank();
  const navigate = useNavigate();
  const card = bank.myCards.find((c) => c.id === id);
  const [pinAction, setPinAction] = useState<PinAction | null>(null);
  const [sheet, setSheet] = useState<null | 'manage' | 'limit' | 'lost' | 'terminate' | 'pay'>(null);
  const [error, setError] = useState('');

  if (!card) return <Page back title="카드" nav><EmptyState icon={SearchX} title="카드를 찾을 수 없어요" desc="해지했거나 내 카드가 아니에요." action={<Button onClick={() => navigate('/cards')}>카드 목록</Button>} /></Page>;
  const acc = bank.db.accounts.find((a) => a.id === card.accountId);
  const usable = card.status === 'active' || card.status === 'paused';
  const used = cardUsedToday(bank.db, card.id);

  /** 간편비밀번호를 거쳐야 하는 일 */
  const withPin = (purpose: string, run: (pin: string) => Promise<void>) => { setSheet(null); setError(''); setPinAction({ purpose, run }); };

  return (
    <Page back title={card.name} nav right={
      <button onClick={() => { setError(''); setSheet('manage'); }} className="mr-1 inline-flex h-9 items-center gap-1 rounded-full px-3 text-[14px] font-semibold text-navy hover:bg-surface">
        <Settings2 className="size-[18px]" />관리
      </button>
    }>
      <section className="flex items-center gap-4 pt-2">
        <CheckCard card={card} small />
        <div className="min-w-0">
          <p className="num text-[15px] font-semibold">•••• {card.last4}</p>
          {acc && <p className="truncate text-[13px] text-sub">{shortName(acc.name)} 연결</p>}
          <p className="mt-1"><StatusText card={card} /></p>
        </div>
      </section>

      {card.status === 'lost' && (
        <p className="mt-4 rounded-2xl bg-danger-soft px-4 py-3 text-[14px] leading-relaxed text-danger">분실 신고한 카드예요. 결제가 모두 막혀 있고, 관리에서 재발급하면 새 번호로 다시 쓸 수 있어요.</p>
      )}
      {error && sheet !== 'manage' && <p role="alert" className="mt-3 text-[13px] text-danger">{error}</p>}

      <History card={card} />

      <Sheet open={sheet === 'manage'} onClose={() => setSheet(null)} title="카드 관리">
        <div className="grid grid-cols-3 gap-2">
          {card.status === 'active' && <Action onClick={() => withPin('일시정지하려면', async (pin) => { await bank.setCardPaused(card.id, true, pin); bank.toast('카드를 일시정지했어요'); })}>일시정지</Action>}
          {card.status === 'paused' && <Action onClick={() => withPin('다시 쓰려면', async (pin) => { await bank.setCardPaused(card.id, false, pin); bank.toast('카드를 다시 쓸 수 있어요'); })}>다시 쓰기</Action>}
          {usable && <Action danger onClick={() => setSheet('lost')}>분실 신고</Action>}
          <Action onClick={() => withPin('재발급하려면', async (pin) => { const n = await bank.reissueCard(card.id, pin); bank.toast(`새 카드 ••${n.last4}를 발급했어요`); navigate(`/cards/${n.id}`, { replace: true }); })}>재발급</Action>
        </div>
        {error && <p role="alert" className="mt-3 text-[13px] text-danger">{error}</p>}

        <section className="mt-5 border-t border-line">
          <div className="py-4">
            <div className="flex items-center justify-between">
              <h3 className="text-[15px] font-semibold">1일 사용한도</h3>
              <Button size="sm" variant="outline" disabled={!usable} onClick={() => setSheet('limit')}>변경</Button>
            </div>
            <Meter label="오늘" used={used} limit={card.dailyLimit} />
          </div>
          <Toggle label="해외결제" desc="꺼 두면 해외 가맹점 결제가 승인되지 않아요" on={card.overseas} disabled={!usable}
            onChange={(v) => withPin('해외결제 설정을 바꾸려면', async (pin) => { await bank.updateCard(card.id, { overseas: v }, pin); bank.toast(v ? '해외결제를 켰어요' : '해외결제를 껐어요'); })} />
          <p className="border-t border-line py-4 text-[13px] text-sub">카드 결제 결과는 알림 화면에서 확인할 수 있어요.</p>
        </section>

        <button onClick={() => setSheet('pay')} disabled={card.status === 'lost'} className="mt-2 w-full rounded-2xl bg-surface py-3.5 text-[14px] font-semibold text-navy hover:bg-line disabled:opacity-40">
          가상 결제 해 보기 <span className="font-normal text-sub">· 체험용</span>
        </button>
        <button onClick={() => setSheet('terminate')} className="mt-4 flex w-full items-center justify-between border-t border-line pt-4 text-[15px] font-semibold text-danger">
          카드 해지<ChevronRight className="size-5" />
        </button>
      </Sheet>

      <LimitSheet open={sheet === 'limit'} onClose={() => setSheet('manage')} current={card.dailyLimit}
        onPick={(v) => withPin('한도를 바꾸려면', async (pin) => { await bank.updateCard(card.id, { dailyLimit: v }, pin); bank.toast(`1일 한도를 ${short(v)}으로 바꿨어요`); })} />
      <ConfirmSheet open={sheet === 'lost'} onClose={() => setSheet('manage')} title="분실 신고" cta="분실 신고하기"
        onConfirm={() => withPin('분실 신고하려면', async (pin) => { await bank.reportLost(card.id, pin); bank.toast('분실 신고했어요. 결제가 바로 막혔어요'); })}>
        신고하는 즉시 이 카드의 모든 결제가 막혀요. 분실 신고는 되돌릴 수 없고, 다시 쓰려면 재발급해야 해요.
      </ConfirmSheet>
      <ConfirmSheet open={sheet === 'terminate'} onClose={() => setSheet('manage')} title="카드 해지" cta="해지하기"
        onConfirm={() => withPin('해지하려면', async (pin) => { await bank.terminateCard(card.id, pin); bank.toast('카드를 해지했어요'); navigate('/cards', { replace: true }); })}>
        해지한 카드는 다시 쓸 수 없어요. 연결 계좌({acc ? shortName(acc.name) : '-'})는 그대로 남고, 다른 카드가 없으면 계좌도 해지할 수 있게 돼요.
      </ConfirmSheet>
      <PaySheet open={sheet === 'pay'} onClose={() => setSheet('manage')} card={card} />

      <PinSheet open={!!pinAction} onClose={() => setPinAction(null)} purpose={pinAction?.purpose}
        onPass={async (pin) => { if (pinAction) await pinAction.run(pin); setPinAction(null); }} />
    </Page>
  );
}

function Action({ children, onClick, danger }: { children: ReactNode; onClick: () => void; danger?: boolean }) {
  return <button onClick={onClick} className={cn('h-11 rounded-xl bg-surface text-[14px] font-semibold hover:bg-line', danger ? 'text-danger' : 'text-navy')}>{children}</button>;
}

function Toggle({ label, desc, on, disabled, onChange }: { label: string; desc: string; on: boolean; disabled?: boolean; onChange: (v: boolean) => void }) {
  return (
    <label className={cn('flex items-center justify-between gap-4 border-t border-line py-4', disabled ? 'opacity-50' : 'cursor-pointer')}>
      <span>
        <span className="block text-[15px] font-semibold">{label}</span>
        <span className="block text-[13px] text-sub">{desc}</span>
      </span>
      <input type="checkbox" role="switch" checked={on} disabled={disabled} onChange={(e) => onChange(e.target.checked)} className="size-5 shrink-0 accent-brand" />
    </label>
  );
}

function ConfirmSheet({ open, onClose, title, cta, onConfirm, children }: { open: boolean; onClose: () => void; title: string; cta: string; onConfirm: () => void; children: ReactNode }) {
  return (
    <Sheet open={open} onClose={onClose} title={title}>
      <p className="text-[15px] leading-relaxed text-sub">{children}</p>
      <div className="mt-6 grid grid-cols-2 gap-2">
        <Button size="lg" variant="secondary" onClick={onClose}>취소</Button>
        <Button size="lg" variant="navy" onClick={onConfirm}>{cta}</Button>
      </div>
    </Sheet>
  );
}

function LimitSheet({ open, onClose, current, onPick }: { open: boolean; onClose: () => void; current: number; onPick: (v: number) => void }) {
  const [v, setV] = useState(current);
  return (
    <Sheet open={open} onClose={onClose} title="1일 사용한도">
      <LimitPicker value={v} onChange={setV} />
      <Button full size="lg" className="mt-6" disabled={v === current} onClick={() => onPick(v)}>{short(v)}으로 바꾸기</Button>
    </Sheet>
  );
}

function LimitPicker({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  return (
    <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="1일 사용한도">
      {CARD_LIMITS.map((l) => (
        <button key={l} type="button" role="radio" aria-checked={value === l} onClick={() => onChange(l)}
          className={cn('num h-11 rounded-xl border-2 text-[14px] font-semibold', value === l ? 'border-brand bg-brand-soft text-ink' : 'border-transparent bg-surface text-sub')}>
          {short(l)}
        </button>
      ))}
    </div>
  );
}

const PAY_PRESETS = [
  { merchant: '하늘커피 역삼점', category: '카페', amount: 4_800, overseas: false },
  { merchant: '동네마트', category: '장보기', amount: 32_000, overseas: false },
  { merchant: 'Global Online Store', category: '쇼핑', amount: 59_000, overseas: true },
];

/** 가상 결제: 상태·해외결제·한도·잔액 규칙이 실제로 걸리는지 보여 주는 체험용 */
function PaySheet({ open, onClose, card }: { open: boolean; onClose: () => void; card: Card }) {
  const bank = useBank();
  const [pick, setPick] = useState(0);
  const [amount, setAmount] = useState(String(PAY_PRESETS[0].amount));
  const [result, setResult] = useState<{ ok: boolean; msg: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const p = PAY_PRESETS[pick];
  const submitting = useRef(false);

  async function pay() {
    if (submitting.current || result?.ok) return;
    submitting.current = true;
    setBusy(true); setResult(null);
    try {
      await bank.payWithCard(card.id, { ...p, amount: Number(amount) });
      setResult({ ok: true, msg: `${p.merchant}에서 ${won(Number(amount))} 결제가 승인됐어요.${card.notify ? ' 알림에도 남았어요.' : ''}` });
    } catch (e) { setResult({ ok: false, msg: (e as Error).message }); }
    finally { submitting.current = false; setBusy(false); }
  }

  return (
    <Sheet open={open} onClose={() => { setResult(null); onClose(); }} title="가상 결제">
      <p className="text-[14px] text-sub">실제 결제는 일어나지 않아요. 연결 계좌의 가상 잔액에서 빠져나가요.</p>
      <div className="mt-4 space-y-2" role="radiogroup" aria-label="가맹점">
        {PAY_PRESETS.map((x, i) => (
          <button key={x.merchant} role="radio" aria-checked={pick === i} disabled={busy || result?.ok} onClick={() => { setPick(i); setAmount(String(x.amount)); setResult(null); }}
            className={cn('flex w-full items-center justify-between rounded-xl border-2 px-4 py-3 text-left text-[14px]', pick === i ? 'border-brand bg-brand-soft' : 'border-transparent bg-surface')}>
            <span><span className="font-semibold">{x.merchant}</span>{x.overseas && <span className="ml-1.5 text-[12px] font-semibold text-brand">해외</span>}</span>
            <span className="text-sub">{x.category}</span>
          </button>
        ))}
      </div>
      <label className="mt-4 flex items-baseline gap-1 border-b-2 border-line pb-1 focus-within:border-brand">
        <span className="sr-only">결제 금액</span>
        <input inputMode="numeric" disabled={busy || result?.ok} value={Number(amount || 0).toLocaleString('ko-KR')} onChange={(e) => { setAmount(e.target.value.replace(/\D/g, '').slice(0, 8)); setResult(null); }}
          className="num w-full bg-transparent font-display text-[24px] font-bold outline-none" />
        <span className="font-display text-[18px] font-bold">원</span>
      </label>
      {result && (
        <p role="alert" className={cn('mt-3 flex items-start gap-1.5 rounded-xl px-4 py-3 text-[14px]', result.ok ? 'bg-success-soft text-success' : 'bg-danger-soft text-danger')}>
          {result.ok && <Check className="mt-0.5 size-4 shrink-0" />}{result.msg}
        </p>
      )}
      <Button full size="lg" className="mt-5" loading={busy} disabled={!Number(amount) || result?.ok} onClick={pay}>{result?.ok ? '결제 완료' : '결제하기'}</Button>
    </Sheet>
  );
}

function History({ card }: { card: Card }) {
  const { db } = useBank();
  const now = new Date();
  const [ym, setYm] = useState({ y: now.getFullYear(), m: now.getMonth() });
  const { state, retry } = useLoad([ym.y, ym.m]);
  const isCurrent = ym.y === now.getFullYear() && ym.m === now.getMonth();
  const shift = (d: number) => setYm(({ y, m }) => { const t = new Date(y, m + d, 1); return { y: t.getFullYear(), m: t.getMonth() }; });
  const list = db.cardTxs
    .filter((t) => { const d = new Date(t.date); return t.cardId === card.id && d.getFullYear() === ym.y && d.getMonth() === ym.m; })
    .sort((a, b) => b.date.localeCompare(a.date));
  const total = list.reduce((s, t) => s + t.amount, 0);

  return (
    <section className="mt-6">
      <h2 className="text-[18px] font-bold">사용내역</h2>
      <div className="mt-3 flex items-center justify-between">
        <button onClick={() => shift(-1)} aria-label="이전 달" className="grid size-9 place-items-center rounded-full hover:bg-surface"><ChevronLeft className="size-5" /></button>
        <p className="text-[16px] font-semibold">{ym.y}년 {ym.m + 1}월</p>
        <button onClick={() => shift(1)} disabled={isCurrent} aria-label="다음 달" className="grid size-9 place-items-center rounded-full hover:bg-surface disabled:opacity-30"><ChevronRight className="size-5" /></button>
      </div>
      <div className="mt-2 border-b border-line pb-5 text-center">
        <p className="text-[14px] text-sub">{isCurrent ? '이번 달' : `${ym.m + 1}월`} 사용 금액{state === 'ready' && ` · ${list.length}건`}</p>
        <p className="num mt-1 font-display text-[30px] font-bold text-navy">{state === 'ready' ? won(total) : '–'}</p>
      </div>
      {state === 'loading' && <ListSkeleton />}
      {state === 'error' && <ErrorState onRetry={retry} message="사용내역을 불러오지 못했어요." />}
      {state === 'ready' && (list.length ? (
        <div className="mt-2">
          {groupByDay(list).map((g) => (
            <section key={g[0].date} className="border-b border-line/60 py-2 last:border-0">
              <h3 className="pt-2 text-[13px] font-medium text-sub">{fmtDay(g[0].date)}</h3>
              {g.map((t) => (
                <div key={t.id} className="flex items-center gap-3 py-3">
                  <span className="flex-1">
                    <span className="block text-[15px] font-medium">{t.merchant}</span>
                    <span className="block text-[13px] text-sub">{fmtTime(t.date)} · {t.category}</span>
                  </span>
                  <span className="num text-[15px] font-semibold">{won(t.amount)}</span>
                </div>
              ))}
            </section>
          ))}
        </div>
      ) : (
        <EmptyState icon={ReceiptText} title={`${ym.m + 1}월 사용내역이 없어요`} desc={card.status === 'active' ? '카드로 결제하면 여기에 표시돼요.' : '지금은 이 카드로 결제할 수 없어요.'} />
      ))}
    </section>
  );
}

const THEMES: { id: CardTheme; label: string }[] = [{ id: 'navy', label: '미드나이트' }, { id: 'sky', label: '라벤더' }, { id: 'slate', label: '샌드' }];

/** 체크카드 발급: 연결 계좌 → 한도·해외결제·디자인 → 확인 + 간편비밀번호 */
export function IssueCard() {
  const bank = useBank();
  const navigate = useNavigate();
  const accounts = bank.myAccounts.filter((a) => a.status === 'active');
  const [step, setStep] = useState(0);
  const [f, setF] = useState({ accountId: accounts[0]?.id ?? '', dailyLimit: 1_000_000, overseas: false, theme: 'navy' as CardTheme });
  const [pin, setPin] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [issued, setIssued] = useState<Card | null>(null);
  const acc = accounts.find((a) => a.id === f.accountId);

  if (!accounts.length) return <Page back title="체크카드 발급"><EmptyState icon={Wallet} title="연결할 계좌가 없어요" desc="정상 상태인 내 계좌가 있어야 카드를 만들 수 있어요." action={<Button onClick={() => navigate('/products')}>통장 만들기</Button>} /></Page>;

  async function issue(pinValue: string) {
    setBusy(true); setError('');
    try { await bank.verifyPin(pinValue, f.accountId); setIssued(await bank.issueCard(f)); setPin(false); } catch (e) { throw e; } finally { setBusy(false); }
  }

  if (issued) {
    return (
      <Page footer={<div className="grid grid-cols-2 gap-2">
        <Button size="lg" variant="secondary" onClick={() => navigate('/cards', { replace: true })}>카드 목록</Button>
        <Button size="lg" onClick={() => navigate(`/cards/${issued.id}`, { replace: true })}>카드 관리</Button>
      </div>}>
        <div className="rise pt-16 text-center">
          <CheckCard card={issued} />
          <p className="mt-8 font-display text-[22px] font-bold">체크카드를 발급했어요</p>
          <p className="mt-2 text-[14px] text-sub">바로 쓸 수 있는 가상 카드예요. 실물 카드는 발송되지 않아요.</p>
        </div>
      </Page>
    );
  }

  const footer = [
    <Button size="lg" full disabled={!acc} onClick={() => setStep(1)}>다음</Button>,
    <Button size="lg" full onClick={() => setStep(2)}>다음</Button>,
    <Button size="lg" full loading={busy} onClick={() => setPin(true)}>발급하기</Button>,
  ][step];
  const preview: Card = { id: 'preview', owner: '', name: '내금고 체크카드', last4: '0000', status: 'active', notify: true, ...f };

  return (
    <Page back={step > 0 ? () => setStep(step - 1) : true} title="체크카드 발급" footer={footer}>
      <Steps steps={['연결 계좌', '설정', '확인']} current={step} />

      {step === 0 && (
        <>
          <h2 className="mb-5 font-display text-[22px] font-bold">어느 계좌에서 결제할까요?</h2>
          <div className="space-y-2" role="radiogroup" aria-label="연결 계좌">
            {accounts.map((a) => (
              <button key={a.id} role="radio" aria-checked={f.accountId === a.id} onClick={() => setF({ ...f, accountId: a.id })}
                className={cn('flex w-full items-center justify-between rounded-2xl border-2 p-4 text-left', f.accountId === a.id ? 'border-brand bg-brand-soft' : 'border-transparent bg-surface')}>
                <span>
                  <span className="block text-[15px] font-semibold">{a.name}</span>
                  <span className="num block text-[13px] text-sub">{a.number}</span>
                </span>
                <span className="num text-[15px] font-semibold">{won(a.balance)}</span>
              </button>
            ))}
          </div>
          <p className="mt-3 text-[13px] text-sub">체크카드는 연결 계좌 잔액 안에서만 결제돼요.</p>
        </>
      )}

      {step === 1 && (
        <>
          <h2 className="font-display text-[22px] font-bold">카드를 설정해 주세요</h2>
          <p className="mt-6 mb-2 text-[13px] font-medium text-sub">1일 사용한도</p>
          <LimitPicker value={f.dailyLimit} onChange={(v) => setF({ ...f, dailyLimit: v })} />
          <div className="mt-6 border-b border-line">
            <Toggle label="해외결제" desc="해외 가맹점·해외 온라인 결제" on={f.overseas} onChange={(v) => setF({ ...f, overseas: v })} />
          </div>
          <p className="mt-6 mb-2 text-[13px] font-medium text-sub">디자인</p>
          <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="카드 디자인">
            {THEMES.map((t) => (
              <button key={t.id} role="radio" aria-checked={f.theme === t.id} onClick={() => setF({ ...f, theme: t.id })}
                className={cn('rounded-xl border-2 p-1.5 text-[13px]', f.theme === t.id ? 'border-brand font-semibold' : 'border-transparent text-sub')}>
                <CheckCard card={{ ...preview, theme: t.id }} small />
                <span className="mt-1.5 block">{t.label}</span>
              </button>
            ))}
          </div>
        </>
      )}

      {step === 2 && acc && (
        <>
          <h2 className="font-display text-[22px] font-bold">이대로 발급할까요?</h2>
          <div className="mt-6"><CheckCard card={preview} /></div>
          <dl className="mt-6 divide-y divide-line border-y border-line text-[15px]">
            <Line label="연결 계좌">{acc.name}</Line>
            <Line label="1일 사용한도"><span className="num">{won(f.dailyLimit)}</span></Line>
            <Line label="해외결제">{f.overseas ? '켬' : '끔'}</Line>
            <Line label="결제 알림">켬</Line>
          </dl>
          {error && <p role="alert" className="mt-3 text-[13px] text-danger">{error}</p>}
          <PinSheet open={pin} onClose={() => setPin(false)} onPass={issue} purpose="발급하려면" />
        </>
      )}
    </Page>
  );
}

function Line({ label, children }: { label: string; children: ReactNode }) {
  return <div className="flex justify-between py-3"><dt className="text-sub">{label}</dt><dd className="font-medium">{children}</dd></div>;
}
