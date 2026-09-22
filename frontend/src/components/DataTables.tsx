import { AlertCircle, Circle, Info } from 'lucide-react';
import { dateTime, modeLabels, number, price } from '../format';
import type { Log, Order, Position } from '../types';
import { Badge, Coin, Empty, Pnl } from './UI';

export function PositionsTable({ positions }: { positions: Position[] }) {
  if (!positions.length) return <Empty title="当前暂无持仓">策略启动后，将在新的有效信号出现时开仓。</Empty>;
  return <div className="table-scroll"><table><thead><tr><th>交易合约</th><th>方向 / 杠杆</th><th>持仓数量</th><th>开仓均价</th><th>最新价格</th><th>占用保证金</th><th>浮动盈亏</th><th>止损 / 止盈</th></tr></thead><tbody>{positions.map(position => <tr key={position.symbol}><td><Coin symbol={position.symbol} compact /></td><td><Badge tone={position.side === 'long' ? 'success' : 'danger'}>{position.side === 'long' ? '做多' : '做空'} · {position.leverage} 倍</Badge></td><td className="numeric">{number(position.quantity, 5)}</td><td className="numeric">{price(position.entry_price)}</td><td className="numeric">{price(position.mark_price)}</td><td className="numeric">{number(position.margin)}</td><td><Pnl value={position.unrealized_pnl} /></td><td className="numeric table-dual"><span>{price(position.stop_loss)}</span><small>{price(position.take_profit)}</small></td></tr>)}</tbody></table></div>;
}
export function OrdersTable({ orders }: { orders: Order[] }) {
  if (!orders.length) return <Empty title="还没有成交记录">每一笔真实返回的成交都会显示在这里。</Empty>;
  return <div className="table-scroll"><table><thead><tr><th>成交时间</th><th>交易合约</th><th>动作</th><th>成交数量</th><th>成交均价</th><th>手续费</th><th>已实现盈亏</th><th>触发原因</th><th>模式</th><th>状态</th></tr></thead><tbody>{orders.map(order => <tr key={order.id}><td className="numeric">{dateTime(order.timestamp)}</td><td><Coin symbol={order.symbol} compact /></td><td><span className={order.side === 'long' ? 'positive' : 'negative'}>{order.action === 'open' ? '开' : '平'}{order.side === 'long' ? '多' : '空'}</span></td><td className="numeric">{number(order.quantity, 5)}</td><td className="numeric">{price(order.price)}</td><td className="numeric">{number(order.fee, 4)}{order.fee_estimated && <small className="fee-estimate">估算</small>}</td><td>{order.action === 'close' ? <Pnl value={order.realized_pnl} /> : <span className="muted">—</span>}</td><td className="reason-cell">{order.reason}</td><td>{modeLabels[order.mode]}</td><td><Badge tone={order.status === 'filled' ? 'success' : 'neutral'}>{({ filled: '已成交', pending: '待确认', failed: '失败', rejected: '已拒绝', canceled: '已撤销', unknown: '待核对' } as Record<string, string>)[order.status] ?? '待核对'}</Badge></td></tr>)}</tbody></table></div>;
}
export function LogsList({ logs }: { logs: Log[] }) {
  if (!logs.length) return <Empty title="暂无运行日志">启动、停止、信号与风控事件会按时间记录。</Empty>;
  return <div className="log-list">{logs.map(log => <div key={log.id} className={`log-row ${log.level}`}><time className="numeric">{dateTime(log.timestamp)}</time><span className="log-level">{log.level === 'error' ? <AlertCircle size={13} /> : log.level === 'warning' ? <Info size={13} /> : <Circle size={7} fill="currentColor" />}{log.level === 'error' ? '异常' : log.level === 'warning' ? '提醒' : '信息'}</span><p>{log.message}</p></div>)}</div>;
}
