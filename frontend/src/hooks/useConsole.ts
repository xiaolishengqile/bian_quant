import { useCallback, useEffect, useRef, useState } from 'react';
import { ApiError, messageOf, request } from '../api';
import type { ConsoleState, StrategyConfig, SymbolResponse } from '../types';

export function useConsole() {
  const [auth, setAuth] = useState<{ required: boolean; authenticated: boolean } | null>(null);
  const [state, setState] = useState<ConsoleState | null>(null);
  const [symbols, setSymbols] = useState<SymbolResponse | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const [lastSync, setLastSync] = useState<number | null>(null);
  const pending = useRef(false);
  const refreshPending = useRef(false);
  const revision = useRef(0);

  const handleError = useCallback((err: unknown) => {
    setError(messageOf(err));
    if (err instanceof ApiError && err.status === 401) { setAuth({ required: true, authenticated: false }); setState(null); }
  }, []);
  const checkAuth = useCallback(async () => {
    setError('');
    try { setAuth(await request('/auth')); } catch (err) { handleError(err); }
  }, [handleError]);
  useEffect(() => { void checkAuth(); }, [checkAuth]);

  const refresh = useCallback(async () => {
    if (pending.current || refreshPending.current) return;
    refreshPending.current = true;
    const current = ++revision.current;
    setRefreshing(true);
    try {
      const next = await request<ConsoleState>('/state');
      if (current === revision.current) { setState(next); setLastSync(Date.now()); setError(''); }
    } catch (err) { if (current === revision.current) handleError(err); }
    finally { refreshPending.current = false; if (current === revision.current) setRefreshing(false); }
  }, [handleError]);

  useEffect(() => {
    if (!auth?.authenticated) return;
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [auth?.authenticated, refresh]);
  const sourceKey = state ? `${state.config.mode}:${state.config.market_source}` : '';
  useEffect(() => {
    if (!auth?.authenticated || !sourceKey) return;
    const controller = new AbortController();
    request<SymbolResponse>('/symbols', { signal: controller.signal }).then(setSymbols).catch(err => {
      if (!controller.signal.aborted) setSymbols({ symbols: [], source: 'binance', error: messageOf(err) });
    });
    return () => controller.abort();
  }, [auth?.authenticated, sourceKey]);
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(''), 5000);
    return () => window.clearTimeout(timer);
  }, [notice]);

  async function login(password: string) {
    setBusy('login'); setError('');
    try { await request('/login', { method: 'POST', body: JSON.stringify({ password }) }); await checkAuth(); }
    catch (err) { handleError(err); }
    finally { setBusy(''); }
  }
  async function logout() {
    setBusy('logout');
    try { await request('/logout', { method: 'POST' }); setState(null); await checkAuth(); }
    catch (err) { handleError(err); }
    finally { setBusy(''); }
  }
  async function mutate(action: string, message: string, body?: unknown): Promise<boolean> {
    if (pending.current) return false;
    pending.current = true; ++revision.current;
    setBusy(action); setError(''); setNotice(''); setRefreshing(false);
    try {
      const next = await request<ConsoleState>(`/${action}`, { method: action === 'config' ? 'PUT' : 'POST', body: body === undefined ? undefined : JSON.stringify(body) });
      setState(next); setLastSync(Date.now()); setNotice(message); return true;
    } catch (err) { handleError(err); return false; }
    finally { pending.current = false; setBusy(''); }
  }
  return {
    auth, state, symbols, error, notice, busy, refreshing, lastSync, checkAuth, refresh, login, logout,
    start: () => mutate('start', '策略已启动，等待新的收盘信号。'),
    stop: () => mutate('stop', '已停止新开仓，已有持仓继续监控止盈止损。'),
    flatten: () => mutate('flatten', '平仓操作已完成，请核对持仓与成交记录。'),
    resetPaper: () => mutate('reset-paper', '模拟账户已重置。'),
    saveConfig: (config: StrategyConfig) => mutate('config', '策略配置已保存，下次运行将使用新参数。', config),
  };
}
