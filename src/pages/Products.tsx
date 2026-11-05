import { useEffect, useState, type ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { BadgeCheck, ChevronDown, CircleAlert, Copy, PackageX } from 'lucide-react';
import { RateText, shortName } from '../components/bank';
import { Button, Checkbox, EmptyState, ErrorState, ListSkeleton, Page, Row, Sheet, Steps, Field } from '../components/ui';
import { productById, products, type Account } from '../data/mock';
import { cn } from '../lib/format';
import { useBank, useLoad } from '../store';
import { api } from '../api/http';
import type { Term } from '../api/bank';

// ── 목록 ───────────────────────────────────────────────
export function ProductList() {
  const [sort, setSort] = useState<'rec' | 'rate'>('rec');
  const { state, retry } = useLoad();
  const list = sort === 'rate' ? [...products].sort((a, b) => b.rate - a.rate) : products;

  return (
    <Page title="통장 만들기" nav>
      <div className="flex items-baseline justify-between border-b border-line pb-3">
        <p className="text-[14px] text-sub">입출금통장 <span className="num font-semibold text-ink">{products.length}</span></p>
        <div className="flex gap-3 text-[14px]" role="radiogroup" aria-label="정렬">
          {([['rec', '추천순'], ['rate', '금리순']] as const).map(([k, l]) => (
            <button key={k} role="radio" aria-checked={sort === k} onClick={() => setSort(k)} className={cn(sort === k ? 'font-bold text-ink' : 'text-sub hover:text-ink')}>{l}</button>
          ))}
        </div>
      </div>

      {state === 'loading' && <ListSkeleton rows={5} />}
      {state === 'error' && <ErrorState onRetry={retry} message="상품 정보를 불러오지 못했어요." />}
      {state === 'ready' && (
        <>
          <ul className="divide-y divide-line">
            {list.map((p) => (
              <li key={p.id}>
                <Link to={`/products/${p.id}`} className="group flex items-center gap-4 py-5">
                  <div className="min-w-0 flex-1">
                    <p className="text-[16px] font-bold">
                      {shortName(p.name)}<span className="ml-1.5 text-[13px] font-medium text-sub">{p.tag}</span>
                    </p>
                    <p className="mt-0.5 text-[14px] text-sub">{p.tagline}</p>
                    <p className="mt-2 text-[13px] text-sub">{p.benefits.slice(0, 2).join(' · ')}</p>
                  </div>
                  <div className="shrink-0 text-right">
                    <p className="text-[12px] text-sub">최고 연</p>
                    <p className="num font-display text-[22px] font-bold">{p.rate.toFixed(1)}%</p>
                    <p className="num text-[12px] text-sub">기본 {p.baseRate.toFixed(1)}%</p>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[12px] text-sub">금리와 조건은 모두 예시 데이터이며 실제 상품과 무관해요.</p>
        </>
      )}
    </Page>
  );
}

// ── 상세 ───────────────────────────────────────────────
export function ProductDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const p = productById(id ?? '');
  if (!p) return <Page back title="상품 상세"><EmptyState icon={PackageX} title="상품을 찾을 수 없어요" action={<Button onClick={() => navigate('/products')}>상품 목록</Button>} /></Page>;

  return (
    <Page back title="" footer={<Button size="lg" full onClick={() => navigate(`/products/${p.id}/open`)}>계좌 개설하기</Button>}>
      <section className="pb-6">
        <h1 className="font-display text-[24px] font-bold">{p.name}</h1>
        <p className="mt-1 text-[15px] text-sub">{p.tagline}</p>
        <div className="mt-5"><RateText p={p} size="lg" /></div>
        <p className="mt-3 text-[13px] text-sub">{p.tag} · {p.target[0]} · 예시 금리</p>
      </section>

      <div className="-mx-5 h-2 bg-surface" />

      <Section title="적용 금리">
        <div className="overflow-hidden rounded-2xl border border-line">
          {p.rateTable.map((r) => (
            <div key={r.label} className="flex justify-between border-b border-line px-4 py-3 text-[15px] last:border-0">
              <span className="text-sub">{r.label}</span><span className="num font-semibold">{r.rate}</span>
            </div>
          ))}
        </div>
        <p className="mt-2 text-[12px] text-sub">세전 기준 · 예시 금리이며 실제 상품과 무관해요.</p>
      </Section>
      <Section title="가입 대상"><Bullets items={p.target} /></Section>
      <Section title="가입 조건"><Bullets items={p.conditions} /></Section>
      <Section title="상품 혜택"><Bullets items={p.benefits} /></Section>

      <div className="mt-6 divide-y divide-line border-y border-line">
        <Accordion title="유의사항"><Bullets items={p.notices} /></Accordion>
        <Accordion title="자세한 상품 설명">
          <div className="space-y-4">
            {p.details.map((d) => (
              <div key={d.title}>
                <p className="text-[14px] font-semibold">{d.title}</p>
                <p className="mt-1 text-[14px] leading-relaxed text-sub">{d.body}</p>
              </div>
            ))}
          </div>
        </Accordion>
      </div>
    </Page>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="pt-7"><h2 className="mb-3 text-[17px] font-bold">{title}</h2>{children}</section>;
}
function Bullets({ items }: { items: string[] }) {
  return <ul className="space-y-2">{items.map((t) => <li key={t} className="flex gap-2 text-[15px] leading-relaxed"><span className="mt-2.5 size-1 shrink-0 rounded-full bg-mute" />{t}</li>)}</ul>;
}
function Accordion({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className="group">
      <summary className="flex cursor-pointer items-center justify-between py-4 text-[16px] font-semibold">
        {title}<ChevronDown className="chev size-5 text-mute transition-transform" />
      </summary>
      <div className="pb-5">{children}</div>
    </details>
  );
}

// ── 계좌 개설 ───────────────────────────────────────────
export function OpenAccount() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user, openAccount, toast } = useBank();
  const p = productById(id ?? '');
  const [step, setStep] = useState(0);
  const [checked, setChecked] = useState<boolean[]>([]);
  const [terms, setTerms] = useState<Term[]>([]);
  const [agreed, setAgreed] = useState<Record<number, boolean>>({});
  const [viewing, setViewing] = useState<Term | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [created, setCreated] = useState<Account | null>(null);
  const [form, setForm] = useState({ password: '', confirm: '', purpose: '' });
  const loadTerms = () => api<Term[]>('/terms?category=ACCOUNT_OPEN').then((data) => { setTerms(data); setError(''); }).catch((e) => setError((e as Error).message));
  useEffect(() => { void loadTerms(); }, []);
  if (!p) return <Page back title="계좌 개설"><EmptyState icon={PackageX} title="상품을 찾을 수 없어요" /></Page>;
  const requiredAgreed = terms.length > 0 && terms.every((t) => !t.required || agreed[t.id]);
  const allAgreed = terms.length > 0 && terms.every((t) => agreed[t.id]);
  const valid = /^[0-9]{4}$/.test(form.password) && form.password === form.confirm && !!form.purpose.trim();
  async function submit() {
    setLoading(true); setError('');
    try { setCreated(await openAccount(p!.id, { password: form.password, passwordConfirm: form.confirm, purpose: form.purpose.trim(), agreedTermIds: terms.filter((t) => agreed[t.id]).map((t) => t.id) })); }
    catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }
  if (created) return (
    <Page footer={<div className="grid grid-cols-2 gap-2"><Button variant="secondary" size="lg" onClick={() => navigate('/', { replace: true })}>홈으로</Button><Button size="lg" onClick={() => navigate(`/accounts/${created.id}`, { replace: true })}>내 계좌 보기</Button></div>}>
      <div className="rise flex flex-col items-center pt-28 text-center">
        <span className="grid size-16 place-items-center rounded-full bg-brand text-white"><BadgeCheck className="size-8" /></span>
        <h2 className="mt-6 font-display text-[22px] font-bold">계좌가 개설됐어요</h2>
        <p className="mt-1 text-sub">{created.name}</p>
        <button onClick={() => navigator.clipboard?.writeText(created.number).then(() => toast('계좌번호가 복사됐어요'))} className="num mt-6 inline-flex items-center gap-2 rounded-2xl bg-surface px-5 py-4 text-[20px]">{created.number}<Copy className="size-4" /></button>
        <p className="mt-4 text-[13px] text-sub">프로젝트 내 가상 계좌예요.</p>
      </div>
    </Page>
  );
  const footer = [
    <Button full size="lg" disabled={!p.conditions.every((_, i) => checked[i])} onClick={() => setStep(1)}>다음</Button>,
    <Button full size="lg" disabled={!requiredAgreed} onClick={() => setStep(2)}>동의하고 계속</Button>,
    <Button full size="lg" loading={loading} disabled={!valid} onClick={submit}>계좌 개설하기</Button>,
  ][step];
  return (
    <Page back={step ? () => setStep(step - 1) : true} title="계좌 개설" footer={footer}>
      <Steps steps={['상품 확인', '약관 동의', '최종 확인']} current={step} />
      {step === 0 && <>
        <div className="rounded-2xl bg-surface p-5"><p className="text-[18px] font-bold">{p.name}</p><p className="text-[14px] text-sub">{p.tagline}</p><div className="mt-3"><RateText p={p} /></div></div>
        <h2 className="mt-8 mb-2 text-[17px] font-bold">가입 조건을 확인해 주세요</h2>
        {p.conditions.map((condition, i) => <Checkbox key={condition} checked={!!checked[i]} onChange={(v) => setChecked((old) => { const next = [...old]; next[i] = v; return next; })}>{condition}</Checkbox>)}
      </>}
      {step === 1 && <>
        <h2 className="mb-4 text-[22px] font-bold">약관에 동의해 주세요</h2>
        {!terms.length && <Button variant="secondary" onClick={() => void loadTerms()}>약관 다시 불러오기</Button>}
        <Checkbox strong checked={allAgreed} onChange={(v) => setAgreed(Object.fromEntries(terms.map((t) => [t.id, v])))}>전체 동의</Checkbox>
        {terms.map((term) => <div key={term.id} className="flex items-center"><div className="flex-1"><Checkbox checked={!!agreed[term.id]} onChange={(v) => setAgreed({ ...agreed, [term.id]: v })}>{term.required ? '[필수] ' : '[선택] '}{term.title}</Checkbox></div><button onClick={() => setViewing(term)} className="px-2 text-[13px] text-sub underline">보기</button></div>)}
        <Sheet open={!!viewing} onClose={() => setViewing(null)} title={viewing?.title ?? ''}><p className="whitespace-pre-wrap text-[14px] leading-relaxed text-sub">{viewing?.content}</p><Button full className="mt-5" onClick={() => { if (viewing) setAgreed({ ...agreed, [viewing.id]: true }); setViewing(null); }}>동의하기</Button></Sheet>
      </>}
      {step === 2 && <>
        <h2 className="mb-5 text-[22px] font-bold">통장 정보를 정해 주세요</h2>
        <div className="space-y-4">
          <Field label="통장 비밀번호 4자리" type="password" inputMode="numeric" maxLength={4} autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value.replace(/\D/g, '') })} />
          <Field label="통장 비밀번호 확인" type="password" inputMode="numeric" maxLength={4} autoComplete="new-password" value={form.confirm} onChange={(e) => setForm({ ...form, confirm: e.target.value.replace(/\D/g, '') })} error={form.confirm && form.confirm !== form.password ? '비밀번호가 서로 달라요.' : undefined} />
          <Field label="계좌 개설 목적" placeholder="생활비, 급여 수령 등" maxLength={100} value={form.purpose} onChange={(e) => setForm({ ...form, purpose: e.target.value })} />
        </div>
        <div className="mt-6 rounded-2xl bg-surface px-5 py-3"><Row label="상품">{p.name}</Row><Row label="예금주">{user?.name}</Row><Row label="개설 시 잔액">0원</Row></div>
        <p className="mt-4 text-[13px] text-sub">실제 금융계좌가 아닌 프로젝트 내 가상 계좌예요.</p>
      </>}
      {error && <p role="alert" className="mt-4 flex items-center gap-1.5 rounded-xl bg-danger-soft px-4 py-3 text-[14px] text-danger"><CircleAlert className="size-4 shrink-0" />{error}</p>}
    </Page>
  );
}
