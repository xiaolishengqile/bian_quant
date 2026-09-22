import { useCallback, useEffect, useRef, useState } from 'react';
import { messageOf, request } from '../api';
import type { Interval, MarketSnapshot } from '../types';

export function useMarket(symbol: string, interval: Interval, sourceKey: string) {
  const [market, setMarket] = useState<MarketSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);
  const controller = useRef<AbortController | null>(null);
  const refresh = useCallback(() => setRefreshKey(value => value + 1), []);
  useEffect(() => {
    let alive = true;
    let active = false;
    setMarket(null); setError(''); setLoading(true);
    async function load() {
      if (active) return;
      active = true;
      controller.current = new AbortController();
      try {
        const next = await request<MarketSnapshot>(`/market?symbol=${encodeURIComponent(symbol)}&interval=${interval}`, { signal: controller.current.signal });
        if (alive) { setMarket(next); setError(next.error ?? ''); }
      } catch (err) {
        if (alive && !(err instanceof DOMException && err.name === 'AbortError')) setError(messageOf(err));
      } finally { if (alive) setLoading(false); active = false; }
    }
    void load();
    const timer = window.setInterval(() => void load(), 15000);
    return () => { alive = false; controller.current?.abort(); window.clearInterval(timer); };
  }, [symbol, interval, sourceKey, refreshKey]);
  return { market, loading, error, refresh };
}
