import { dateTime, number } from '../format';

export default function EquityChart({ points, initial }: { points: { time: number; equity: number }[]; initial: number }) {
  if (!points.length) return <div className="empty-state">本次回测暂无资金曲线数据。</div>;
  const left = 20, right = 830, top = 25, bottom = 240;
  const values = [...points.map(point => point.equity), initial];
  const min = Math.min(...values), max = Math.max(...values), span = max - min || initial * 0.01 || 1;
  const low = min - span * 0.15, high = max + span * 0.15;
  const x = (index: number) => left + index / Math.max(1, points.length - 1) * (right - left);
  const y = (value: number) => bottom - (value - low) / (high - low) * (bottom - top);
  const path = points.map((point, index) => `${index === 0 ? 'M' : 'L'}${x(index)},${y(point.equity)}`).join(' ');
  return <div className="equity-chart"><svg viewBox="0 0 930 285" role="img" aria-label="历史回测账户权益曲线"><defs><linearGradient id="equity-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#d1b171" stopOpacity=".16" /><stop offset="100%" stopColor="#d1b171" stopOpacity="0" /></linearGradient></defs>{[0, 1, 2, 3, 4].map(index => { const yy = top + (bottom - top) * index / 4; return <g key={index}><line x1={left} x2={right} y1={yy} y2={yy} className="chart-grid" /><text x={right + 14} y={yy + 4} className="chart-axis">{number(high - (high - low) * index / 4)}</text></g>; })}<line x1={left} x2={right} y1={y(initial)} y2={y(initial)} stroke="#63656a" strokeDasharray="5 5" /><path d={`${path} L${right},${bottom} L${left},${bottom} Z`} fill="url(#equity-fill)" /><path d={path} fill="none" stroke="#d1b171" strokeWidth="2" />{[0, 1, 2, 3, 4].map(index => { const i = Math.round(index / 4 * (points.length - 1)); return <text key={index} x={x(i)} y={273} textAnchor={index === 0 ? 'start' : index === 4 ? 'end' : 'middle'} className="chart-axis">{dateTime(points[i].time)}</text>; })}</svg></div>;
}
