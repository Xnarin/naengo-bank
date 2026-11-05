import { useState, type ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Check, ChevronRight, CircleAlert, SearchX, Star } from 'lucide-react';
import { PinSheet, shortName } from '../components/bank';
import { Button, Checkbox, EmptyState, Field, Page, Sheet } from '../components/ui';
import { MAX_LIMITS } from '../data/mock';
import { cn, won } from '../lib/format';
import { BankError, closeBlockers, usageOf, useBank, type CloseBlocker } from '../store';

const digitsOnly = (v: string) => v.replace(/\D/g, '').slice(0, 9).replace(/^0+/, '');
const comma = (v: string) => (v ? Number(v).toLocaleString('ko-KR') : '');

/** 본인 계좌(해지 포함)만 찾는다 */
function useMyAccount() {
  const { id } = useParams();
  const { db, user } = useBank();
  return db.accounts.find((a) => a.id === id && a.owner === user?.email);
}

function NotFound({ title }: { title: string }) {
  const navigate = useNavigate();
  return <Page back title={title}><EmptyState icon={SearchX} title="계좌를 찾을 수 없어요" action={<Button onClick={() => navigate('/')}>홈으로</Button>} /></Page>;
}

/** 계좌 관리: 즐겨찾기, 상태(거래중지 해제), 이체한도, 해지 진입 */
export function AccountManage() {
  const acc = useMyAccount();
  const bank = useBank();
  const [limitOpen, setLimitOpen] = useState(false);
  if (!acc || acc.status === 'closed') return <NotFound title="계좌 관리" />;
  const u = usageOf(bank.db, acc.id);

  return (
    <Page back title="계좌 관리">
      <section className="pt-2">
        <p className="text-[15px] font-bold">{acc.name}</p>
        <p className="num text-[13px] text-sub">내금고 {acc.number}</p>
      </section>

      <button onClick={() => { bank.toggleFavorite(acc.id); bank.toast(acc.favorite ? '즐겨찾기를 해제했어요' : '홈 맨 위에 고정했어요'); }}
        role="switch" aria-checked={!!acc.favorite}
        className="mt-6 flex w-full items-center justify-between border-y border-line py-4 text-left">
        <span>
          <span className="block text-[15px] font-semibold">즐겨찾기</span>
          <span className="block text-[13px] text-sub">켜면 홈에서 맨 위에 보여요</span>
        </span>
        <Star className={cn('size-6', acc.favorite ? 'fill-brand text-brand' : 'text-mute')} />
      </button>

      <StatusSection id={acc.id} suspended={acc.status === 'suspended'} />

      <section className="border-b border-line py-5">
        <div className="flex items-center justify-between">
          <h2 className="text-[15px] font-semibold">이체한도</h2>
          <Button size="sm" variant="outline" disabled={acc.status !== 'active'} onClick={() => setLimitOpen(true)}>변경</Button>
        </div>
        <Meter label="오늘" used={u.today} limit={acc.limits.daily} />
        <Meter label="이번 달" used={u.month} limit={acc.limits.monthly} />
        <p className="mt-3 text-[12px] text-sub">내 계좌끼리 옮기는 돈은 한도에 들어가지 않아요. 기본 한도는 1일 100만원, 1달 500만원이에요.</p>
      </section>

      <Link to={`/accounts/${acc.id}/close`} className="flex items-center justify-between py-5 text-[15px] font-semibold text-danger">
        계좌 해지<ChevronRight className="size-5" />
      </Link>

      <LimitSheet open={limitOpen} onClose={() => setLimitOpen(false)} accountId={acc.id} current={acc.limits} />
    </Page>
  );
}

