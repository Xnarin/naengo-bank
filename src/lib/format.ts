export const won = (n: number) => `${n.toLocaleString('ko-KR')}원`;
export const signedWon = (n: number, type: 'in' | 'out') => `${type === 'in' ? '+' : '-'}${won(n)}`;

/** 상대 계좌: 123-***-**9012 */
export const maskAccount = (no: string) => {
  const p = no.split('-');
  return p.length === 3 ? `${p[0]}-***-**${p[2].slice(-4)}` : no.replace(/\d(?=\d{4})/g, '*');
};
export const maskName = (n: string) => (n.length <= 2 ? `${n[0]}*` : `${n[0]}${'*'.repeat(n.length - 2)}${n.at(-1)}`);
export const maskEmail = (e: string) => {
  const [u, d] = e.split('@');
  return `${u.slice(0, 2)}***@${d}`;
};

/** 숫자만 받아 123-4567-8901 형태로 */
export const formatAccountInput = (v: string) => {
  const d = v.replace(/\D/g, '').slice(0, 11);
  return [d.slice(0, 3), d.slice(3, 7), d.slice(7)].filter(Boolean).join('-');
};

const WD = ['일', '월', '화', '수', '목', '금', '토'];
export const fmtDay = (iso: string) => {
  const d = new Date(iso);
  return `${d.getMonth() + 1}월 ${d.getDate()}일 (${WD[d.getDay()]})`;
};
export const fmtTime = (iso: string) => new Date(iso).toLocaleTimeString('ko-KR', { hour: '2-digit', minute: '2-digit', hour12: false });
export const fmtDateTime = (iso: string) => {
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}.${p(d.getMonth() + 1)}.${p(d.getDate())} ${fmtTime(iso)}`;
};
export const dayKey = (iso: string) => new Date(iso).toDateString();

export function groupByDay<T extends { date: string }>(items: T[]) {
  const map = new Map<string, T[]>();
  for (const it of items) map.set(dayKey(it.date), [...(map.get(dayKey(it.date)) ?? []), it]);
  return [...map.values()];
}

export const cn = (...c: (string | false | null | undefined)[]) => c.filter(Boolean).join(' ');
