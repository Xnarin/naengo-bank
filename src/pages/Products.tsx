import { useState, type ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { BadgeCheck, ChevronDown, CircleAlert, Copy, PackageX } from 'lucide-react';
import { RateText, shortName } from '../components/bank';
import { Button, Checkbox, EmptyState, ErrorState, ListSkeleton, Page, Row, Sheet, Steps } from '../components/ui';
import { productById, products, type Account } from '../data/mock';
import { cn } from '../lib/format';
import { useBank, useLoad } from '../store';

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
const TERMS = [
  { id: 't1', label: '[필수] 예금거래기본약관', required: true },
  { id: 't2', label: '[필수] 입출금이 자유로운 예금 약관', required: true },
  { id: 't3', label: '[필수] 개인(신용)정보 수집·이용 동의', required: true },
  { id: 't4', label: '[선택] 상품 및 이벤트 안내 수신 동의', required: false },
];

export function OpenAccount() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user, openAccount, toast } = useBank();
  const p = productById(id ?? '');
  const [step, setStep] = useState(0);
  const [checked, setChecked] = useState<boolean[]>([]);
  const [agreed, setAgreed] = useState<Record<string, boolean>>({});
  const [viewing, setViewing] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [created, setCreated] = useState<Account | null>(null);

  if (!p) return <Page back title="계좌 개설"><EmptyState icon={PackageX} title="상품을 찾을 수 없어요" /></Page>;

  const allConditions = p.conditions.every((_, i) => checked[i]);
  const requiredAgreed = TERMS.filter((t) => t.required).every((t) => agreed[t.id]);
  const allAgreed = TERMS.every((t) => agreed[t.id]);

  async function submit() {
    setLoading(true);
    setError('');
    try { setCreated(await openAccount(p!.id)); }
    catch (e) { setError((e as Error).message); }
    finally { setLoading(false); }
  }

  if (created) {
    return (
      <Page footer={
        <div className="grid grid-cols-2 gap-2">
          <Button size="lg" variant="secondary" onClick={() => navigate('/', { replace: true })}>홈으로</Button>
          <Button size="lg" onClick={() => navigate(`/accounts/${created.id}`, { replace: true })}>내 계좌 보기</Button>
        </div>
      }>
        <div className="rise flex flex-col items-center pt-28 text-center">
          <span className="grid size-16 place-items-center rounded-full bg-brand text-white"><BadgeCheck className="size-8" /></span>
          <p className="mt-6 font-display text-[22px] font-bold">계좌가 개설됐어요</p>
          <p className="mt-1 text-[15px] text-sub">{created.name}</p>
          <button onClick={() => navigator.clipboard?.writeText(created.number).then(() => toast('계좌번호가 복사됐어요'), () => {})}
            className="num mt-6 inline-flex items-center gap-2 rounded-2xl bg-surface px-5 py-4 font-display text-[20px] font-bold" aria-label="새 계좌번호 복사">
            내금고 {created.number}<Copy className="size-4 text-sub" />
          </button>
          <p className="mt-4 text-[13px] text-sub">프로젝트 내 가상 계좌예요.</p>
        </div>
      </Page>
    );
  }

  const footer = [
    <Button size="lg" full disabled={!allConditions} onClick={() => setStep(1)}>다음</Button>,
    <Button size="lg" full disabled={!requiredAgreed} onClick={() => setStep(2)}>동의하고 계속</Button>,
    <Button size="lg" full loading={loading} onClick={submit}>계좌 개설하기</Button>,
  ][step];

  return (
    <Page back={step > 0 ? () => setStep(step - 1) : true} title="계좌 개설" footer={footer}>
      <Steps steps={['상품 확인', '약관 동의', '최종 확인']} current={step} />

      {step === 0 && (
        <>
          <div className="rounded-2xl bg-surface p-5">
            <p className="text-[18px] font-bold">{p.name}</p>
            <p className="text-[14px] text-sub">{p.tagline}</p>
            <div className="mt-3"><RateText p={p} /></div>
          </div>
          <h2 className="mt-8 mb-2 text-[17px] font-bold">가입 조건을 확인해 주세요</h2>
          {p.conditions.map((c, i) => (
            <Checkbox key={c} checked={!!checked[i]} onChange={(v) => setChecked((s) => { const n = [...s]; n[i] = v; return n; })}>{c}</Checkbox>
          ))}
          <p className="mt-3 text-[12px] text-sub">가입 조건은 예시 데이터이며, 프로토타입에서는 본인 확인을 생략해요.</p>
        </>
      )}

      {step === 1 && (
        <>
          <h2 className="mb-4 font-display text-[22px] font-bold">약관에 동의해 주세요</h2>
          <div className="rounded-2xl bg-surface px-4 py-2">
            <Checkbox strong checked={allAgreed} onChange={(v) => setAgreed(Object.fromEntries(TERMS.map((t) => [t.id, v])))}>전체 동의</Checkbox>
          </div>
          <div className="mt-2 px-4">
            {TERMS.map((t) => (
              <div key={t.id} className="flex items-center">
                <div className="flex-1"><Checkbox checked={!!agreed[t.id]} onChange={(v) => setAgreed({ ...agreed, [t.id]: v })}>{t.label}</Checkbox></div>
                <button onClick={() => setViewing(t.label)} className="px-2 text-[13px] text-sub underline">보기</button>
              </div>
            ))}
          </div>
          <Sheet open={!!viewing} onClose={() => setViewing(null)} title={viewing?.replace(/^\[.+?\]\s*/, '') ?? ''}>
            <p className="text-[14px] leading-relaxed text-sub">프로토타입용 예시 약관이에요. 실제 서비스에서는 이 영역에 약관 전문이 표시돼요. 내금고는 계좌 개설과 거래를 위해 필요한 최소한의 정보만 수집하며, 관련 법령에 따라 안전하게 보관해요.</p>
            <Button full size="lg" className="mt-6" onClick={() => {
              const t = TERMS.find((x) => x.label === viewing);
              if (t) setAgreed({ ...agreed, [t.id]: true });
              setViewing(null);
            }}>동의하기</Button>
          </Sheet>
        </>
      )}

      {step === 2 && (
        <>
          <h2 className="font-display text-[22px] leading-snug font-bold">아래 내용으로<br />계좌를 개설할까요?</h2>
          <div className="mt-6 rounded-2xl bg-surface px-5 py-3">
            <Row label="상품">{p.name}</Row>
            <Row label="적용 금리"><span className="num">최고 연 {p.rate.toFixed(1)}%</span></Row>
            <Row label="예금주">{user?.name}</Row>
            <Row label="개설 시 잔액"><span className="num">0원</span></Row>
            <Row label="선택 동의">{agreed.t4 ? '동의' : '미동의'}</Row>
          </div>
          {error && <p role="alert" className="mt-4 flex items-center gap-1.5 rounded-xl bg-danger-soft px-4 py-3 text-[14px] text-danger"><CircleAlert className="size-4 shrink-0" />{error}</p>}
          <p className="mt-4 text-[13px] text-sub">실제 금융계좌가 아닌 프로젝트 내 가상 계좌가 개설돼요.</p>
        </>
      )}
    </Page>
  );
}
