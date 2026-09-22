import { useMemo, useState } from 'react';
import { Download, Search } from 'lucide-react';
import { LogsList, OrdersTable } from '../components/DataTables';
import { Metric, PanelHeading, Pnl } from '../components/UI';
import { csvCell, dateTime, modeLabels, number } from '../format';
import type { ConsoleState } from '../types';

export default function TradesPage({ state }: { state: ConsoleState }) {
  const synced = state.config.mode === 'paper' || state.summary.account_synced === true;
  const [filter, setFilter] = useState('');
  const [action, setAction] = useState('all');
  const [page, setPage] = useState(0);
  const [tab, setTab] = useState<'orders' | 'logs'>('orders');
  const filtered = useMemo(() => state.orders.filter(order => `${order.symbol} ${order.reason}`.toLowerCase().includes(filter.toLowerCase()) && (action === 'all' || order.action === action)), [state.orders, filter, action]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / 15));
  const safePage = Math.min(page, totalPages - 1);
  function download() {
    const rows = [['成交时间', '交易合约', '模式', '动作', '方向', '数量', '价格', '手续费', '已实现盈亏', '原因'], ...filtered.map(order => [dateTime(order.timestamp), order.symbol, modeLabels[order.mode], order.action === 'open' ? '开仓' : '平仓', order.side === 'long' ? '多' : '空', order.quantity, order.price, order.fee, order.realized_pnl, order.reason])];
    const text = '\uFEFF' + rows.map(row => row.map(csvCell).join(',')).join('\r\n');
    const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8;' }));
    const link = document.createElement('a'); link.href = url; link.download = `衡量成交记录-${new Date().toISOString().slice(0, 10)}.csv`; link.click(); URL.revokeObjectURL(url);
  }
  return <><section className="account-strip panel"><Metric label="已完成交易" value={<>{state.summary.total_trades}<small>笔</small></>}>当前策略账户</Metric><Metric label="已实现盈亏" value={synced ? <Pnl value={state.summary.realized_pnl} /> : '—'}>泰达币</Metric><Metric label="累计手续费" value={synced ? state.summary.fees : '—'}>泰达币</Metric><Metric label="平仓胜率" value={`${number(state.summary.win_rate, 1)}%`}>以已平仓交易计算</Metric></section><section className="panel"><div className="holdings-heading"><div className="panel-tabs" role="tablist"><button role="tab" aria-selected={tab === 'orders'} onClick={() => setTab('orders')}>最近成交<span>{state.orders.length}</span></button><button role="tab" aria-selected={tab === 'logs'} onClick={() => setTab('logs')}>运行日志<span>{state.logs.length}</span></button></div><button className="button secondary small-button" disabled={!filtered.length || tab !== 'orders'} onClick={download}><Download size={14} />导出筛选记录</button></div>{tab === 'orders' ? <><div className="table-filters"><label className="search-field"><Search size={15} /><span className="sr-only">搜索成交合约或原因</span><input type="search" placeholder="搜索合约或成交原因" value={filter} onChange={event => { setFilter(event.target.value); setPage(0); }} /></label><label className="filter-select">成交类型<select value={action} onChange={event => { setAction(event.target.value); setPage(0); }}><option value="all">全部类型</option><option value="open">开仓成交</option><option value="close">平仓成交</option></select></label><span className="muted">最近最多 200 条 · 导出当前筛选结果 · 单位：泰达币</span></div><OrdersTable orders={filtered.slice(safePage * 15, (safePage + 1) * 15)} /><div className="table-pagination"><span>共 {filtered.length} 条符合条件的记录</span><div><button className="button secondary small-button" disabled={safePage === 0} onClick={() => setPage(value => Math.max(0, value - 1))}>上一页</button><span>{safePage + 1} / {totalPages}</span><button className="button secondary small-button" disabled={safePage + 1 >= totalPages} onClick={() => setPage(value => value + 1)}>下一页</button></div></div></> : <div role="tabpanel"><PanelHeading title="最近运行事件" extra={<span className="muted">由服务器持续记录</span>} /><LogsList logs={state.logs} /></div>}</section></>;
}
