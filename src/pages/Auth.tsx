import { useState, type FormEvent, type ReactNode } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { CircleAlert, CircleCheck } from 'lucide-react';
import { PinPad } from '../components/bank';
import { Button, Checkbox, Field, Logo, Page, Steps } from '../components/ui';
import { DEMO, DEMO_PIN } from '../data/mock';
import { EMAIL_RE, useBank } from '../store';

export const PW_RE = /^(?=.*[A-Za-z])(?=.*\d)(?=.*[^A-Za-z\d]).{8,}$/;
const PW_HINT = '영문, 숫자, 특수문자를 포함해 8자 이상 입력해 주세요.';
/** 같은 숫자 반복·연속 숫자는 간편비밀번호로 쓰지 않는다 */
export const weakPin = (p: string) => /^(\d)\1{5}$/.test(p) || '0123456789'.includes(p) || '9876543210'.includes(p);

function Alert({ children }: { children: ReactNode }) {
  return <p role="alert" className="mt-4 flex items-start gap-2 rounded-xl bg-danger-soft px-4 py-3 text-[14px] text-danger"><CircleAlert className="mt-0.5 size-4 shrink-0" /><span>{children}</span></p>;
}

function Brand() {
  return (
    <div className="flex items-center gap-2">
      <Logo size={36} />
      <span className="font-display text-[20px] font-bold text-navy">내금고</span>
      <span className="text-[13px] text-sub">나만 여는 금고</span>
    </div>
  );
}

export function Login() {
  const { user, deviceUser } = useBank();
  const loc = useLocation();
  const state = loc.state as { from?: string; signedUp?: string; reset?: string } | null;
  const [mode, setMode] = useState<'pin' | 'email'>(deviceUser && !state?.signedUp && !state?.reset ? 'pin' : 'email');
  if (user) return <Navigate to={state?.from ?? '/'} replace />;
  return mode === 'pin' && deviceUser ? <PinLogin onEmail={() => setMode('email')} /> : <EmailLogin onPin={deviceUser ? () => setMode('pin') : undefined} />;
}

/** 이 기기에 기억된 계정: 간편비밀번호로 로그인 */
function PinLogin({ onEmail }: { onEmail: () => void }) {
  const { deviceUser, loginWithPin, forgetDevice } = useBank();
  const [error, setError] = useState<{ msg: string; n: number; locked: boolean } | null>(null);
  const [busy, setBusy] = useState(false);
  if (!deviceUser) return null;

  async function go(pin: string) {
    setBusy(true);
    try { await loginWithPin(deviceUser!.email, pin); }
    catch (e) { setError((p) => ({ msg: (e as Error).message, n: (p?.n ?? 0) + 1, locked: (e as { code?: string }).code === 'LOGIN_LOCKED' })); }
    finally { setBusy(false); }
  }

  return (
    <Page>
      <div className="flex min-h-dvh flex-col pt-20 pb-8">
        <Brand />
        <h1 className="mt-10 font-display text-[24px] leading-snug font-bold"><span className="text-brand">{deviceUser.name}</span>님,<br />간편비밀번호를 눌러 주세요</h1>
        <PinPad onComplete={go} error={error} busy={busy} locked={error?.locked || deviceUser.locked}
          message={deviceUser.locked ? '로그인이 잠긴 계정이에요.' : deviceUser.email === DEMO.email ? <>예시 비밀번호 <span className="num font-semibold">{DEMO_PIN}</span></> : ' '} />
        {(error?.locked || deviceUser.locked) && <Link to="/reset-password" className="mt-3 text-center text-[14px] font-semibold text-brand">비밀번호 재설정으로 잠금 풀기</Link>}
        <div className="mt-auto flex justify-center gap-4 pt-8 text-[14px] text-sub">
          <button onClick={onEmail} className="underline-offset-2 hover:underline">이메일로 로그인</button>
          <span aria-hidden>·</span>
          <button onClick={() => { forgetDevice(); onEmail(); }} className="underline-offset-2 hover:underline">다른 계정으로 로그인</button>
        </div>
      </div>
    </Page>
  );
}

