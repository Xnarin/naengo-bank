import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowUpRight, ChevronRight, Delete, LoaderCircle, Nfc, Star } from 'lucide-react';
import { TEST_ACCOUNTS, DEMO_PIN, type Account, type Card, type CardStatus, type CardTheme, type Product, type Tx } from '../data/mock';
import { cn, fmtDateTime, fmtDay, fmtTime, groupByDay, maskAccount, signedWon, won } from '../lib/format';
import { Button, Row, Sheet } from './ui';
import { recentRecipients, useBank } from '../store';

/** 금고 서랍마다 고유색. 순서대로 돌려 쓴다. */
const TONES = ['bg-drawer-1', 'bg-drawer-2', 'bg-drawer-3', 'bg-drawer-4'];
/** 같은 서랍을 가리키는 진한 표시색(목록의 막대용) */
const MARKS = ['bg-mark-1', 'bg-mark-2', 'bg-mark-3', 'bg-mark-4'];
const idx = (accounts: Account[], id: string) => Math.max(0, accounts.findIndex((a) => a.id === id));
export const toneOf = (accounts: Account[], id: string) => TONES[idx(accounts, id) % TONES.length];
export const markOf = (accounts: Account[], id: string) => MARKS[idx(accounts, id) % MARKS.length];
export const shortName = (name: string) => name.replace(/^내금고\s*/, '');

