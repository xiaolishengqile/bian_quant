export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) { super(message); this.status = status; }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      credentials: 'same-origin',
      ...init,
      signal: init.signal ? AbortSignal.any([init.signal, AbortSignal.timeout(45000)]) : AbortSignal.timeout(45000),
      headers: { ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new ApiError('暂时无法连接服务，请检查后端是否运行后重试。', 0);
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    throw new ApiError(typeof detail === 'string' ? detail : response.status === 401 ? '登录已失效，请重新输入访问口令。' : `请求未完成（${response.status}），请稍后重试。`, response.status);
  }
  if (!body) throw new ApiError('服务返回了无法读取的数据，请稍后重试。', response.status);
  return body as T;
}

export function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : '操作未完成，请稍后重试。';
}
