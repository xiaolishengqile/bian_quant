import { useState } from 'react';
import { ArrowRight, ArrowUpRight, CircleDot, Layers, ShieldCheck, SlidersHorizontal, Square, Wallet } from 'lucide-react';
import MarketChart from '../components/MarketChart';
import { LogsList, PositionsTable } from '../components/DataTables';
import { Badge, Metric, PanelHeading, Pnl, Unit } from '../components/UI';
import { intervals, number, stateLabels } from '../format';
import type { ConsoleState, Interval, SymbolResponse } from '../types';

export default function Dashboard({ state, symbols, onConfigure, onTrades, onFlatten, busy }: {
  state: ConsoleState; symbols: SymbolResponse | null; onConfigure: () => void; onTrades: () => void; onFlatten: () => void; busy: boolean;
}) {
  const { config, summary } = state;
  const [symbol, setSymbol] = useState(config.symbols[0]);
  const [interval, setInterval] = useState<Interval>(config.interval);
  const [tab, setTab] = useState<'positions' | 'logs'>('positions');
  const available = [...new Set([...config.symbols, ...(symbols?.symbols.map(item => item.symbol) ?? [])])].map(value => ({ symbol: value, base_asset: value.replace('USDT', ''), quote_asset: 'USDT' }));
  const margin = state.positions.reduce((sum, position) => sum + position.margin, 0);
  const marginPct = Math.min(100, margin / config.max_position_margin * 100);
  const lossPct = Math.min(100, Math.abs(Math.min(0, summary.daily_pnl)) / config.daily_loss_limit * 100);
  const running = state.status.state === 'running';
  const synced = config.mode === 'paper' || summary.account_synced === true;
  return <>
    <section className="account-strip panel" aria-label="账户统计"><Metric accent label={<span className="account-metric-label"><Wallet size={15} />账户权益<Unit /></span>} value={synced ? summary.equity : '—'}><span>{synced ? <>钱包余额 <strong className="numeric">{number(summary.wallet_balance)}</strong></> : '账户尚未与交易所同步'}</span></Metric><Metric label="当日净盈亏" value={synced ? <Pnl value={summary.daily_pnl} /> : '—'}><span>{synced ? <>已实现 <Pnl value={summary.realized_pnl} /></> : '启动校验成功后同步'}</span></Metric><Metric label="占用保证金" value={synced ? margin : '—'}><span>{state.positions.length} 个持仓<span className="metric-note-dot">·</span>上限 {number(config.max_position_margin, 0)}</span></Metric><Metric label="已完成交易" value={<>{summary.total_trades}<small>笔</small></>}><button className="text-button" onClick={onTrades}>查看成交记录<ArrowUpRight size={12} /></button></Metric></section>
    <div className="overview-grid"><MarketChart symbol={symbol} setSymbol={setSymbol} interval={interval} setInterval={setInterval} symbols={available} sourceKey={`${config.mode}:${config.market_source}`} />
      <aside className="strategy-summary panel"><PanelHeading title="策略概览" extra={<button className="icon-button" onClick={onConfigure} aria-label="编辑策略配置"><SlidersHorizontal size={16} /></button>} />
        <div className="strategy-identity"><span className="strategy-glyph"><Layers size={22} strokeWidth={1.5} /></span><div><h3>双向趋势跟随</h3><span className="strategy-code">MACD<small>指数平滑异同移动平均线</small></span></div></div>
        <div className={`strategy-live-state ${running ? 'is-running' : ''}`}><span className="status-dot" /><div><strong>{running ? '策略正在监测市场' : state.status.state === 'stopped' ? '策略等待启动' : stateLabels[state.status.state]}</strong><small>{running ? '等待新的收盘交叉信号' : '参数已就绪，启动后监测新信号'}</small></div><CircleDot size={18} /></div>
        <dl className="strategy-facts"><div><dt>交易方向</dt><dd>双向 · 多 / 空</dd></div><div><dt>信号周期</dt><dd>{intervals.find(item => item.value === config.interval)?.label}</dd></div><div><dt>杠杆 / 保证金</dt><dd>{config.leverage} 倍<span className="muted"> / </span>{config.margin_mode === 'isolated' ? '逐仓' : '全仓'}</dd></div><div><dt>指标参数</dt><dd className="numeric">{config.macd_fast}<span> / </span>{config.macd_slow}<span> / </span>{config.macd_signal}</dd></div></dl>
        <div className="strategy-assets"><span>监测合约</span><div>{config.symbols.map(item => <span key={item}>{item.replace('USDT', '')}<small>{item === 'BTCUSDT' ? '比特币' : item === 'ETHUSDT' ? '以太坊' : '永续合约'}</small></span>)}</div></div>
        <button className="strategy-configure" onClick={onConfigure}>管理策略配置<ArrowRight size={14} /></button>
        <div className="risk-section"><h3><ShieldCheck size={15} />风险控制<Badge tone="success">已配置</Badge></h3><div className="risk-item"><div><span>保证金使用</span><strong className="numeric">{number(marginPct, 1)}<small>%</small></strong></div><div className="progress-track"><span style={{ width: `${marginPct}%` }} /></div><small>{number(margin, 0)} / {number(config.max_position_margin, 0)} 泰达币</small></div><div className="risk-item"><div><span>每日亏损额度</span><strong className="numeric">{number(lossPct, 1)}<small>%</small></strong></div><div className="progress-track loss"><span style={{ width: `${lossPct}%` }} /></div><small>上限 {number(config.daily_loss_limit, 0)} 泰达币</small></div><div className="risk-thresholds"><span>止损 <strong>{config.stop_loss_pct}%</strong></span><span>止盈 <strong>{config.take_profit_pct}%</strong></span></div></div>
      </aside>
    </div>
    <section className="panel holdings-panel"><div className="holdings-heading"><div className="panel-tabs" role="tablist" aria-label="持仓与日志"><button role="tab" aria-selected={tab === 'positions'} onClick={() => setTab('positions')}>当前持仓<span>{state.positions.length}</span></button><button role="tab" aria-selected={tab === 'logs'} onClick={() => setTab('logs')}>运行日志<span>{state.logs.length}</span></button></div><div className="holdings-actions"><span>浮动盈亏 <Pnl value={summary.unrealized_pnl} /></span><button className="button danger-outline small-button" disabled={busy || !state.positions.length} onClick={onFlatten}><Square size={11} />全部平仓</button></div></div><div role="tabpanel">{tab === 'positions' ? <PositionsTable positions={state.positions} /> : <LogsList logs={state.logs.slice(0, 30)} />}</div><div className="holdings-footer"><span><ShieldCheck size={12} />停止策略后，已有持仓仍监控止盈止损。</span><button className="text-button" onClick={onTrades}>全部成交<ArrowRight size={12} /></button></div></section>
  </>;
}
