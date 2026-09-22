import { useEffect, useState } from 'react';
import { Check, Info, LockKeyhole, Save, Search, ShieldCheck, SlidersHorizontal } from 'lucide-react';
import { validateConfig } from '../config-validation';
import { Badge, PanelHeading } from '../components/UI';
import { intervals, modeLabels, number, symbolName } from '../format';
import type { ConsoleState, Interval, Mode, StrategyConfig, SymbolResponse } from '../types';

type NumericField = Exclude<{ [K in keyof StrategyConfig]: StrategyConfig[K] extends number ? K : never }[keyof StrategyConfig], undefined>;
const modeDescriptions = { paper: '虚拟资金，验证交易流程', testnet: '测试环境，验证交易所下单', live: '真实账户，使用真实资金' };

export default function StrategyPage({ state, symbols, saveConfig, busy }: {
  state: ConsoleState; symbols: SymbolResponse | null; saveConfig: (config: StrategyConfig) => Promise<boolean>; busy: boolean;
}) {
  const saved = JSON.stringify(state.config);
  const [form, setForm] = useState<StrategyConfig>(state.config);
  const [filter, setFilter] = useState('');
  const [validation, setValidation] = useState('');
  useEffect(() => { setForm(JSON.parse(saved)); setValidation(''); }, [saved]);
  const locked = state.status.state === 'running' || busy || state.positions.length > 0;
  const dirty = JSON.stringify(form) !== saved;
  const hasPositions = state.positions.length > 0;
  const change = <K extends keyof StrategyConfig>(key: K, value: StrategyConfig[K]) => setForm(previous => ({ ...previous, [key]: value }));
  const available = [...new Set([...form.symbols, ...(symbols?.symbols.map(item => item.symbol) ?? [])])];
  const filtered = available.filter(symbol => `${symbol} ${symbolName(symbol)}`.toLowerCase().includes(filter.toLowerCase())).slice(0, 24);
  const numeric = (key: NumericField, label: string, min: number, max: number, step = 1, hint?: string) => <label className="field" key={key}>{label}<input type="number" required min={min} max={max} step={step} value={Number.isFinite(form[key]) ? form[key] : ''} onChange={event => change(key, event.target.value === '' ? Number.NaN : Number(event.target.value))} />{hint && <small>{hint}</small>}</label>;
  function toggleSymbol(symbol: string) {
    setValidation('');
    if (form.symbols.includes(symbol)) change('symbols', form.symbols.filter(item => item !== symbol));
    else if (form.symbols.length < 8) change('symbols', [...form.symbols, symbol]);
    else setValidation('最多同时监测 8 个交易币种。');
  }
  return <form className="configuration-layout" onSubmit={async event => { event.preventDefault(); const problem = validateConfig(form); setValidation(problem ?? ''); if (!problem) await saveConfig(form); }}>
    <fieldset className="configuration-fields" disabled={locked}>
      {(state.status.state === 'running' || hasPositions) && <div className="alert"><LockKeyhole size={16} />{hasPositions ? '存在持仓，请先停止策略并平仓后再编辑配置。' : '策略运行中，停止策略后可编辑参数。'}</div>}
      <section className="panel form-section"><PanelHeading title="交易环境" extra={<span className="section-number">01</span>} /><div className="form-section-content"><label className="field-label">交易模式</label><div className="mode-options">{(['paper', 'testnet', 'live'] as Mode[]).map(mode => <label key={mode} className={`mode-option ${form.mode === mode ? 'selected' : ''} ${hasPositions && form.mode !== mode ? 'is-disabled' : ''}`}><input type="radio" name="trading-mode" checked={form.mode === mode} disabled={hasPositions && form.mode !== mode} onChange={() => setForm(previous => ({ ...previous, mode, market_source: mode === 'paper' ? previous.market_source : 'binance' }))} /><span><strong>{modeLabels[mode]}</strong><small>{modeDescriptions[mode]}</small></span>{form.mode === mode && <Check size={15} />}</label>)}</div>{hasPositions && <p className="field-help">存在持仓时不能切换交易模式，请先平仓。</p>}
        <div className="form-grid"><label className="field">行情来源<select value={form.market_source} disabled={form.mode !== 'paper'} onChange={event => change('market_source', event.target.value as 'demo' | 'binance')}><option value="demo">演示行情 · 仅供体验</option><option value="binance">币安真实行情</option></select><small>{form.mode === 'paper' ? '切换行情来源后，先保存配置，再选择该环境下的其他币种。' : '测试网和实盘固定使用币安行情。'}</small></label><label className="field">信号周期<select value={form.interval} onChange={event => change('interval', event.target.value as Interval)}>{intervals.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}</select><small>只使用已收盘蜡烛判断交易信号。</small></label></div>
        <div className="field-heading"><span>交易币种 <span className="muted">{form.symbols.length} / 8</span></span><label className="search-field"><Search size={14} /><span className="sr-only">搜索交易币种</span><input type="search" value={filter} onChange={event => setFilter(event.target.value)} placeholder="搜索币种" /></label></div>
        <div className="symbol-options">{filtered.map(symbol => <label className={`symbol-option ${form.symbols.includes(symbol) ? 'selected' : ''}`} key={symbol}><input type="checkbox" checked={form.symbols.includes(symbol)} onChange={() => toggleSymbol(symbol)} /><span><strong>{symbol.replace('USDT', '')}<span className="muted"> / USDT</span></strong><small>{symbolName(symbol)}</small></span>{form.symbols.includes(symbol) && <Check size={13} />}</label>)}</div>{!filtered.length && <p className="field-help">没有匹配的可用合约。</p>}{symbols?.error && <p className="field-help negative">{symbols.error}</p>}<p className="field-help">已选 {form.symbols.length} 个合约。币种列表来源：{symbols?.source === 'demo' ? '演示环境' : symbols ? '币安' : '当前策略配置'}。</p>
      </div></section>
      <section className="panel form-section"><PanelHeading title="信号与执行" extra={<span className="section-number">02</span>} /><div className="form-section-content"><div className="indicator-caption"><SlidersHorizontal size={18} /><div><strong>MACD</strong><small>指数平滑异同移动平均线</small></div><Badge>双向趋势跟随</Badge></div><div className="form-grid three-columns">{numeric('macd_fast', '快线周期', 2, 50)}{numeric('macd_slow', '慢线周期', 3, 100)}{numeric('macd_signal', '信号线周期', 2, 50)}</div><label className="switch-field"><span><strong>反向信号后反手开仓</strong><small>先确认原持仓平仓，再按新方向开仓；关闭后反向信号仅平仓。</small></span><input type="checkbox" role="switch" checked={form.reverse_on_signal} onChange={event => change('reverse_on_signal', event.target.checked)} /><span className="switch-track" aria-hidden="true" /></label><div className="form-grid">{numeric('leverage', '杠杆倍数', 1, 20, 1, '实际可用倍数还受交易所限制。')}<label className="field">保证金方式<select value={form.margin_mode} onChange={event => change('margin_mode', event.target.value as 'isolated' | 'cross')}><option value="isolated">逐仓</option><option value="cross">全仓</option></select><small>仅支持单向持仓，不自动更改全局持仓模式。</small></label></div></div></section>
      <section className="panel form-section"><PanelHeading title="资金与风险限制" extra={<span className="section-number">03</span>} /><div className="form-section-content"><div className="form-grid">{numeric('initial_balance', '策略资金（泰达币）', 100, 10000000, 1)}{numeric('order_margin', '单笔保证金（泰达币）', 5, 1000000, 1, '单笔金额指保证金，不是杠杆后的名义金额。')}{numeric('max_position_margin', '总保证金上限（泰达币）', 5, 10000000, 1)}{numeric('daily_loss_limit', '每日净亏损上限（泰达币）', 0.01, 10000000, 0.01, '按协调世界时的自然日计算。')}{numeric('stop_loss_pct', '价格止损幅度（%）', 0.01, 50, 0.01)}{numeric('take_profit_pct', '价格止盈幅度（%）', 0.01, 100, 0.01)}</div><div className="note-box"><Info size={15} /><span>止盈止损是标的价格变化幅度，并非杠杆收益率。单笔名义金额为保证金乘以杠杆；交易模式与行情来源分别保存账户资金和历史。</span></div></div></section>
      <section className="panel form-section"><PanelHeading title="模拟与回测成本" extra={<span className="section-number">04</span>} /><div className="form-section-content"><div className="form-grid">{numeric('fee_bps', '单边手续费（基点）', 0, 100, 0.1, '1 基点 = 0.01%；实盘费用以成交返回为准。')}{numeric('slippage_bps', '单边滑点（基点）', 0, 100, 0.1, '模拟成交价格向不利方向调整。')}</div></div></section>
    </fieldset>
    <aside className="configuration-aside"><section className="panel save-panel"><PanelHeading title="配置摘要" extra={<ShieldCheck size={16} />} /><div className="save-content"><Badge tone={form.mode === 'live' ? 'danger' : 'gold'}>{modeLabels[form.mode]}</Badge><dl className="definition-list"><div><dt>监测合约</dt><dd>{form.symbols.length} 个</dd></div><div><dt>信号周期</dt><dd>{intervals.find(item => item.value === form.interval)?.label}</dd></div><div><dt>单笔名义金额</dt><dd>{number(form.order_margin * form.leverage, 0)}<small>泰达币</small></dd></div><div><dt>保证金上限</dt><dd>{number(form.max_position_margin, 0)}<small>泰达币</small></dd></div></dl><div className="save-state"><span className={`status-dot ${dirty ? 'gold-dot' : ''}`} />{dirty ? '有尚未保存的修改' : '已与服务器配置同步'}</div>{validation && <p className="inline-error" role="alert">{validation}</p>}<button type="submit" className="button primary" disabled={locked || !dirty}><Save size={15} />{busy ? '正在保存' : '保存策略配置'}</button><button type="button" className="button secondary" disabled={locked || !dirty} onClick={() => { setForm(state.config); setValidation(''); }}>恢复已保存配置</button><p className="field-help">保存后不会自动启动策略。请返回总览核对后启动。</p></div></section><div className="aside-note"><ShieldCheck size={17} /><p>参数校验同时在服务器执行，实际下单还会检查连接、余额、持仓和交易所规则。</p></div></aside>
  </form>;
}
