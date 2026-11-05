import { useState, type ReactNode } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Bell, ChevronDown, ChevronRight, Repeat, LogOut, MessageCircle, Plus, Receipt, RotateCcw, UserRound, Wallet } from 'lucide-react';
import { DrawerStack, TxRow, markOf } from '../components/bank';
import { Button, EmptyState, ErrorState, Logo, Page, SectionTitle, Sheet, Skeleton } from '../components/ui';
import { cn, maskEmail, won } from '../lib/format';
import { THEMES, applyTheme, savedTheme } from '../lib/theme';
import { useBank, useLoad } from '../store';

function greeting() {
  const h = new Date().getHours();
  return h < 6 ? '편안한 밤 보내세요' : h < 12 ? '좋은 아침이에요' : h < 18 ? '좋은 오후예요' : '오늘 하루도 수고했어요';
}

export function Home() {
  const { user, myAccounts, closedAccounts, db, unread } = useBank();
  const navigate = useNavigate();
  const { state, retry } = useLoad();
  const [profile, setProfile] = useState(false);
  const total = myAccounts.reduce((s, a) => s + a.balance, 0);
  const ids = myAccounts.map((a) => a.id);
  const recent = db.txs.filter((t) => ids.includes(t.accountId)).sort((a, b) => b.date.localeCompare(a.date)).slice(0, 3);

  return (
    <Page nav>
      <header className="flex h-16 items-center justify-between">
        <div className="flex items-center gap-2">
          <Logo size={30} />
          <span className="font-display text-[18px] font-bold text-navy">내금고</span>
        </div>
        <div className="flex items-center gap-1">
          <Link to="/notifications" aria-label={unread ? `알림, 새 알림 ${unread}개` : '알림'} className="relative grid size-10 place-items-center rounded-full text-sub hover:bg-surface">
            <Bell className="size-[22px]" />
            {unread > 0 && <span className="num absolute top-1 right-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-brand px-1 text-[11px] font-bold text-white">{unread > 9 ? '9+' : unread}</span>}
          </Link>
          <button onClick={() => setProfile(true)} aria-label="내 정보" className="grid size-10 place-items-center rounded-full bg-surface text-sub hover:bg-line">
            <UserRound className="size-5" />
          </button>
        </div>
      </header>

      <p className="mt-1 text-[22px] leading-snug font-semibold text-sub"><span className="font-bold text-brand">{user?.name}</span>님, {greeting()}</p>

      {state === 'loading' && (
        <div className="mt-8 space-y-3"><Skeleton className="h-16 w-2/3" /><Skeleton className="h-64 rounded-[22px]" /></div>
      )}
      {state === 'error' && <ErrorState onRetry={retry} message="계좌 정보를 불러오지 못했어요." />}
      {state === 'ready' && (
        <>
          <section className="mt-2">
            <h2 className="text-[14px] font-medium text-sub">금고 {myAccounts.length}개에 보관 중</h2>
            <p className="num mt-1 font-display text-[30px] font-bold text-navy">{won(total)}</p>
          </section>

          {myAccounts.length ? (
            <div className="mt-5"><DrawerStack accounts={myAccounts} /></div>
          ) : (
            <EmptyState icon={Wallet} title="아직 금고가 비어 있어요" desc="통장을 만들면 잔액과 거래내역이 여기에 보여요." action={<Button onClick={() => navigate('/products')}>통장 만들기</Button>} />
          )}

          {closedAccounts.length > 0 && (
            <details className="mt-3 text-[14px]">
              <summary className="flex cursor-pointer list-none items-center gap-1 text-sub">해지한 계좌 {closedAccounts.length}개<ChevronDown className="chev size-4 transition-transform" /></summary>
              <ul className="mt-1">
                {closedAccounts.map((a) => (
                  <li key={a.id}><Link to={`/accounts/${a.id}`} className="flex justify-between py-2 text-sub hover:text-ink"><span>{a.name}</span><span className="num">{a.number}</span></Link></li>
                ))}
              </ul>
            </details>
          )}

          <SectionTitle>최근 거래</SectionTitle>
          {recent.length ? (
            <div className="rounded-2xl border border-line px-4 py-1">
              {recent.map((t) => <TxRow key={t.id} tx={t} showBalance={false} tone={markOf(myAccounts, t.accountId)} onClick={() => navigate(`/accounts/${t.accountId}`)} />)}
            </div>
          ) : (
            <EmptyState icon={Receipt} title="아직 거래내역이 없어요" desc="송금하거나 입금받으면 최근 3건이 여기에 보여요." />
          )}

          <nav className="mt-8 divide-y divide-line border-y border-line" aria-label="바로가기">
            <ShortCut to="/products" icon={<Plus className="size-5" />} title="새 통장 만들기" desc="입출금통장 5종 금리 비교" />
            <ShortCut to="/auto-transfers" icon={<Repeat className="size-5" />} title="자동이체" desc="월세·생활비를 정해진 날 자동으로" />
            <ShortCut to="/assistant" icon={<MessageCircle className="size-5" />} title="AI 어시스턴트에게 묻기" desc="잔액 조회와 송금을 대화로" />
          </nav>
        </>
      )}

      <ProfileSheet open={profile} onClose={() => setProfile(false)} email={user?.email ?? ''} />
    </Page>
  );
}

