import { createPortal } from 'react-dom';
import { useEffect, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Check, ChevronLeft, CircleAlert, CreditCard, House, LoaderCircle, MessageCircle, PiggyBank, RotateCcw, X, type LucideIcon } from 'lucide-react';
import { cn } from '../lib/format';
import { useBank } from '../store';

export function Logo({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" aria-hidden>
      <rect width="40" height="40" rx="12" style={{ fill: 'var(--color-brand)' }} />
      <circle cx="20" cy="20" r="10.5" fill="#FFFFFF" />
      <circle cx="20" cy="20" r="4" style={{ fill: 'var(--color-brand)' }} />
      <rect x="18.75" y="9.5" width="2.5" height="5" rx="1.25" style={{ fill: 'var(--color-brand)' }} />
    </svg>
  );
}

// ── Button ─────────────────────────────────────────────
type BtnProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost' | 'navy' | 'outline';
  size?: 'lg' | 'md' | 'sm';
  loading?: boolean;
  full?: boolean;
};
const V = {
  primary: 'bg-brand text-white hover:bg-brand-dark active:bg-brand-dark disabled:opacity-35',
  secondary: 'bg-surface text-ink hover:bg-line disabled:text-mute',
  ghost: 'text-sub hover:bg-surface',
  navy: 'bg-navy text-paper hover:bg-navy-2',
  outline: 'border border-line bg-paper text-ink hover:bg-surface',
};
const S = { lg: 'h-14 rounded-full px-6 text-[17px]', md: 'h-11 rounded-full px-5 text-[15px]', sm: 'h-9 rounded-full px-3.5 text-sm' };

export function Button({ variant = 'primary', size = 'md', loading, full, className, children, disabled, ...rest }: BtnProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cn('inline-flex shrink-0 items-center justify-center gap-1.5 font-semibold transition-colors disabled:cursor-not-allowed', V[variant], S[size], full && 'w-full', className)}
    >
      {loading && <LoaderCircle className="size-5 animate-spin" />}
      {children}
    </button>
  );
}

// ── Page layout ────────────────────────────────────────
export function Page({ title, back, nav, footer, right, children, className }: {
  title?: string; back?: boolean | (() => void); nav?: boolean; footer?: ReactNode; right?: ReactNode; children: ReactNode; className?: string;
}) {
  const navigate = useNavigate();
  const loc = useLocation();
  const goBack = typeof back === 'function' ? back : () => (loc.key === 'default' ? navigate('/') : navigate(-1));
  return (
    <div className="flex min-h-dvh flex-col">
      {(title !== undefined || back) && (
        <header className="sticky top-0 z-30 flex h-14 items-center gap-1 bg-paper/95 px-2 backdrop-blur">
          {back ? (
            <button onClick={goBack} aria-label="뒤로가기" className="grid size-10 place-items-center rounded-full hover:bg-surface">
              <ChevronLeft className="size-6" />
            </button>
          ) : <div className="w-3" />}
          <h1 className="flex-1 truncate text-[17px] font-semibold">{title}</h1>
          {right}
        </header>
      )}
      <main className={cn('flex-1 px-5', nav && 'pb-24', footer ? 'pb-32' : undefined, className)}>{children}</main>
      {footer && (
        <div className="fixed bottom-0 left-1/2 z-30 w-full max-w-[430px] -translate-x-1/2 bg-gradient-to-t from-paper from-70% to-paper/0 px-5 pt-6 pb-[max(20px,env(safe-area-inset-bottom))]">
          {footer}
        </div>
      )}
      {nav && <BottomNav />}
    </div>
  );
}

const TABS: { to: string; label: string; icon: LucideIcon; match: (p: string) => boolean }[] = [
  { to: '/', label: '홈', icon: House, match: (p) => p === '/' || p.startsWith('/accounts') },
  { to: '/products', label: '상품', icon: PiggyBank, match: (p) => p.startsWith('/products') },
  { to: '/cards', label: '카드', icon: CreditCard, match: (p) => p.startsWith('/cards') },
  { to: '/assistant', label: 'AI', icon: MessageCircle, match: (p) => p.startsWith('/assistant') },
];

