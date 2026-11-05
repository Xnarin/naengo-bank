import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ChevronRight, CircleAlert } from 'lucide-react';
import { PinPad, PinSheet } from '../components/bank';
import { Button, Checkbox, Field, Page, Sheet } from '../components/ui';
import { cn, maskEmail } from '../lib/format';
import { useBank } from '../store';
import { PW_RE, weakPin } from './Auth';

const IDLE_OPTIONS = [{ m: 1, label: '1분 (체험용)' }, { m: 5, label: '5분' }, { m: 10, label: '10분' }, { m: 30, label: '30분' }];

type SheetKind = null | 'name' | 'password' | 'pin-check' | 'pin-new';

/** 계정 관리: 정보 변경, 비밀번호·간편비밀번호 변경, 자동 로그아웃, 회원 탈퇴 */
export function Settings() {
  const bank = useBank();
  const { user } = bank;
  const [currentPin, setCurrentPin] = useState('');
  const [sheet, setSheet] = useState<SheetKind>(null);
  const close = () => { setSheet(null); setCurrentPin(''); };
  if (!user) return null;

  return (
    <Page back title="계정 관리">
      <h2 className="pt-2 text-[13px] font-medium text-sub">내 정보</h2>
      <ul className="divide-y divide-line border-b border-line">
        <Item label="이름" value={user.name} onClick={() => setSheet('name')} />
        <Item label="이메일" value={maskEmail(user.email)} />
      </ul>

      <h2 className="mt-8 text-[13px] font-medium text-sub">보안</h2>
      <ul className="divide-y divide-line border-b border-line">
        <Item label="비밀번호 변경" onClick={() => setSheet('password')} />
        <Item label="간편비밀번호 변경" onClick={() => setSheet('pin-check')} />
      </ul>

      <h2 className="mt-8 text-[13px] font-medium text-sub">자동 로그아웃</h2>
      <p className="mt-1 text-[13px] text-sub">이 시간 동안 아무것도 누르지 않으면 로그아웃돼요.</p>
      <div className="mt-3 grid grid-cols-4 gap-1 rounded-full bg-surface p-1" role="radiogroup" aria-label="자동 로그아웃 시간">
        {IDLE_OPTIONS.map((o) => (
          <button key={o.m} role="radio" aria-checked={bank.idleMinutes === o.m} onClick={() => { bank.setIdleMinutes(o.m); bank.toast(`${o.m}분 뒤 자동 로그아웃돼요`); }}
            className={cn('h-10 rounded-full text-[13px] font-semibold transition-colors', bank.idleMinutes === o.m ? 'bg-paper text-ink shadow-sm' : 'text-sub')}>
            {o.label.replace(' (체험용)', '')}
          </button>
        ))}
      </div>
      <p className="mt-2 text-[12px] text-sub">1분은 자동 로그아웃을 바로 보는 체험용이에요.</p>

      <Link to="/settings/withdraw" className="mt-10 flex items-center justify-between border-t border-line py-5 text-[15px] font-semibold text-danger">
        회원 탈퇴<ChevronRight className="size-5" />
      </Link>

      <NameSheet open={sheet === 'name'} onClose={close} />
      <PasswordSheet open={sheet === 'password'} onClose={close} />
      <PinSheet open={sheet === 'pin-check'} onClose={close} onPass={async (pin) => { await bank.verifyPin(pin); setCurrentPin(pin); setSheet('pin-new'); }} purpose="지금 쓰는" />
      <NewPinSheet open={sheet === 'pin-new'} onClose={close} currentPin={currentPin} />
    </Page>
  );
}

function Item({ label, value, onClick }: { label: string; value?: string; onClick?: () => void }) {
  const body = (
    <>
      <span className="text-[15px] font-medium">{label}</span>
      <span className="flex items-center gap-1 text-[14px] text-sub">{value}{onClick && <ChevronRight className="size-4 text-mute" />}</span>
    </>
  );
  return (
    <li>
      {onClick
        ? <button onClick={onClick} className="flex w-full items-center justify-between py-4 text-left">{body}</button>
        : <div className="flex items-center justify-between py-4">{body}</div>}
    </li>
  );
}

