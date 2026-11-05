export class BankError extends Error {
  constructor(public code: string, message: string) { super(message); }
}

const TOKEN = 'naengo-access-token';
export const getToken = () => sessionStorage.getItem(TOKEN);
export function setToken(token: string | null) {
  if (token) sessionStorage.setItem(TOKEN, token);
  else sessionStorage.removeItem(TOKEN);
}

export async function api<T>(path: string, body?: unknown, method = body === undefined ? 'GET' : 'POST'): Promise<T> {
  const token = getToken();
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { method, headers: {
      ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    }, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch { throw new BankError('NETWORK', '서버에 연결하지 못했어요. 연결을 확인하고 다시 시도해 주세요.'); }
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && data.code === 'AUTH' && token && token === getToken() && !path.startsWith('/auth/') && path !== '/me/password') {
      setToken(null);
      window.dispatchEvent(new Event('naengo-auth-expired'));
    }
    throw new BankError(data.code === 'USER_LOCKED' ? 'LOGIN_LOCKED' : data.code ?? 'INPUT', data.message ?? '입력 내용을 확인해 주세요.');
  }
  return data as T;
}