function EmailLogin({ onPin }: { onPin?: () => void }) {
  const { login } = useBank();
  const navigate = useNavigate();
  const loc = useLocation();
  const state = loc.state as { from?: string; signedUp?: string; reset?: string } | null;
  const [email, setEmail] = useState(state?.signedUp ?? state?.reset ?? '');
  const [pw, setPw] = useState('');
  const [errs, setErrs] = useState<{ email?: string; pw?: string }>({});
  const [fail, setFail] = useState<{ msg: string; locked: boolean } | null>(null);
  const [loading, setLoading] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const next = {
      email: !email ? '이메일을 입력해 주세요.' : !EMAIL_RE.test(email) ? '올바른 이메일 형식이 아니에요.' : undefined,
      pw: !pw ? '비밀번호를 입력해 주세요.' : undefined,
    };
    setErrs(next);
    setFail(null);
    if (next.email || next.pw) return;
    setLoading(true);
    try {
      await login(email.trim(), pw);
      navigate(state?.from ?? '/', { replace: true });
    } catch (err) {
      setFail({ msg: (err as Error).message, locked: (err as { code?: string }).code === 'LOGIN_LOCKED' });
      setLoading(false);
    }
  }

  return (
    <Page>
      <form onSubmit={submit} noValidate className="flex min-h-dvh flex-col pt-20 pb-8">
        <Brand />
        <h1 className="mt-10 font-display text-[24px] font-bold">이메일로 로그인</h1>

        {(state?.signedUp || state?.reset) && (
          <p className="mt-6 flex items-center gap-2 rounded-xl bg-success-soft px-4 py-3 text-[14px] text-success">
            <CircleCheck className="size-4" />{state.signedUp ? '회원가입이 완료됐어요. 로그인해 주세요.' : '비밀번호를 바꿨어요. 새 비밀번호로 로그인해 주세요.'}
          </p>
        )}

        <div className="mt-8 space-y-5">
          <Field label="이메일" type="email" autoComplete="email" placeholder="example@email.com" value={email} onChange={(e) => setEmail(e.target.value)} error={errs.email} />
          <Field label="비밀번호" type="password" autoComplete="current-password" placeholder="비밀번호 입력" value={pw} onChange={(e) => setPw(e.target.value)} error={errs.pw} />
        </div>
        <Link to="/reset-password" state={{ email }} className="mt-3 self-end text-[13px] text-sub underline-offset-2 hover:underline">비밀번호를 잊으셨나요?</Link>

        {fail && <Alert>{fail.msg}{fail.locked && <> <Link to="/reset-password" state={{ email }} className="font-semibold underline">재설정하기</Link></>}</Alert>}

        <div className="mt-auto pt-10">
          <Button type="submit" size="lg" full loading={loading}>로그인</Button>
          {onPin
            ? <button type="button" onClick={onPin} className="mt-3 w-full py-2 text-[14px] text-sub underline-offset-2 hover:underline">간편비밀번호로 로그인</button>
            : <button type="button" onClick={() => { setEmail(DEMO.email); setPw(DEMO.password); }} className="mt-3 w-full py-2 text-[14px] text-sub underline-offset-2 hover:underline">데모 계정 정보 채우기</button>}
          <p className="mt-4 text-center text-[14px] text-sub">
            아직 회원이 아니신가요? <Link to="/signup" className="font-semibold text-brand">회원가입</Link>
          </p>
        </div>
      </form>
    </Page>
  );
}