export function Meter({ label, used, limit }: { label: string; used: number; limit: number }) {
  const pct = Math.min(100, (used / limit) * 100);
  return (
    <div className="mt-4">
      <div className="flex items-baseline justify-between text-[14px]">
        <span className="text-sub">{label}</span>
        <span className="num"><b className="font-semibold">{won(used)}</b><span className="text-sub"> / {won(limit)}</span></span>
      </div>
      <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-surface" role="progressbar" aria-label={`${label} 한도 사용`} aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
        <div className={cn('h-full rounded-full', pct >= 90 ? 'bg-danger' : 'bg-brand')} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

/** 상태 표시 + 거래중지면 인증번호 본인인증으로 해제 */
function StatusSection({ id, suspended }: { id: string; suspended: boolean }) {
  const bank = useBank();
  const [sent, setSent] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  async function send() {
    setBusy(true); setError('');
    try { setSent(await bank.sendMyCode()); setCode(''); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function confirm() {
    setBusy(true); setError('');
    try { await bank.unlockAccount(id, code); setSent(null); bank.toast('거래중지를 해제했어요'); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <section className="border-b border-line py-5">
      <div className="flex items-center justify-between">
        <h2 className="text-[15px] font-semibold">계좌 상태</h2>
        <span className={cn('inline-flex items-center gap-1.5 text-[14px] font-semibold', suspended ? 'text-danger' : 'text-success')}>
          <span aria-hidden className={cn('size-1.5 rounded-full', suspended ? 'bg-danger' : 'bg-success')} />{suspended ? '거래중지' : '정상'}
        </span>
      </div>
      {suspended && (
        <div className="mt-3">
          <p className="text-[14px] text-sub">간편비밀번호를 5회 틀려 입출금이 막혔어요. 가입한 이메일로 받은 인증번호로 본인인증하면 바로 풀려요.</p>
          {!sent ? (
            <Button className="mt-3" full loading={busy} onClick={send}>인증번호 받기</Button>
          ) : (
            <div className="rise mt-3">
              <Field label="인증번호 6자리" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code}
                onChange={(e) => setCode(e.target.value.replace(/\D/g, ''))} error={error || undefined}
                hint={<>메일 대신 예시로 보여 드려요: <span className="num font-semibold text-ink">{sent}</span></>} />
              <div className="mt-3 grid grid-cols-[auto_1fr] gap-2">
                <Button variant="secondary" onClick={send} disabled={busy}>다시 받기</Button>
                <Button loading={busy} disabled={code.length !== 6} onClick={confirm}>해제하기</Button>
              </div>
            </div>
          )}
          {!sent && error && <p role="alert" className="mt-2 text-[13px] text-danger">{error}</p>}
        </div>
      )}
    </section>
  );
}

function LimitSheet({ open, onClose, accountId, current }: { open: boolean; onClose: () => void; accountId: string; current: { daily: number; monthly: number } }) {
  const bank = useBank();
  const [daily, setDaily] = useState(String(current.daily));
  const [monthly, setMonthly] = useState(String(current.monthly));
  const [pin, setPin] = useState(false);
  const [error, setError] = useState('');
  const d = Number(daily || 0), m = Number(monthly || 0);
  const invalid = !d || !m ? '한도를 입력해 주세요.'
    : d > MAX_LIMITS.daily ? `1일 한도는 최대 ${won(MAX_LIMITS.daily)}이에요.`
    : m > MAX_LIMITS.monthly ? `1달 한도는 최대 ${won(MAX_LIMITS.monthly)}이에요.`
    : d > m ? '1일 한도는 1달 한도보다 클 수 없어요.' : '';

  async function save() {
    setPin(false);
    try { await bank.setLimits(accountId, { daily: d, monthly: m }); bank.toast('이체한도를 바꿨어요'); onClose(); }
    catch (e) { setError(e instanceof BankError ? e.message : '한도를 바꾸지 못했어요.'); }
  }

  return (
    <>
      <Sheet open={open && !pin} onClose={onClose} title="이체한도 변경">
        <div className="space-y-4">
          <Field label="1일 한도 (원)" inputMode="numeric" value={comma(daily)} onChange={(e) => { setDaily(digitsOnly(e.target.value)); setError(''); }} />
          <Field label="1달 한도 (원)" inputMode="numeric" value={comma(monthly)} onChange={(e) => { setMonthly(digitsOnly(e.target.value)); setError(''); }} />
        </div>
        <p role="alert" className={cn('mt-3 text-[13px]', invalid || error ? 'text-danger' : 'text-sub')}>
          {invalid || error || `최대 1일 ${won(MAX_LIMITS.daily)}, 1달 ${won(MAX_LIMITS.monthly)}까지 정할 수 있어요.`}
        </p>
        <Button full size="lg" className="mt-5" disabled={!!invalid} onClick={() => setPin(true)}>변경하기</Button>
      </Sheet>
      <PinSheet open={pin} onClose={() => setPin(false)} onPass={save} accountId={accountId} purpose="한도를 바꾸려면" />
    </>
  );
}

const BLOCKER_ACTION: Record<CloseBlocker['kind'], (id: string) => { label: string; to: string }> = {
  status: (id) => ({ label: '거래중지 해제', to: `/accounts/${id}/manage` }),
  balance: (id) => ({ label: '다른 계좌로 옮기기', to: `/transfer?from=${id}` }),
  card: () => ({ label: '카드 해지하러 가기', to: '/cards' }),
  scheduled: () => ({ label: '예약·자동이체 보기', to: '/auto-transfers' }),
};

/** 계좌 해지: 가능 여부 점검 → 최종 확인 → 간편비밀번호 → 완료 */
export function CloseAccount() {
  const acc = useMyAccount();
  const bank = useBank();
  const navigate = useNavigate();
  const [agree, setAgree] = useState(false);
  const [pin, setPin] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (!acc) return <NotFound title="계좌 해지" />;

  if (acc.status === 'closed') {
    return (
      <Page footer={<div className="grid grid-cols-2 gap-2">
        <Button size="lg" variant="secondary" onClick={() => navigate(`/accounts/${acc.id}`, { replace: true })}>거래내역 보기</Button>
        <Button size="lg" onClick={() => navigate('/', { replace: true })}>홈으로</Button>
      </div>}>
        <div className="rise flex flex-col items-center pt-28 text-center">
          <span className="grid size-16 place-items-center rounded-full bg-navy text-white"><Check className="size-8" strokeWidth={3} /></span>
          <p className="mt-6 font-display text-[22px] leading-snug font-bold">{shortName(acc.name)}을<br />해지했어요</p>
          <p className="mt-3 text-[14px] text-sub">이 계좌로는 더 이상 입출금할 수 없어요.<br />지난 거래내역은 계속 볼 수 있어요.</p>
        </div>
      </Page>
    );
  }

  const checks: { kind: CloseBlocker['kind']; label: string }[] = [
    { kind: 'status', label: '정상 상태인 계좌' },
    { kind: 'balance', label: '잔액 0원' },
    { kind: 'card', label: '연결된 체크카드 없음' },
    { kind: 'scheduled', label: '예약 송금·자동이체 없음' },
  ];
  const blockers = closeBlockers(bank.db, acc.id);
  const ok = !blockers.length;

  async function close() {
    setPin(false); setBusy(true); setError('');
    try { await bank.closeAccount(acc!.id); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <Page back title="계좌 해지" footer={ok ? <Button size="lg" full variant="navy" disabled={!agree} loading={busy} onClick={() => setPin(true)}>해지하기</Button> : undefined}>
      <h2 className="pt-2 font-display text-[22px] leading-snug font-bold">{shortName(acc.name)}을<br />해지할 수 있는지 확인했어요</h2>
      <p className="num mt-1 text-[14px] text-sub">내금고 {acc.number}</p>

      <ul className="mt-6 divide-y divide-line border-y border-line">
        {checks.map((c) => {
          const b = blockers.find((x) => x.kind === c.kind);
          const act = b && BLOCKER_ACTION[c.kind](acc.id);
          return (
            <li key={c.kind} className="py-3.5">
              <div className="flex items-center justify-between gap-3">
                <span className="text-[15px] font-medium">{c.label}</span>
                {b ? <span className="inline-flex items-center gap-1 text-[13px] font-semibold text-danger"><CircleAlert className="size-4" />확인 필요</span>
                  : <span className="inline-flex items-center gap-1 text-[13px] font-semibold text-success"><Check className="size-4" />통과</span>}
              </div>
              {b && (
                <Row2>
                  <span>{b.text}</span>
                  {act && <Link to={act.to} className="shrink-0 font-semibold text-brand">{act.label}</Link>}
                </Row2>
              )}
            </li>
          );
        })}
      </ul>

      {ok ? (
        <div className="mt-6">
          <p className="rounded-2xl bg-danger-soft px-4 py-3 text-[14px] leading-relaxed text-danger">해지하면 되돌릴 수 없어요. 이 계좌로 입금받거나 보낼 수 없게 되고, 지난 거래내역은 계속 볼 수 있어요.</p>
          <div className="mt-3"><Checkbox checked={agree} onChange={setAgree} strong>위 내용을 확인했고 계좌를 해지할게요</Checkbox></div>
          {error && <p role="alert" className="mt-2 text-[13px] text-danger">{error}</p>}
        </div>
      ) : (
        <p className="mt-6 text-[14px] text-sub">위 항목을 정리하면 해지할 수 있어요. 체크카드가 연결되지 않은 새 통장으로 해지를 체험해 볼 수 있어요.</p>
      )}

      <PinSheet open={pin} onClose={() => setPin(false)} onPass={close} accountId={acc.id} purpose="해지하려면" />
    </Page>
  );
}

function Row2({ children }: { children: ReactNode }) {
  return <p className="mt-1.5 flex items-start justify-between gap-3 text-[13px] text-sub">{children}</p>;
}
