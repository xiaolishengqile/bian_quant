import type { Interval, Mode } from './types';

export const intervals: { value: Interval; label: string }[] = [
  { value: '1m', label: '1 分钟' }, { value: '3m', label: '3 分钟' },
  { value: '5m', label: '5 分钟' }, { value: '15m', label: '15 分钟' },
  { value: '30m', label: '30 分钟' }, { value: '1h', label: '1 小时' },
  { value: '4h', label: '4 小时' }, { value: '1d', label: '1 天' },
];
export const modeLabels: Record<Mode, string> = { paper: '模拟盘', testnet: '测试网', live: '实盘' };
export const stateLabels = { stopped: '已停止', running: '运行中', error: '异常暂停', risk_stopped: '风控暂停' };
export function number(value: number | null | undefined, digits = 2): string {
  return value == null || !Number.isFinite(value) ? '—' : value.toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
export function signed(value: number, digits = 2): string { return `${value > 0 ? '+' : ''}${number(value, digits)}`; }
export function price(value: number): string { return number(value, value < 1 ? 5 : 2); }
export function clockTime(time: number | null | undefined): string {
  return time ? new Date(time).toLocaleTimeString('zh-CN', { hour12: false }) : '等待同步';
}
export function dateTime(time: number | null | undefined): string {
  return time ? new Date(time).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '—';
}
export function symbolName(symbol: string): string {
  const names: Record<string, string> = { BTCUSDT: '比特币 · 泰达币永续', ETHUSDT: '以太坊 · 泰达币永续', SOLUSDT: '索拉纳 · 泰达币永续', BNBUSDT: '币安币 · 泰达币永续', XRPUSDT: '瑞波币 · 泰达币永续', DOGEUSDT: '狗狗币 · 泰达币永续' };
  return names[symbol] ?? '泰达币永续';
}