/** 이메일 + 인증번호 확인. send가 돌려준 코드를 메일 대신 화면에 보여 준다(Mock). */
export function EmailVerify({ email, onEmail, verified, onVerified, send, label = '이메일' }: {
  email: string; onEmail: (v: string) => void; verified: boolean; onVerified: () => void; send: (email: string) => Promise<string>; label?: string;
}) {
  const { confirmCode } = useBank();
  const [sent, setSent] = useState<string | null>(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const valid = EMAIL_RE.test(email.trim());

  async function doSend() {
    setBusy(true); setError('');
    try { setSent(await send(email.trim())); setCode(''); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function doConfirm() {
    setBusy(true); setError('');
    try { await confirmCode(email, code); setSent(null); onVerified(); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return (
    <div className="space-y-3">
      <Field label={label} type="email" autoComplete="email" placeholder="example@email.com" value={email} disabled={verified}
        onChange={(e) => { onEmail(e.target.value); setSent(null); setError(''); }}
        error={!sent ? error || (email && !valid ? '올바른 이메일 형식이 아니에요.' : undefined) : undefined}
        hint={verified ? <span className="flex items-center gap-1 text-success"><CircleCheck className="size-3.5" />이메일 인증을 마쳤어요.</span> : undefined}
        right={!verified && <Button type="button" variant="secondary" className="h-13" onClick={doSend} loading={busy && !sent} disabled={!valid}>{sent ? '다시 받기' : '인증번호 받기'}</Button>} />
      {sent && !verified && (
        <div className="rise">
          <Field label="인증번호 6자리" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code}
            onChange={(e) => { setCode(e.target.value.replace(/\D/g, '')); setError(''); }} error={error || undefined}
            hint={<>메일 대신 예시로 보여 드려요: <span className="num font-semibold text-ink">{sent}</span></>}
            right={<Button type="button" className="h-13" onClick={doConfirm} loading={busy} disabled={code.length !== 6}>확인</Button>} />
        </div>
      )}
    </div>
  );
}

const TERMS = [
  { id: 'service', label: '[필수] 내금고 서비스 이용약관', required: true },
  { id: 'privacy', label: '[필수] 개인정보 수집·이용 동의', required: true },
  { id: 'marketing', label: '[선택] 혜택·이벤트 알림 받기', required: false },
] as const;

/** 회원가입: 약관 → 이메일 인증(이름) → 비밀번호 → 간편비밀번호 */
export function Signup() {
  const { signup, sendSignupCode } = useBank();
  const navigate = useNavigate();
  const [step, setStep] = useState(0);
  const [agree, setAgree] = useState<Record<string, boolean>>({});
  const [f, setF] = useState({ name: '', email: '', pw: '', pw2: '' });
  const [verified, setVerified] = useState(false);
  const [touched, setTouched] = useState(false);
  const [pin1, setPin1] = useState<string | null>(null);
  const [pinErr, setPinErr] = useState<{ msg: string; n: number } | null>(null);
  const [failMsg, setFailMsg] = useState('');
  const [loading, setLoading] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  const allRequired = TERMS.every((t) => !t.required || agree[t.id]);
  const nameErr = !f.name.trim() ? '이름을 입력해 주세요.' : !/^[가-힣a-zA-Z\s]{2,20}$/.test(f.name.trim()) ? '한글 또는 영문 2~20자로 입력해 주세요.' : undefined;
  const errs = {
    pw: !PW_RE.test(f.pw) ? PW_HINT : undefined,
    pw2: !f.pw2 ? '비밀번호를 한 번 더 입력해 주세요.' : f.pw !== f.pw2 ? '비밀번호가 일치하지 않아요.' : undefined,
  };
  const show = (k: keyof typeof errs) => (touched ? errs[k] : undefined);

  async function onPin(p: string) {
    if (!pin1) {
      if (weakPin(p)) { setPinErr((e) => ({ msg: '같은 숫자나 연속된 숫자는 쓸 수 없어요.', n: (e?.n ?? 0) + 1 })); return; }
      setPin1(p); setPinErr(null); return;
    }
    if (p !== pin1) { setPin1(null); setPinErr((e) => ({ msg: '두 번 입력한 비밀번호가 달라요. 처음부터 다시 눌러 주세요.', n: (e?.n ?? 0) + 1 })); return; }
    setLoading(true); setFailMsg('');
    try {
      await signup({ name: f.name.trim(), email: f.email.trim(), password: f.pw, pin: p, marketing: !!agree.marketing });
      navigate('/login', { replace: true, state: { signedUp: f.email.trim() } });
    } catch (err) {
      setFailMsg((err as Error).message); setPin1(null); setLoading(false);
    }
  }

  const footer = [
    <Button size="lg" full disabled={!allRequired} onClick={() => setStep(1)}>동의하고 계속</Button>,
    <Button size="lg" full disabled={!!nameErr || !verified} onClick={() => setStep(2)}>다음</Button>,
    <Button size="lg" full onClick={() => { setTouched(true); if (!errs.pw && !errs.pw2) setStep(3); }}>다음</Button>,
    undefined,
  ][step];

  return (
    <Page back={step > 0 ? () => { setStep(step - 1); setPin1(null); } : () => navigate('/login')} title="회원가입" footer={footer}>
      <Steps steps={['약관 동의', '이메일 인증', '비밀번호', '간편비밀번호']} current={step} />

      {step === 0 && (
        <>
          <h2 className="font-display text-[22px] font-bold">약관에 동의해 주세요</h2>
          <div className="mt-6 border-b border-line pb-2">
            <Checkbox strong checked={TERMS.every((t) => agree[t.id])} onChange={(v) => setAgree(Object.fromEntries(TERMS.map((t) => [t.id, v])))}>전체 동의</Checkbox>
          </div>
          <div className="mt-2">
            {TERMS.map((t) => <Checkbox key={t.id} checked={!!agree[t.id]} onChange={(v) => setAgree({ ...agree, [t.id]: v })}>{t.label}</Checkbox>)}
          </div>
          <p className="mt-4 text-[13px] text-sub">프로토타입용 예시 약관이에요. 선택 항목은 동의하지 않아도 가입할 수 있어요.</p>
        </>
      )}

      {step === 1 && (
        <div className="space-y-5">
          <h2 className="font-display text-[22px] leading-snug font-bold">이메일로 본인확인할게요</h2>
          <Field label="이름" autoComplete="name" placeholder="홍길동" value={f.name} onChange={set('name')} error={f.name && nameErr ? nameErr : undefined} />
          <EmailVerify email={f.email} onEmail={(v) => { setF({ ...f, email: v }); setVerified(false); }} verified={verified} onVerified={() => setVerified(true)} send={sendSignupCode} />
          <p className="text-[13px] text-sub">인증한 이메일이 로그인 아이디가 돼요.</p>
        </div>
      )}

      {step === 2 && (
        <form onSubmit={(e) => e.preventDefault()} noValidate className="space-y-5">
          <h2 className="font-display text-[22px] font-bold">비밀번호를 정해 주세요</h2>
          <input type="email" autoComplete="username" value={f.email} readOnly hidden />
          <Field label="비밀번호" type="password" autoComplete="new-password" placeholder="영문, 숫자, 특수문자 포함 8자 이상" value={f.pw} onChange={set('pw')} error={show('pw')} />
          <Field
            label="비밀번호 확인" type="password" autoComplete="new-password" placeholder="비밀번호 재입력" value={f.pw2} onChange={set('pw2')} error={show('pw2')}
            hint={f.pw2 && f.pw === f.pw2 ? <span className="flex items-center gap-1 text-success"><CircleCheck className="size-3.5" />비밀번호가 일치해요.</span> : undefined}
          />
        </form>
      )}

      {step === 3 && (
        <>
          <h2 className="font-display text-[22px] leading-snug font-bold">{pin1 ? '한 번 더 눌러 주세요' : <>송금·로그인에 쓸<br />간편비밀번호 6자리를 정해 주세요</>}</h2>
          <PinPad key={pin1 ? 'confirm' : 'first'} onComplete={onPin} error={pinErr} busy={loading} message="같은 숫자 반복이나 연속된 숫자는 쓸 수 없어요." />
          {failMsg && <Alert>{failMsg}</Alert>}
          <p className="mt-4 text-[13px] text-sub">가입하면 체험용 내금고 입출금통장과 가상머니 1,000,000원이 지급돼요.</p>
        </>
      )}
    </Page>
  );
}

/** 비밀번호 재설정: 가입한 이메일 인증 → 새 비밀번호. 로그인 잠금도 함께 풀린다. */
export function ResetPassword() {
  const { startReset, resetPassword } = useBank();
  const navigate = useNavigate();
  const loc = useLocation();
  const [email, setEmail] = useState((loc.state as { email?: string } | null)?.email ?? '');
  const [verified, setVerified] = useState(false);
  const [pw, setPw] = useState({ a: '', b: '' });
  const [touched, setTouched] = useState(false);
  const [fail, setFail] = useState('');
  const [loading, setLoading] = useState(false);
  const pwErr = !PW_RE.test(pw.a) ? PW_HINT : undefined;
  const pw2Err = pw.a !== pw.b ? '비밀번호가 일치하지 않아요.' : undefined;

  async function save() {
    setTouched(true);
    if (pwErr || pw2Err) return;
    setLoading(true); setFail('');
    try { await resetPassword(email, pw.a); navigate('/login', { replace: true, state: { reset: email.trim() } }); }
    catch (e) { setFail((e as Error).message); setLoading(false); }
  }

  return (
    <Page back={() => navigate('/login')} title="비밀번호 재설정"
      footer={verified ? <Button size="lg" full loading={loading} onClick={save}>비밀번호 바꾸기</Button> : undefined}>
      {!verified ? (
        <div className="space-y-5 pt-2">
          <h2 className="font-display text-[22px] leading-snug font-bold">가입한 이메일로<br />인증번호를 보내 드릴게요</h2>
          <EmailVerify email={email} onEmail={setEmail} verified={verified} onVerified={() => setVerified(true)} send={startReset} />
          <p className="text-[13px] text-sub">5회 틀려 잠긴 로그인도 비밀번호를 바꾸면 풀려요.</p>
        </div>
      ) : (
        <div className="space-y-5 pt-2">
          <h2 className="font-display text-[22px] font-bold">새 비밀번호를 정해 주세요</h2>
          <input type="email" autoComplete="username" value={email} readOnly hidden />
          <Field label="새 비밀번호" type="password" autoComplete="new-password" placeholder="영문, 숫자, 특수문자 포함 8자 이상" value={pw.a} onChange={(e) => setPw({ ...pw, a: e.target.value })} error={touched ? pwErr : undefined} />
          <Field label="새 비밀번호 확인" type="password" autoComplete="new-password" value={pw.b} onChange={(e) => setPw({ ...pw, b: e.target.value })} error={touched ? pw2Err : undefined} />
          {fail && <Alert>{fail}</Alert>}
        </div>
      )}
    </Page>
  );
}
