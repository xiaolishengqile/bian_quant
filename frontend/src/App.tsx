import { useEffect, useState } from 'react';
import { ArrowDownUp, ChartNoAxesCombined, Check, CircleHelp, FlaskConical, LayoutDashboard, LoaderCircle, LogOut, Pause, Play, RefreshCw, Settings2, Shield, SlidersHorizontal, TriangleAlert } from 'lucide-react';
import { clockTime, modeLabels, number, stateLabels } from './format';
import { useConsole } from './hooks/useConsole';
import { Badge, Loading, Logo, Modal, Unit } from './components/UI';
import Login from './components/Login';
import Dashboard from './pages/Dashboard';
import StrategyPage from './pages/StrategyPage';
import TradesPage from './pages/TradesPage';
import BacktestPage from './pages/BacktestPage';
import SettingsPage from './pages/SettingsPage';
import type { Page } from './types';

const navigation = [
  { id: 'overview', label: '总览', title: '交易总览', icon: LayoutDashboard },
  { id: 'strategy', label: '策略', title: '策略配置', icon: SlidersHorizontal },
  { id: 'trades', label: '成交', title: '成交记录', icon: ArrowDownUp },
  { id: 'backtest', label: '回测', title: '历史回测', icon: FlaskConical },
  { id: 'settings', label: '设置', title: '连接设置', icon: Settings2 },
] as const;
const descriptions: Record<Page, string> = { overview: '每一次决策，都有据可循。', strategy: '定义交易规则，让执行保持一致。', trades: '从信号到成交，保留完整记录。', backtest: '用历史数据，理解策略的表现。', settings: '检查服务连接，管理运行环境。' };

