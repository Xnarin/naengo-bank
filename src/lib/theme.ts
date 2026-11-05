// 색 테마: <html data-theme>로 CSS 변수를 바꾼다. 기본(violet)은 속성 없음.
export const THEMES = [
  { id: 'violet', label: '바이올렛', swatch: '#5b4bdb' },
  { id: 'mono', label: '모노', swatch: '#18181b' },
  { id: 'teal', label: '틸', swatch: '#0f766e' },
  { id: 'coral', label: '코랄', swatch: '#c2410c' },
] as const;
export type ThemeId = (typeof THEMES)[number]['id'];
const DEFAULT: ThemeId = 'violet';
const KEY = 'naengo-theme-v2';

export function applyTheme(id: ThemeId) {
  if (id === DEFAULT) delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = id;
  try { localStorage.setItem(KEY, id); } catch { /* 저장 불가 시 이번 세션만 */ }
}

export function savedTheme(): ThemeId {
  try {
    const v = localStorage.getItem(KEY);
    if (THEMES.some((t) => t.id === v)) return v as ThemeId;
  } catch { /* noop */ }
  return DEFAULT;
}
