import { useState } from 'react';
import { ArrowRight, FlaskConical, History, Info, LoaderCircle } from 'lucide-react';
import { messageOf, request } from '../api';
import { Badge, Coin, Metric, PanelHeading, Pnl } from '../components/UI';
import EquityChart from '../components/EquityChart';
import { dateTime, intervals, number } from '../format';
import type { BacktestResult, ConsoleState, Interval, StrategyConfig, SymbolResponse } from '../types';

export default function BacktestPage({ state, symbols }: { state: ConsoleState; symbols: SymbolResponse | null }) {
  const [symbol, setSymbol] = useState(state.config.symbols[0]);
  const [interval, setInterval] = useState<Interval>(state.config.interval);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [usedConfig, setUsedConfig] = useState<StrategyConfig | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const available = [...new Set([...state.config.symbols, ...(symbols?.symbols.map(item => item.symbol) ?? [])])];
  async function backtest() {
    setBusy(true); setError('');
    const config = { ...state.config, interval };
    try { const next = await request<BacktestResult>('/backtest', { method: 'POST', body: JSON.stringify({ symbol, interval }) }); setResult(next); setUsedConfig(config); }
    catch (err) { setError(messageOf(err)); }
    finally { setBusy(false); }
  }
  return <div className="backtest-layout"><section className="panel backtest-controls"><PanelHeading title="回测参数" extra={<FlaskConical size={16} />} /><form onSubmit={event => { event.preventDefault(); void backtest(); }}><label className="field">回测合约<select value={symbol} disabled={busy} onChange={event => setSymbol(event.target.value)}>{available.map(item => <option key={item} value={item}>{item}</option>)}</select><small>泰达币计价永续合约</small></label><label className="field">蜡烛周期<select value={interval} disabled={busy} onChange={event => setInterval(event.target.value as Interval)}>{intervals.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label><dl className="definition-list"><div><dt>行情来源</dt><dd>{state.config.market_source === 'demo' ? '演示行情' : '币安行情'}</dd></div><div><dt>样本长度</dt><dd>最近最多 1,000 根</dd></div><div><dt>初始资金</dt><dd>{number(state.config.initial_balance, 0)}<small>泰达币</small></dd></div><div><dt>指标周期</dt><dd>{state.config.macd_fast} / {state.config.macd_slow} / {state.config.macd_signal}</dd></div><div><dt>杠杆</dt><dd>{state.config.leverage} 倍</dd></div><div><dt>手续费 / 滑点</dt><dd>{state.config.fee_bps} / {state.config.slippage_bps} 基点</dd></div></dl><p className="field-help">使用服务器当前已保存策略，未保存的编辑不会用于回测。</p><button className="button primary" type="submit" disabled={busy}>{busy ? <LoaderCircle size={15} className="spin" /> : <FlaskConical size={15} />}{busy ? '正在运行回测' : '运行历史回测'}{!busy && <ArrowRight size={14} />}</button></form><div className="backtest-note"><Info size={15} /><p>回测只分析历史表现，不会创建持仓或提交交易订单。</p></div></section>
    <div className="backtest-results">{error && <div className="alert error" role="alert">{error}{result && ' 下方保留上一次成功回测结果。'}</div>}{!result ? <section className="panel backtest-empty"><div className="backtest-illustration"><span /><History size={43} strokeWidth={1.1} /></div><Badge tone="gold">从数据开始</Badge><h2>先验证，再执行</h2><p>选择一个交易合约，使用已保存的策略运行回测。<br />资金曲线、收益表现与交易成本将在这里呈现。</p><div className="backtest-empty-facts"><span>已收盘信号</span><i /><span>下一根开盘成交</span><i /><span>计入手续费与滑点</span></div></section> : <>
      <div className="backtest-result-heading"><div><Coin symbol={result.symbol} /><p>{dateTime(result.start_time)} — {dateTime(result.end_time)}<span> · {result.bars} 根蜡烛</span></p></div><Badge tone={usedConfig?.market_source === 'demo' ? 'gold' : 'neutral'}>{usedConfig?.market_source === 'demo' ? '演示数据回测' : '币安数据回测'}</Badge></div>
      <section className="account-strip panel backtest-metrics"><Metric label="累计收益率" value={<Pnl value={result.return_pct} percent />}>期末权益 {number(result.final_equity)}</Metric><Metric label="最大回撤" value={<span className="negative">{number(result.max_drawdown_pct)}%</span>}>历史峰值至低点</Metric><Metric label="平仓交易" value={<>{result.total_trades}<small>笔</small></>}>胜率 {number(result.win_rate, 1)}%</Metric><Metric label="累计手续费" value={result.fees}>泰达币</Metric></section>
      <section className="panel"><PanelHeading title="账户权益曲线" extra={<span className="muted">单位：泰达币</span>} /><EquityChart points={result.equity_curve} initial={result.initial_balance} /><div className="chart-footer"><span><i className="legend-line gold-line" />账户权益</span><span>虚线为初始资金</span></div></section>
      <section className="panel assumptions-panel"><PanelHeading title="回测口径与限制" extra={<Info size={16} />} /><ul>{(result.assumptions.length ? result.assumptions : ['使用上一根收盘信号，于下一根开盘价成交。', '已考虑手续费与滑点，未完整模拟强平及资金费率。']).map((assumption, index) => <li key={index}>{assumption}</li>)}</ul><p>历史表现不代表未来收益。演示行情的回测只用于检查流程。</p></section>
    </>}</div></div>;
}