export default function App() {
  const console = useConsole();
  const { state, auth, busy, error } = console;
  const [page, setPage] = useState<Page>(() => navigation.find(item => item.id === window.location.hash.slice(1))?.id ?? 'overview');
  const [confirm, setConfirm] = useState<'flatten' | 'start' | null>(null);
  const [help, setHelp] = useState(false);
  useEffect(() => { window.location.hash = page; document.title = `${navigation.find(item => item.id === page)?.title} · 衡量`; }, [page]);
  useEffect(() => {
    const change = () => { const match = navigation.find(item => item.id === window.location.hash.slice(1)); if (match) setPage(match.id); };
    window.addEventListener('hashchange', change); return () => window.removeEventListener('hashchange', change);
  }, []);
  if (!auth) return <main className="boot-screen"><Logo /><h1>衡量 · 量化工作台</h1>{error ? <><p className="negative" role="alert">{error}</p><button className="button secondary" onClick={() => void console.checkAuth()}><RefreshCw size={15} />重新连接</button></> : <Loading text="正在连接控制台" />}</main>;
  if (auth.required && !auth.authenticated) return <Login login={console.login} busy={busy === 'login'} error={error} />;
  const running = state?.status.state === 'running';
  const actionDisabled = !!busy || !state || !!error;
  return <div className="app-shell">
    <aside className="sidebar"><a className="sidebar-logo" href="#overview" aria-label="衡量工作台首页" onClick={() => setPage('overview')}><Logo /></a><div className="sidebar-divider" />
      <nav aria-label="工作台导航">{navigation.map(({ id, label, icon: Icon }) => <button key={id} className={`nav-item ${page === id ? 'active' : ''}`} aria-current={page === id ? 'page' : undefined} onClick={() => setPage(id)}><Icon size={20} strokeWidth={1.6} /><span>{label}</span></button>)}</nav>
      <div className="sidebar-bottom"><button className="nav-item" onClick={() => setHelp(true)} aria-label="运行说明"><CircleHelp size={20} /><span>说明</span></button><span className="sidebar-version">1.0</span></div>
    </aside>
    <div className="workspace">
      <header className="topbar"><div className="wordmark">衡量<span className="topbar-separator" /><span>量化工作台</span><Badge>个人版</Badge></div><div className="topbar-right"><span className="server-status"><span className={`status-dot ${error ? 'bad-dot' : ''}`} />{error ? '连接异常' : '服务已连接'}</span><span className="topbar-separator" /><button className="icon-button" title="刷新工作台" aria-label="刷新工作台" disabled={console.refreshing || !!busy} onClick={() => void console.refresh()}><RefreshCw size={16} className={console.refreshing ? 'spin' : ''} /></button>{auth.required && <button className="icon-button" aria-label="退出登录" disabled={!!busy} onClick={() => void console.logout()}><LogOut size={16} /></button>}<div className="avatar" aria-label="个人账户">量</div></div></header>
      <main className="main-content">
        <div className="page-intro"><div><div className="eyebrow"><span />个人交易终端</div><h1>{navigation.find(item => item.id === page)?.title}</h1><p>{descriptions[page]}</p></div><div className="intro-actions">{state && <><Badge tone={state.config.mode === 'live' ? 'danger' : 'gold'}>{modeLabels[state.config.mode]}</Badge><Badge dot tone={running ? 'success' : state.status.state === 'stopped' ? 'neutral' : 'danger'}>{stateLabels[state.status.state]}</Badge><button className={`button ${running ? 'secondary' : 'primary'}`} disabled={actionDisabled} onClick={() => running ? void console.stop() : state.config.mode === 'live' ? setConfirm('start') : void console.start()}>{busy === 'start' || busy === 'stop' ? <LoaderCircle size={15} className="spin" /> : running ? <Pause size={15} fill="currentColor" /> : <Play size={15} fill="currentColor" />}{running ? '停止策略' : '启动策略'}</button></>}</div></div>
        {error && <div className="alert error" role="alert"><TriangleAlert size={17} /><span>{error}{state && <small>当前显示上次成功同步的数据，请恢复连接后再操作。</small>}</span><button className="text-button" disabled={console.refreshing} onClick={() => void console.refresh()}>重试</button></div>}
        {console.notice && <div className="alert success-alert" role="status"><Check size={17} />{console.notice}</div>}
        {!state ? <div className="panel initial-loading"><Loading text={error ? '等待服务恢复' : '正在加载账户与策略'} /></div> : <>
          {state.status.last_error && <div className="alert error"><Shield size={17} /><span>策略提示：{state.status.last_error}</span></div>}
          {page === 'overview' && <Dashboard state={state} symbols={console.symbols} onConfigure={() => setPage('strategy')} onTrades={() => setPage('trades')} onFlatten={() => setConfirm('flatten')} busy={actionDisabled} />}
          {page === 'strategy' && <StrategyPage state={state} symbols={console.symbols} saveConfig={console.saveConfig} busy={!!busy || !!error} />}
          {page === 'trades' && <TradesPage state={state} />}
          {page === 'backtest' && <BacktestPage state={state} symbols={console.symbols} />}
          {page === 'settings' && <SettingsPage state={state} authRequired={auth.required} resetPaper={console.resetPaper} saveCredentials={console.saveCredentials} removeCredentials={console.removeCredentials} busy={!!busy} error={error} />}
        </>}
      </main>
      <footer className="workspace-footer"><span><ChartNoAxesCombined size={13} />{state?.config.market_source === 'demo' ? '演示行情 · 非真实市场价格' : '币安行情 · 以交易所返回为准'}</span><span>最近同步 {clockTime(console.lastSync)}<span className="footer-divider">/</span>账户金额以泰达币计价</span></footer>
    </div>
    {confirm === 'flatten' && state && <Modal title="确认全部平仓" danger confirmLabel="确认全部平仓" busy={busy === 'flatten'} error={error} onClose={() => setConfirm(null)} onConfirm={async () => { if (await console.flatten()) setConfirm(null); }}><div className="confirm-icon"><TriangleAlert size={25} /></div><p>将对当前 <strong>{modeLabels[state.config.mode]}</strong> 中的 <strong>{state.positions.length}</strong> 个策略持仓执行平仓。</p><p className="muted">浮动盈亏 <strong>{number(state.summary.unrealized_pnl)}</strong> 泰达币。最终结果以实际成交为准；此操作会产生适用的费用。</p><div className="note-box">本次操作会先停止策略，再平掉全部策略持仓。完成后需要手动重新启动策略。</div></Modal>}
    {confirm === 'start' && state && <Modal title="启动真实资金交易" danger confirmLabel="确认启动实盘" busy={busy === 'start'} error={error} onClose={() => setConfirm(null)} onConfirm={async () => { if (await console.start()) setConfirm(null); }}><p>策略将在币安真实账户下单，请核对当前配置：</p><dl className="definition-list"><div><dt>交易对</dt><dd>{state.config.symbols.map(s => s.replace('USDT', '')).join('、')}<small>所选币种 · 泰达币永续</small></dd></div><div><dt>单笔保证金 / 杠杆</dt><dd>{number(state.config.order_margin)} 泰达币 / {state.config.leverage} 倍</dd></div><div><dt>每日净亏损上限</dt><dd>{number(state.config.daily_loss_limit)} 泰达币</dd></div></dl><p className="negative">此模式会操作真实资金，演示及回测表现不代表未来结果。</p></Modal>}
    {help && <Modal title="运行说明" onClose={() => setHelp(false)} onConfirm={() => setHelp(false)} confirmLabel="我已了解" hideCancel><p>策略根据已收盘蜡烛的指标交叉判断方向，启动时不会追逐历史信号。</p><p>停止策略会禁止新开仓，已有持仓仍监控止盈止损；全部平仓会先停止策略，再平掉全部策略持仓。</p><p>演示行情仅供体验。服务器持续执行策略，关闭浏览器不会停止运行；后台进程重启后默认停止新开仓，已有持仓继续监控风险。</p><div className="help-unit"><Unit /><span>所有账户金额与收益均以泰达币计价。</span></div></Modal>}
  </div>;
}
