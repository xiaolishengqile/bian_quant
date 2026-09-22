import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { Activity, Inbox, LoaderCircle, X } from 'lucide-react';
import { number, signed, symbolName } from '../format';

export function Logo({ small = false }: { small?: boolean }) {
  return <span className={`brand-mark ${small ? 'small' : ''}`} aria-hidden="true"><svg viewBox="0 0 32 32"><path d="M5 22 13 7h6l-8 15zM14 25 22 10h5l-8 15z" fill="currentColor" /></svg></span>;
}
export function Unit() { return <span className="unit"><span>USDT</span><small>泰达币</small></span>; }
export function Coin({ symbol, compact = false }: { symbol: string; compact?: boolean }) {
  return <span className={`coin-label ${compact ? 'compact' : ''}`}><strong>{symbol.replace('USDT', '')}<span className="muted"> / USDT</span></strong><small>{symbolName(symbol)}</small></span>;
}
export function Pnl({ value, percent = false, digits = 2 }: { value: number; percent?: boolean; digits?: number }) {
  return <span className={`numeric ${value > 0 ? 'positive' : value < 0 ? 'negative' : ''}`}>{signed(value, digits)}{percent && '%'}</span>;
}
export function Badge({ children, tone = 'neutral', dot = false }: { children: ReactNode; tone?: string; dot?: boolean }) {
  return <span className={`badge ${tone}`}>{dot && <span className="status-dot" />}{children}</span>;
}
export function Loading({ text = '正在同步数据' }: { text?: string }) {
  return <div className="loading-state" role="status"><LoaderCircle size={22} className="spin" /><span>{text}</span></div>;
}
export function Empty({ title, children, icon = true }: { title: string; children?: ReactNode; icon?: boolean }) {
  return <div className="empty-state">{icon && <span className="empty-icon"><Inbox size={23} strokeWidth={1.4} /></span>}<strong>{title}</strong>{children && <p>{children}</p>}</div>;
}
export function PanelHeading({ title, extra, icon = false }: { title: string; extra?: ReactNode; icon?: boolean }) {
  return <div className="panel-heading"><h2>{icon && <Activity size={16} />}{title}</h2>{extra}</div>;
}
export function Metric({ label, value, children, accent = false }: { label: ReactNode; value: ReactNode; children?: ReactNode; accent?: boolean }) {
  return <div className={`metric ${accent ? 'accent' : ''}`}><span className="metric-label">{label}</span><div className="metric-value numeric">{typeof value === 'number' ? number(value) : value}</div><div className="metric-note">{children}</div></div>;
}
export function Modal({ title, children, onClose, onConfirm, confirmLabel = '确认', danger = false, busy = false, error = '', hideCancel = false }: {
  title: string; children: ReactNode; onClose: () => void; onConfirm: () => void; confirmLabel?: string; danger?: boolean; busy?: boolean; error?: string; hideCancel?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(onClose);
  closeRef.current = onClose;
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    const overflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    ref.current?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) closeRef.current();
      if (event.key !== 'Tab') return;
      const elements = ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled), [href], input:not(:disabled), select:not(:disabled)');
      if (!elements?.length) { event.preventDefault(); return; }
      const first = elements[0], last = elements[elements.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) { last.focus(); event.preventDefault(); }
      else if (!event.shiftKey && (document.activeElement === last || document.activeElement === ref.current)) { first.focus(); event.preventDefault(); }
    };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); document.body.style.overflow = overflow; previous?.focus(); };
  }, [busy]);
  return <div className="modal-backdrop" onClick={() => !busy && onClose()}><div className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title" tabIndex={-1} ref={ref} onClick={event => event.stopPropagation()}>
    <div className="modal-heading"><h2 id="modal-title">{title}</h2><button className="icon-button" onClick={onClose} disabled={busy} aria-label="关闭确认框"><X size={18} /></button></div>
    <div className="modal-body">{children}{error && <div className="inline-error" role="alert">{error}</div>}</div>
    <div className="modal-actions">{!hideCancel && <button className="button secondary" disabled={busy} onClick={onClose}>取消</button>}<button className={`button ${danger ? 'danger-solid' : 'primary'}`} disabled={busy} onClick={onConfirm}>{busy && <LoaderCircle size={15} className="spin" />}{confirmLabel}</button></div>
  </div></div>;
}