function ShortCut({ to, icon, title, desc }: { to: string; icon: ReactNode; title: string; desc: string }) {
  return (
    <Link to={to} className="flex items-center gap-3 py-4 hover:bg-surface/60">
      <span className="text-navy">{icon}</span>
      <span className="flex-1">
        <span className="block text-[15px] font-semibold">{title}</span>
        <span className="block text-[13px] text-sub">{desc}</span>
      </span>
      <ChevronRight className="size-5 text-mute" />
    </Link>
  );
}

function ProfileSheet({ open, onClose, email }: { open: boolean; onClose: () => void; email: string }) {
  const { user, logout, resetDemo, simulateError, setSimulateError, toast } = useBank();
  return (
    <Sheet open={open} onClose={onClose} title="내 정보">
      <div className="flex items-center gap-3 rounded-2xl bg-surface p-4">
        <span className="grid size-11 place-items-center rounded-full bg-paper text-navy"><UserRound className="size-6" /></span>
        <div>
          <p className="font-semibold">{user?.name}</p>
          <p className="text-[13px] text-sub">{maskEmail(email)}</p>
        </div>
      </div>
      <Link to="/settings" onClick={onClose} className="mt-3 flex items-center justify-between border-b border-line py-4 text-[15px] font-medium">
        계정 관리<ChevronRight className="size-5 text-mute" />
      </Link>
      <ThemePicker />
      <p className="mt-6 mb-2 text-[13px] font-medium text-sub">프로토타입 설정</p>
      <label className="flex cursor-pointer items-center justify-between py-3">
        <span>
          <span className="block text-[15px]">API 오류 시뮬레이션</span>
          <span className="block text-[13px] text-sub">조회·송금·챗봇 요청이 실패하도록 설정</span>
        </span>
        <input type="checkbox" role="switch" checked={simulateError} onChange={(e) => setSimulateError(e.target.checked)} className="size-5 accent-brand" />
      </label>
      <button className="flex w-full items-center gap-2 py-3 text-[15px]" onClick={() => { resetDemo(); toast('데모 데이터를 초기화했어요'); onClose(); }}>
        <RotateCcw className="size-4 text-sub" />데모 데이터 초기화
      </button>
      <button className="flex w-full items-center gap-2 py-3 text-[15px] text-danger" onClick={logout}>
        <LogOut className="size-4" />로그아웃
      </button>
      <p className="mt-4 text-[12px] text-sub">모든 계좌·거래는 프로토타입용 가상 데이터예요.</p>
    </Sheet>
  );
}

function ThemePicker() {
  const [theme, setTheme] = useState(savedTheme);
  return (
    <div className="mt-6">
      <p className="mb-3 text-[13px] font-medium text-sub">색 테마</p>
      <div className="grid grid-cols-4 gap-2" role="radiogroup" aria-label="색 테마">
        {THEMES.map((t) => (
          <button
            key={t.id}
            role="radio"
            aria-checked={theme === t.id}
            onClick={() => { applyTheme(t.id); setTheme(t.id); }}
            className={cn('flex flex-col items-center gap-1.5 rounded-2xl border py-3 text-[13px]', theme === t.id ? 'border-ink font-semibold' : 'border-line text-sub')}
          >
            <span className="size-6 rounded-full" style={{ background: t.swatch }} />
            {t.label}
          </button>
        ))}
      </div>
    </div>
  );
}