/** 계좌들을 겹쳐 쌓인 금고 서랍으로 보여 준다. 한 번에 하나만 열린다. */
export function DrawerStack({ accounts }: { accounts: Account[] }) {
  const navigate = useNavigate();
  const [openId, setOpenId] = useState<string | undefined>(accounts[0]?.id);
  return (
    <ul className="flex flex-col">
      {accounts.map((a, i) => {
        const open = a.id === openId;
        const last = i === accounts.length - 1;
        return (
          <li key={a.id} className={cn('relative rounded-[22px] px-5 pt-5 transition-[padding] duration-300', toneOf(accounts, a.id), i > 0 && '-mt-6 border-t border-ink/[0.06]', last ? 'pb-4' : 'pb-10')}>
            <span aria-hidden className="absolute top-2 left-1/2 h-1 w-9 -translate-x-1/2 rounded-full bg-ink/15" />
            <button
              onClick={() => setOpenId(open ? undefined : a.id)}
              aria-expanded={open}
              aria-controls={`drawer-${a.id}`}
              className="flex w-full items-center justify-between gap-3 text-left"
            >
              <span className="flex min-w-0 items-center gap-1.5">
                <span className="truncate text-[15px] font-bold">{shortName(a.name)}</span>
                {a.favorite && <Star aria-label="즐겨찾기" className="size-3.5 shrink-0 fill-brand text-brand" />}
                {a.status === 'suspended' && <span className="shrink-0 text-[12px] font-semibold text-danger">거래중지</span>}
              </span>
              <span className={cn('num font-display text-[17px] font-bold transition-opacity duration-200', open && 'opacity-0')}>{won(a.balance)}</span>
            </button>
            <div id={`drawer-${a.id}`} className={cn('grid transition-[grid-template-rows] duration-300 ease-out motion-reduce:transition-none', open ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]')}>
              <div className="overflow-hidden" inert={!open}>
                <p className="num text-[12px] text-ink/65">{a.number}</p>
                <p className="num mt-5 font-display text-[30px] font-bold">{won(a.balance)}</p>
                <div className="mt-3 flex items-center justify-between pb-1">
                  <button onClick={() => navigate(`/accounts/${a.id}`)} className="group inline-flex items-center text-[13px] font-semibold text-ink/70 hover:text-ink">
                    거래내역<ChevronRight className="size-4 transition-transform group-hover:translate-x-0.5" />
                  </button>
                  {a.status === 'suspended' ? (
                    <button onClick={() => navigate(`/accounts/${a.id}/manage`)} className="inline-flex h-9 items-center rounded-full bg-navy px-4 text-[14px] font-semibold text-white active:scale-95">해제하기</button>
                  ) : (
                    <button
                      onClick={() => navigate(`/transfer?from=${a.id}`)}
                      className="inline-flex h-9 items-center gap-1 rounded-full bg-brand pr-3 pl-4 text-[14px] font-semibold text-white transition-transform hover:bg-brand-dark active:scale-95"
                    >
                      송금<ArrowUpRight className="size-4" />
                    </button>
                  )}
                </div>
              </div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function TxRow({ tx, onClick, showBalance = true, tone }: { tx: Pick<Tx, 'type' | 'amount' | 'counterparty' | 'date' | 'memo'> & { balanceAfter?: number }; onClick?: () => void; showBalance?: boolean; tone?: string }) {
  const isIn = tx.type === 'in';
  return (
    <button onClick={onClick} className="flex w-full items-center gap-3 py-3 text-left">
      {tone && <span aria-hidden className={cn('h-8 w-1.5 shrink-0 rounded-full', tone)} />}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[15px] font-medium">{tx.counterparty}</span>
        <span className="block text-[13px] text-sub">{fmtTime(tx.date)}{tx.memo ? ` · ${tx.memo}` : ''}</span>
      </span>
      <span className="text-right">
        <span className={cn('num block text-[15px] font-semibold', isIn && 'text-success')}>{signedWon(tx.amount, tx.type)}</span>
        {showBalance && tx.balanceAfter !== undefined && <span className="num block text-[12px] text-sub">잔액 {won(tx.balanceAfter)}</span>}
      </span>
    </button>
  );
}

/** 날짜별로 묶은 거래 목록 */
export function TxList({ txs, onSelect }: { txs: Tx[]; onSelect?: (t: Tx) => void }) {
  return (
    <div>
      {groupByDay(txs).map((group) => (
        <section key={group[0].date} className="border-b border-line/60 py-2 last:border-0">
          <h3 className="pt-2 text-[13px] font-medium text-sub">{fmtDay(group[0].date)}</h3>
          {group.map((t) => <TxRow key={t.id} tx={t} onClick={() => onSelect?.(t)} />)}
        </section>
      ))}
    </div>
  );
}

export function TxDetailSheet({ tx, onClose }: { tx: Tx | null; onClose: () => void }) {
  return (
    <Sheet open={!!tx} onClose={onClose} title="거래 상세">
      {tx && (
        <>
          <p className="text-[15px] text-sub">{tx.counterparty}</p>
          <p className={cn('num mt-1 font-display text-[30px] font-bold', tx.type === 'in' && 'text-success')}>{signedWon(tx.amount, tx.type)}</p>
          <div className="mt-5 border-t border-line pt-3">
            <Row label="거래일시">{fmtDateTime(tx.date)}</Row>
            <Row label="거래구분">{tx.type === 'in' ? '입금' : '출금'}</Row>
            <Row label={tx.type === 'in' ? '보낸 분' : '받는 분'}>{tx.counterparty}</Row>
            {tx.counterpartyAccount && <Row label="상대 계좌"><span className="num">내금고 {maskAccount(tx.counterpartyAccount)}</span></Row>}
            {tx.memo && <Row label="메모">{tx.memo}</Row>}
            <Row label="거래 후 잔액"><span className="num">{won(tx.balanceAfter)}</span></Row>
            <Row label="거래번호"><span className="num text-[13px] text-sub">{tx.id.toUpperCase()}</span></Row>
          </div>
          <Button full size="lg" variant="secondary" className="mt-5" onClick={onClose}>확인</Button>
        </>
      )}
    </Sheet>
  );
}

const THEME: Record<CardTheme, string> = {
  navy: 'bg-[linear-gradient(135deg,var(--color-navy)_0%,var(--color-brand)_120%)] text-white',
  sky: 'bg-[linear-gradient(135deg,var(--color-drawer-1)_0%,var(--color-brand-soft)_60%,var(--color-drawer-4)_130%)] text-ink',
  slate: 'bg-[linear-gradient(135deg,#F1ECE4_0%,#E2D8CA_70%,#CFC0AC_130%)] text-ink',
};

/** 카드 상태 이름 */
export const CARD_STATUS: Record<CardStatus, string> = { active: '사용 중', paused: '일시정지', lost: '분실 신고됨', terminated: '해지됨' };

/** 자체 디자인 체크카드 */
export function CheckCard({ card, small }: { card: Card; small?: boolean }) {
  return (
    <div className={cn('relative aspect-[1.586] overflow-hidden rounded-2xl shadow-[0_10px_30px_rgba(14,30,74,0.18)]', THEME[card.theme], small ? 'w-40 p-3' : 'w-full p-5')}>
      <div className="pointer-events-none absolute -top-1/3 -right-1/4 aspect-square w-3/4 rounded-full bg-paper/10" />
      <div className="pointer-events-none absolute -bottom-1/2 -left-1/4 aspect-square w-2/3 rounded-full bg-paper/[0.06]" />
      <div className="relative flex h-full flex-col justify-between">
        <div className="flex items-start justify-between">
          <span className={cn('font-extrabold tracking-[0.18em]', small ? 'text-[11px]' : 'text-[15px]')}>NAENGO</span>
          {!small && <span className="rounded-full bg-paper/20 px-2 py-0.5 text-[11px] font-semibold">CHECK</span>}
        </div>
        {!small && (
          <div className="flex items-center gap-3">
            <div className="h-8 w-11 rounded-md bg-[linear-gradient(135deg,#F4D88A,#C9A24B)]" />
            <Nfc className="size-6 opacity-80" />
          </div>
        )}
        <div className="flex items-end justify-between">
          <span className={cn('num font-medium tracking-widest', small ? 'text-[11px]' : 'text-[16px]')}>•••• {card.last4}</span>
          {!small && <span className="text-[12px] opacity-80">{card.name}</span>}
        </div>
      </div>
      {card.status !== 'active' && (
        <div className={cn('absolute inset-0 grid place-items-center bg-black/45 font-semibold text-white', small ? 'text-[12px]' : 'text-[14px]')}>{CARD_STATUS[card.status]}</div>
      )}
    </div>
  );
}

export function RateText({ p, size = 'md' }: { p: Product; size?: 'md' | 'lg' }) {
  return (
    <div>
      <p className={cn('num font-bold text-brand', size === 'lg' ? 'font-display text-[30px]' : 'font-display text-[22px]')}>최고 연 {p.rate.toFixed(1)}%</p>
      <p className="text-[13px] text-sub">기본 연 {p.baseRate.toFixed(1)}%</p>
    </div>
  );
}

/**
 * 6자리 숫자 키패드(열 때마다 섞임). 6자리가 되면 onComplete. 오류가 오면 흔들리고 비워진다.
 * PinSheet(확인)와 간편비밀번호 설정 화면이 같이 쓴다.
 */
export function PinPad({ onComplete, message, error, busy, locked }: {
  onComplete: (pin: string) => void; message?: ReactNode; error?: { msg: string; n: number } | null; busy?: boolean; locked?: boolean;
}) {
  const [pin, setPin] = useState('');
  const keys = useMemo(() => [...'0123456789'].sort(() => Math.random() - 0.5), []);
  useEffect(() => { setPin(''); }, [error?.n]);

  function press(d: string) {
    if (busy || locked || pin.length >= 6) return;
    const next = pin + d;
    setPin(next);
    if (next.length === 6) onComplete(next);
  }

  const keyCls = 'grid h-14 place-items-center rounded-2xl text-ink transition-colors hover:bg-surface active:bg-line disabled:opacity-30';
  return (
    <div>
      <div key={error?.n} className={cn('mt-7 flex justify-center gap-3.5', error && 'shake')} aria-label={`${pin.length}자리 입력됨`} role="status">
        {Array.from({ length: 6 }, (_, i) => (
          <span key={i} className={cn('size-3.5 rounded-full transition-colors', i < pin.length ? 'bg-brand' : 'bg-line')} />
        ))}
      </div>
      <p role="alert" className={cn('mt-4 flex min-h-5 items-center justify-center gap-1.5 text-center text-[13px]', error ? 'text-danger' : 'text-sub')}>
        {busy ? <LoaderCircle className="size-4 animate-spin text-sub" /> : error ? error.msg : message}
      </p>
      <div className="mt-5 grid grid-cols-3 gap-1">
        {keys.slice(0, 9).map((d) => (
          <button type="button" key={d} onClick={() => press(d)} disabled={locked} className={cn(keyCls, 'num font-display text-[24px] font-semibold')}>{d}</button>
        ))}
        <button type="button" onClick={() => setPin('')} disabled={!pin} className={cn(keyCls, 'text-[14px] font-medium text-sub')}>전체 삭제</button>
        <button type="button" onClick={() => press(keys[9])} disabled={locked} className={cn(keyCls, 'num font-display text-[24px] font-semibold')}>{keys[9]}</button>
        <button type="button" onClick={() => setPin((v) => v.slice(0, -1))} disabled={!pin} aria-label="한 자리 지우기" className={keyCls}><Delete className="size-6" /></button>
      </div>
    </div>
  );
}

/** 간편비밀번호 확인 시트. 맞으면 onPass. 계좌를 넘기면 5회 오류 시 그 계좌가 거래중지된다. */
export function PinSheet({ open, onClose, onPass, accountId, purpose = '송금하려면' }: { open: boolean; onClose: () => void; onPass: (pin: string) => void | Promise<void>; accountId?: string; purpose?: string }) {
  const bank = useBank();
  const [error, setError] = useState<{ msg: string; locked: boolean; n: number } | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) setError(null); }, [open]);

  async function check(pin: string) {
    setBusy(true);
    try {
      await onPass(pin);
    } catch (e) {
      const code = (e as { code?: string }).code;
      setError((p) => ({ msg: (e as Error).message, locked: code === 'PIN_LOCKED' || code === 'LOGIN_LOCKED', n: (p?.n ?? 0) + 1 }));
    } finally {
      setBusy(false);
    }
  }

  const isDemo = TEST_ACCOUNTS.some((account) => bank.user?.email === account.email);
  return (
    <Sheet open={open} onClose={onClose} title="간편비밀번호">
      <p className="text-[15px] text-sub">{purpose} 비밀번호 6자리를 눌러 주세요.</p>
      {open && <PinPad onComplete={check} error={error} busy={busy} locked={error?.locked}
        message={isDemo ? <>예시 비밀번호 <span className="num font-semibold">{DEMO_PIN}</span></> : '가입할 때 정한 6자리예요.'} />}
    </Sheet>
  );
}

/** 받는 계좌 고르기: 내 다른 계좌, 최근·자주 보낸 계좌(별표 즐겨찾기 먼저). 송금과 자동이체가 같이 쓴다. */
export function RecipientPicker({ onPick, excludeId, testChip }: { onPick: (number: string) => void; excludeId?: string; testChip?: boolean }) {
  const bank = useBank();
  const recent = recentRecipients(bank.db, bank.user?.email ?? '').slice(0, 6);
  const own = bank.myAccounts.filter((a) => a.id !== excludeId && a.status === 'active');
  return (
    <div className="mt-8">
      {own.length > 0 && (
        <>
          <p className="mb-2 text-[13px] font-medium text-sub">내 계좌</p>
          <div className="flex flex-wrap gap-2">
            {own.map((a) => (
              <button type="button" key={a.id} onClick={() => onPick(a.number)} className="h-9 rounded-full bg-surface px-3.5 text-[13px] text-sub hover:bg-line">{shortName(a.name)}</button>
            ))}
            {testChip && <button type="button" onClick={() => onPick('999-9999-9999')} className="h-9 rounded-full border border-dashed border-line px-3.5 text-[13px] text-sub">없는 계좌 테스트</button>}
          </div>
        </>
      )}
      {recent.length > 0 && (
        <>
          <p className="mt-6 mb-1 text-[13px] font-medium text-sub">최근·자주 보낸 계좌</p>
          <ul className="divide-y divide-line/60">
            {recent.map((r) => (
              <li key={r.number} className="flex items-center gap-2">
                <button type="button" onClick={() => onPick(r.number)} className="flex min-w-0 flex-1 items-center justify-between gap-3 py-3 text-left">
                  <span className="min-w-0">
                    <span className="block truncate text-[15px] font-medium">{r.name}</span>
                    <span className="num block text-[13px] text-sub">내금고 {maskAccount(r.number)}</span>
                  </span>
                  <span className="shrink-0 text-[12px] text-sub">{r.count}번 보냄</span>
                </button>
                <button type="button" onClick={() => void bank.toggleFavRecipient(r.number).catch((e) => bank.toast((e as Error).message))} aria-label={r.fav ? `${r.name} 즐겨찾기 해제` : `${r.name} 즐겨찾기`} aria-pressed={r.fav}
                  className="grid size-9 shrink-0 place-items-center rounded-full hover:bg-surface">
                  <Star className={cn('size-[18px]', r.fav ? 'fill-brand text-brand' : 'text-mute')} />
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
