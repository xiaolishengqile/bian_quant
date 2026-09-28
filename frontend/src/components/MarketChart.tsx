import { useMemo, useState } from 'react';
import { Crosshair, RefreshCw, TriangleAlert } from 'lucide-react';
import { clockTime, dateTime, intervals, price, signed } from '../format';
import { useMarket } from '../hooks/useMarket';
import type { Interval, SymbolInfo } from '../types';
import { Badge, Empty, Loading } from './UI';

const W = 900, LEFT = 12, RIGHT = 810, TOP = 18, BOTTOM = 235, IND_TOP = 300, IND_BOTTOM = 386;
export default function MarketChart({ symbol, setSymbol, interval, setInterval, symbols, sourceKey }: {
  symbol: string; setSymbol: (symbol: string) => void; interval: Interval; setInterval: (interval: Interval) => void; symbols: SymbolInfo[]; sourceKey: string;
}) {
  const { market, loading, error, refresh } = useMarket(symbol, interval, sourceKey);
  const [hover, setHover] = useState<number | null>(null);
  const candles = useMemo(() => market?.candles.slice(-90) ?? [], [market]);
  const indicatorMap = useMemo(() => new Map(market?.indicators.map(item => [item.time, item]) ?? []), [market]);
  const active = candles[hover == null ? candles.length - 1 : Math.min(hover, candles.length - 1)];
  const values = candles.flatMap(candle => [candle.low, candle.high]);
  const minimum = values.length ? Math.min(...values) : 0, maximum = values.length ? Math.max(...values) : 1;
  const spread = maximum - minimum || maximum * 0.01 || 1;
  const low = minimum - spread * 0.13, high = maximum + spread * 0.13;
  const step = (RIGHT - LEFT) / Math.max(1, candles.length);
  const x = (index: number) => LEFT + step * (index + 0.5);
  const y = (value: number) => BOTTOM - ((value - low) / (high - low)) * (BOTTOM - TOP);
  const maxVolume = Math.max(1, ...candles.map(candle => candle.volume));
  const indicators = candles.map(candle => indicatorMap.get(candle.time));
  const scale = Math.max(0.00001, ...indicators.flatMap(item => item ? [Math.abs(item.macd ?? 0), Math.abs(item.signal ?? 0), Math.abs(item.histogram ?? 0)] : [0])) * 1.2;
  const mid = (IND_TOP + IND_BOTTOM) / 2;
  const iy = (value: number) => mid - value / scale * ((IND_BOTTOM - IND_TOP) / 2);
  function indicatorLine(field: 'macd' | 'signal') {
    let started = false;
    return indicators.map((indicator, index) => { const value = indicator?.[field]; if (value == null) { started = false; return ''; } const part = `${started ? 'L' : 'M'}${x(index)},${iy(value)}`; started = true; return part; }).join(' ');
  }
  const lastClose = candles.at(-1)?.close;
  return <section className="panel market-panel">
    <div className="market-heading"><div className="market-pair"><span className="coin-emblem">{symbol.startsWith('BTC') ? '₿' : symbol.startsWith('ETH') ? 'Ξ' : symbol[0]}</span><div><label className="sr-only" htmlFor="chart-symbol">行情交易对</label><select id="chart-symbol" className="symbol-select" value={symbol} onChange={event => { setHover(null); setSymbol(event.target.value); }}>{symbols.map(item => <option key={item.symbol} value={item.symbol}>{item.symbol}</option>)}</select><small>{symbol === 'BTCUSDT' ? '比特币' : symbol === 'ETHUSDT' ? '以太坊' : '数字资产'} · 泰达币永续</small></div></div><div className="market-price"><strong className="numeric">{market ? price(market.last_price) : '—'}</strong><span className={`numeric ${!market || market.change_pct === 0 ? 'muted' : market.change_pct > 0 ? 'positive' : 'negative'}`}>{market ? signed(market.change_pct) : '—'}%<small>区间涨跌</small></span></div><Badge tone={market?.source === 'demo' ? 'gold' : 'neutral'}>{market?.source === 'demo' ? '演示行情' : market ? '币安行情' : '等待行情'}</Badge></div>
    <div className="chart-toolbar"><div className="timeframes" role="group" aria-label="图表周期">{(['1m', '5m', '15m', '1h', '4h', '1d'] as Interval[]).map(value => <button key={value} className={interval === value ? 'selected' : ''} onClick={() => { setHover(null); setInterval(value); }} aria-pressed={interval === value}>{intervals.find(item => item.value === value)?.label}</button>)}</div><div className="chart-tools"><label className="sr-only" htmlFor="chart-interval">全部图表周期</label><select id="chart-interval" value={interval} onChange={event => setInterval(event.target.value as Interval)}>{intervals.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select><span className="chart-tool-divider" /><Crosshair size={15} aria-hidden="true" /><button className="icon-button" onClick={refresh} disabled={loading} aria-label="刷新行情"><RefreshCw size={14} className={loading ? 'spin' : ''} /></button></div></div>
    {error && <div className="chart-error" role="alert"><TriangleAlert size={15} /><span>{error}{market && ' 当前图表为上次成功获取的数据。'}</span><button className="text-button" onClick={refresh}>重试</button></div>}
    {loading && !market ? <div className="chart-placeholder"><Loading text="正在获取蜡烛与指标数据" /></div> : !candles.length ? <div className="chart-placeholder"><Empty title="行情暂不可用">请检查行情来源与网络连接后重试。</Empty></div> : <>
      <div className="ohlc-row"><span className="ohlc-time">{active && dateTime(active.time)}</span>{active && [['开', active.open], ['高', active.high], ['低', active.low], ['收', active.close]].map(([label, value]) => <span key={label}> {label} <b className="numeric">{price(Number(value))}</b></span>)}{active && active.close_time > Date.now() && <span className="unclosed">未收盘</span>}</div>
      <div className="chart-canvas"><svg viewBox={`0 0 ${W} 416`} preserveAspectRatio="none" role="img" tabIndex={0} aria-label={`${symbol} 蜡烛行情和指数平滑异同移动平均线，使用左右方向键逐根查看`} onPointerLeave={() => setHover(null)} onPointerMove={event => { const rect = event.currentTarget.getBoundingClientRect(); const point = (event.clientX - rect.left) / rect.width * W; setHover(Math.max(0, Math.min(candles.length - 1, Math.floor((point - LEFT) / step)))); }} onKeyDown={event => { if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); setHover(Math.min(candles.length - 1, Math.max(0, (hover ?? candles.length - 1) + (event.key === 'ArrowLeft' ? -1 : 1)))); } }}>
        <defs><clipPath id="price-area"><rect x={LEFT} y={TOP} width={RIGHT - LEFT} height={BOTTOM - TOP + 33} /></clipPath></defs>
        {[0, 1, 2, 3, 4].map(index => { const yy = TOP + index * (BOTTOM - TOP) / 4; return <g key={index}><line x1={LEFT} x2={RIGHT} y1={yy} y2={yy} className="chart-grid" /><text x={RIGHT + 12} y={yy + 4} className="chart-axis">{price(high - index / 4 * (high - low))}</text></g>; })}
        {[0, 1, 2, 3, 4, 5].map(index => { const xx = LEFT + index / 5 * (RIGHT - LEFT); return <line key={index} x1={xx} x2={xx} y1={TOP} y2={IND_BOTTOM} className="chart-grid vertical" />; })}
        <g clipPath="url(#price-area)">{candles.map((candle, index) => { const color = candle.close >= candle.open ? '#168466' : '#c6475b'; return <g key={candle.time}><rect x={x(index) - step * 0.31} y={265 - candle.volume / maxVolume * 28} width={Math.max(1, step * 0.62)} height={Math.max(0.5, candle.volume / maxVolume * 28)} fill={color} opacity=".16" /><line x1={x(index)} x2={x(index)} y1={y(candle.high)} y2={y(candle.low)} stroke={color} strokeWidth="1" /><rect x={x(index) - step * 0.3} y={Math.min(y(candle.open), y(candle.close))} width={Math.max(1, step * 0.6)} height={Math.max(1.2, Math.abs(y(candle.close) - y(candle.open)))} fill={color} /></g>; })}</g>
        {lastClose !== undefined && <g><line x1={LEFT} x2={RIGHT} y1={y(lastClose)} y2={y(lastClose)} stroke="#a7751e" strokeDasharray="4 4" opacity=".6" /><rect x={RIGHT + 3} y={y(lastClose) - 10} width="84" height="20" rx="2" fill="#a7751e" /><text x={RIGHT + 9} y={y(lastClose) + 4} className="chart-current-price">{price(lastClose)}</text></g>}
        <line x1={LEFT} x2={W - 12} y1={277} y2={277} className="chart-grid" /><text x={LEFT + 3} y={295} className="chart-indicator-title">MACD</text><text x={LEFT + 3} y={309} className="chart-axis chart-translation">指数平滑异同移动平均线</text>
        <line x1={LEFT} x2={RIGHT} y1={mid} y2={mid} className="chart-grid" /><text x={RIGHT + 12} y={mid + 4} className="chart-axis">0.00</text>
        {indicators.map((indicator, index) => indicator?.histogram == null ? null : <rect key={index} x={x(index) - step * 0.28} y={Math.min(mid, iy(indicator.histogram))} width={Math.max(1, step * 0.56)} height={Math.max(0.5, Math.abs(mid - iy(indicator.histogram)))} fill={indicator.histogram >= 0 ? '#168466' : '#c6475b'} opacity=".58" />)}
        <path d={indicatorLine('macd')} fill="none" stroke="#a7751e" strokeWidth="1.5" /><path d={indicatorLine('signal')} fill="none" stroke="#6878ba" strokeWidth="1.5" />
        {[0, 1, 2, 3, 4, 5].map(index => { const candleIndex = Math.floor(index / 5 * (candles.length - 1)); return <text key={index} x={x(candleIndex)} y={407} textAnchor={index === 0 ? 'start' : index === 5 ? 'end' : 'middle'} className="chart-axis">{new Date(candles[candleIndex].time).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', hour12: false })}</text>; })}
        {hover !== null && <line x1={x(hover)} x2={x(hover)} y1={TOP} y2={IND_BOTTOM} stroke="#8796a6" strokeDasharray="3 4" opacity=".6" />}
      </svg></div>
      <div className="chart-footer"><span><i className="legend-line gold-line" />快线<i className="legend-line purple-line" />信号线<span className="histogram-legend" />柱状差值</span><span>{market?.source === 'demo' && '演示数据 · '}更新于 {clockTime(market?.updated_at)}</span></div>
    </>}
  </section>;
}