function useSave(onClose: () => void, okMsg: string) {
  const { toast } = useBank();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  async function run(fn: () => Promise<void>) {
    setBusy(true); setError('');
    try { await fn(); toast(okMsg); onClose(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return { busy, error, run, setError };
}

function NameSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { user, updateName } = useBank();
  const [name, setName] = useState(user?.name ?? '');
  const { busy, error, run } = useSave(onClose, '이름을 바꿨어요');
  const err = !/^[가-힣a-zA-Z\s]{2,20}$/.test(name.trim()) ? '한글 또는 영문 2~20자로 입력해 주세요.' : '';
  return (
    <Sheet open={open} onClose={onClose} title="이름 변경">
      <Field label="이름" value={name} onChange={(e) => setName(e.target.value)} error={(name && err) || error || undefined} />
      <Button full size="lg" className="mt-5" loading={busy} disabled={!!err} onClick={() => run(() => updateName(name.trim()))}>저장</Button>
    </Sheet>
  );
}

function PasswordSheet({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { changePassword } = useBank();
  const [f, setF] = useState({ cur: '', a: '', b: '' });
  const [touched, setTouched] = useState(false);
  const { busy, error, run } = useSave(onClose, '비밀번호를 바꿨어요');
  const errs = { a: !PW_RE.test(f.a) ? '영문, 숫자, 특수문자를 포함해 8자 이상 입력해 주세요.' : '', b: f.a !== f.b ? '비밀번호가 일치하지 않아요.' : '' };
  return (
    <Sheet open={open} onClose={onClose} title="비밀번호 변경">
      <div className="space-y-4">
        <Field label="지금 비밀번호" type="password" autoComplete="current-password" value={f.cur} onChange={(e) => setF({ ...f, cur: e.target.value })} />
        <Field label="새 비밀번호" type="password" autoComplete="new-password" placeholder="영문, 숫자, 특수문자 포함 8자 이상" value={f.a} onChange={(e) => setF({ ...f, a: e.target.value })} error={touched && errs.a ? errs.a : undefined} />
        <Field label="새 비밀번호 확인" type="password" autoComplete="new-password" value={f.b} onChange={(e) => setF({ ...f, b: e.target.value })} error={touched && errs.b ? errs.b : undefined} />
      </div>
      {error && <p role="alert" className="mt-3 text-[13px] text-danger">{error}</p>}
      <Button full size="lg" className="mt-5" loading={busy} disabled={!f.cur}
        onClick={() => { setTouched(true); if (!errs.a && !errs.b) run(() => changePassword(f.cur, f.a)); }}>변경하기</Button>
    </Sheet>
  );
}

function NewPinSheet({ open, onClose, currentPin }: { open: boolean; onClose: () => void; currentPin: string }) {
  const { changePin, toast } = useBank();
  const [first, setFirst] = useState<string | null>(null);
  const [err, setErr] = useState<{ msg: string; n: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const bump = (msg: string) => setErr((e) => ({ msg, n: (e?.n ?? 0) + 1 }));

  async function onPin(p: string) {
    if (!first) { if (weakPin(p)) return bump('같은 숫자나 연속된 숫자는 쓸 수 없어요.'); setFirst(p); setErr(null); return; }
    if (p !== first) { setFirst(null); return bump('두 번 입력한 비밀번호가 달라요. 처음부터 다시 눌러 주세요.'); }
    setBusy(true);
    try { await changePin(currentPin, p); toast('간편비밀번호를 바꿨어요'); setFirst(null); onClose(); }
    catch (e) { setFirst(null); bump((e as Error).message); }
    finally { setBusy(false); }
  }

  return (
    <Sheet open={open} onClose={() => { setFirst(null); onClose(); }} title="새 간편비밀번호">
      <p className="text-[15px] text-sub">{first ? '한 번 더 눌러 주세요.' : '새로 쓸 6자리를 눌러 주세요.'}</p>
      {open && <PinPad key={first ? 'b' : 'a'} onComplete={onPin} error={err} busy={busy} message="같은 숫자 반복이나 연속된 숫자는 쓸 수 없어요." />}
    </Sheet>
  );
}

/** 회원 탈퇴: 잔액·예약 송금 점검 → 동의 → 간편비밀번호 */
export function Withdraw() {
  const bank = useBank();
  const navigate = useNavigate();
  const [agree, setAgree] = useState(false);
  const [pin, setPin] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const blockers = bank.withdrawBlockers();

  async function go(pinValue: string) {
    setBusy(true); setError('');
    try { await bank.withdraw(pinValue); setPin(false); bank.toast('탈퇴했어요. 그동안 이용해 주셔서 고마워요'); navigate('/login', { replace: true }); }
    catch (e) { setBusy(false); if (['PIN', 'PIN_LOCKED', 'AUTH', 'LOGIN_LOCKED'].includes((e as { code?: string }).code ?? '')) throw e; setPin(false); setError((e as Error).message); }
  }

  return (
    <Page back title="회원 탈퇴" footer={blockers.length ? undefined : <Button size="lg" full variant="navy" disabled={!agree} loading={busy} onClick={() => setPin(true)}>탈퇴하기</Button>}>
      <h2 className="pt-2 font-display text-[22px] leading-snug font-bold">탈퇴하기 전에<br />확인해 주세요</h2>
      <ul className="mt-6 space-y-2 text-[14px] leading-relaxed text-sub">
        <li>· 모든 계좌와 연결된 체크카드를 먼저 해지해야 탈퇴할 수 있어요.</li>
        <li>· 탈퇴한 이메일로는 다시 가입할 수 없어요(프로토타입 기준).</li>
        <li>· 되돌릴 수 없어요.</li>
      </ul>
      {blockers.length > 0 ? (
        <div className="mt-6 space-y-2">
          {blockers.map((b) => <p key={b} className="flex items-start gap-2 rounded-xl bg-danger-soft px-4 py-3 text-[14px] text-danger"><CircleAlert className="mt-0.5 size-4 shrink-0" />{b}</p>)}
          <p className="pt-2 text-[13px] text-sub">위 항목을 정리하면 탈퇴할 수 있어요.</p>
        </div>
      ) : (
        <div className="mt-6">
          <Checkbox checked={agree} onChange={setAgree} strong>위 내용을 확인했고 탈퇴할게요</Checkbox>
          {error && <p role="alert" className="mt-2 text-[13px] text-danger">{error}</p>}
        </div>
      )}
      <PinSheet open={pin} onClose={() => setPin(false)} onPass={go} purpose="탈퇴하려면" />
    </Page>
  );
}