export function BottomNav() {
  const { pathname } = useLocation();
  return (
    <nav className="fixed bottom-0 left-1/2 z-40 w-full max-w-[430px] -translate-x-1/2 border-t border-line bg-paper/95 pb-[env(safe-area-inset-bottom)] backdrop-blur" aria-label="주요 메뉴">
      <ul className="grid h-16 grid-cols-4">
        {TABS.map(({ to, label, icon: Icon, match }) => {
          const on = match(pathname);
          return (
            <li key={to}>
              <Link to={to} aria-current={on ? 'page' : undefined} className={cn('flex h-full flex-col items-center justify-center gap-0.5 text-[11px] font-medium transition-colors', on ? 'text-brand' : 'text-sub hover:text-ink')}>
                <span className={cn('grid h-7 w-12 place-items-center rounded-full transition-colors', on && 'bg-brand-soft')}>
                  <Icon className="size-[22px]" strokeWidth={on ? 2.3 : 1.9} />
                </span>
                {label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

// ── Form ───────────────────────────────────────────────
export function Field({ label, error, hint, right, ...input }: InputHTMLAttributes<HTMLInputElement> & { label: string; error?: string; hint?: ReactNode; right?: ReactNode }) {
  return (
    <label className="block">
      <span className="mb-2 block text-[13px] font-medium text-sub">{label}</span>
      <span className="flex gap-2">
        <input
          {...input}
          aria-invalid={!!error}
          className={cn(
            'h-13 w-full min-w-0 rounded-xl border bg-paper px-4 text-[16px] outline-none transition-colors placeholder:text-sub focus:border-brand',
            error ? 'border-danger' : 'border-line',
          )}
        />
        {right}
      </span>
      {error ? <span className="mt-1.5 flex items-center gap-1 text-[13px] text-danger"><CircleAlert className="size-3.5" />{error}</span>
        : hint ? <span className="mt-1.5 block text-[13px]">{hint}</span> : null}
    </label>
  );
}

export function Checkbox({ checked, onChange, children, strong }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode; strong?: boolean }) {
  return (
    <label className="flex cursor-pointer items-center gap-3 py-2">
      <input type="checkbox" className="peer sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className={cn('grid size-6 shrink-0 place-items-center rounded-full transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-brand/40', checked ? 'bg-brand text-white' : 'bg-line text-white')}>
        <Check className="size-4" strokeWidth={3} />
      </span>
      <span className={cn('flex-1 text-[15px]', strong && 'font-semibold')}>{children}</span>
    </label>
  );
}

// ── Feedback ───────────────────────────────────────────
export function Steps({ steps, current }: { steps: string[]; current: number }) {
  return (
    <ol className="flex gap-1.5 pt-1 pb-6" aria-label={`${steps.length}단계 중 ${current + 1}단계`}>
      {steps.map((s, i) => (
        <li key={s} className="flex-1">
          <div className={cn('h-1 rounded-full transition-colors', i <= current ? 'bg-brand' : 'bg-line')} />
          <span className={cn('mt-1.5 block text-[11px]', i === current ? 'font-semibold text-brand' : 'text-sub')}>{s}</span>
        </li>
      ))}
    </ol>
  );
}

export function EmptyState({ icon: Icon, title, desc, action }: { icon: LucideIcon; title: string; desc?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-14 text-center">
      <div className="mb-4 grid size-14 place-items-center rounded-full bg-surface text-mute"><Icon className="size-7" /></div>
      <p className="text-[16px] font-semibold">{title}</p>
      {desc && <p className="mt-1 text-[14px] text-sub">{desc}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}

export function ErrorState({ onRetry, message = '정보를 불러오지 못했어요.' }: { onRetry: () => void; message?: string }) {
  return (
    <div className="flex flex-col items-center px-6 py-14 text-center">
      <div className="mb-4 grid size-14 place-items-center rounded-full bg-danger-soft text-danger"><CircleAlert className="size-7" /></div>
      <p className="text-[16px] font-semibold">{message}</p>
      <p className="mt-1 text-[14px] text-sub">네트워크 상태를 확인한 뒤 다시 시도해 주세요.</p>
      <Button variant="secondary" className="mt-5" onClick={onRetry}><RotateCcw className="size-4" />다시 시도</Button>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn('animate-pulse rounded-xl bg-surface', className)} />;
}
export function ListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-4 py-4" aria-busy="true" aria-label="불러오는 중">
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="flex-1 space-y-2"><Skeleton className="h-4 w-1/2" /><Skeleton className="h-3 w-1/3" /></div>
          <Skeleton className="h-4 w-20" />
        </div>
      ))}
    </div>
  );
}

export function Sheet({ open, onClose, title, children }: { open: boolean; onClose: () => void; title?: string; children: ReactNode }) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose();
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/40" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()} className="rise max-h-[85dvh] w-full max-w-[430px] overflow-y-auto rounded-t-3xl bg-paper px-6 pt-5 pb-[max(24px,env(safe-area-inset-bottom))]">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-[18px] font-bold">{title}</h2>
          <button onClick={onClose} aria-label="닫기" className="grid size-9 place-items-center rounded-full hover:bg-surface"><X className="size-5" /></button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}

export function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2.5 text-[15px]">
      <span className="shrink-0 text-sub">{label}</span>
      <span className="text-right font-medium">{children}</span>
    </div>
  );
}

export function Toast() {
  const { toastMsg } = useBank();
  if (!toastMsg) return null;
  return (
    <div role="status" className="rise fixed bottom-24 left-1/2 z-[60] -translate-x-1/2 rounded-full bg-ink/90 px-5 py-3 text-[14px] text-white shadow-lg">
      {toastMsg}
    </div>
  );
}

export function SectionTitle({ children, right }: { children: ReactNode; right?: ReactNode }) {
  return (
    <div className="mt-8 mb-3 flex items-center justify-between">
      <h2 className="text-[18px] font-bold">{children}</h2>
      {right}
    </div>
  );
}
