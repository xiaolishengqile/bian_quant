"""单币种历史模拟：上一收盘信号仅能在下一根开盘执行。"""
from datetime import datetime, timezone
import math
import time

from backend.indicators import calculate_macd, signal_direction
from backend.models import Candle, StrategyConfig


def run_backtest(candles: list[Candle], config: StrategyConfig, symbol: str) -> dict:
    bars = sorted({c.time: c for c in candles if c.close_time <= int(time.time()*1000)}.values(), key=lambda c: c.time)
    if not bars:
        raise RuntimeError('没有可用的已收盘行情')
    if any(not all(math.isfinite(v) and v > 0 for v in (c.open, c.high, c.low, c.close)) for c in bars):
        raise RuntimeError('历史行情价格异常')
    lines = calculate_macd(bars, config.macd_fast, config.macd_slow, config.macd_signal)
    wallet = config.initial_balance
    fees = 0.0
    position = None
    trades, curve = [], []
    day, day_start, stopped = None, wallet, False
    peak, maximum_drawdown = wallet, 0.0

    def execution_price(price, side, opening):
        buy = (side == 'long') == opening
        return price*(1+(1 if buy else -1)*config.slippage_bps/10000)

    def close_position(price, timestamp, reason):
        nonlocal position, wallet, fees
        fill = execution_price(price, position['side'], False)
        fee = position['quantity']*fill*config.fee_bps/10000
        gross = (fill-position['entry_price'])*position['quantity']*position['sign']
        wallet += gross-fee
        fees += fee
        trades.append({'symbol': symbol, 'side': position['side'],
                       'entry_time': position['entry_time'], 'exit_time': timestamp,
                       'entry_price': position['entry_price'], 'exit_price': fill,
                       'quantity': position['quantity'], 'fees': position['fee']+fee,
                       'pnl': gross-position['fee']-fee, 'reason': reason})
        position = None

    for index, candle in enumerate(bars):
        current_day = datetime.fromtimestamp(candle.time/1000, timezone.utc).date()
        if day != current_day:
            day = current_day
            day_start = curve[-1]['equity'] if curve else wallet
            stopped = False
        # 开盘跳空首先检查存量仓位风险，避免用理想止损价填平跳空。
        risk_exit = False
        if position:
            at_open = wallet + (candle.open-position['entry_price'])*position['quantity']*position['sign']
            if at_open-day_start <= -config.daily_loss_limit:
                close_position(candle.open, candle.time, '每日亏损风控')
                stopped, risk_exit = True, True
            elif position['sign']*(candle.open-position['stop']) <= 0:
                close_position(candle.open, candle.time, '跳空止损')
                risk_exit = True
            elif position['sign']*(candle.open-position['take']) >= 0:
                close_position(candle.open, candle.time, '跳空止盈')
                risk_exit = True
        direction = signal_direction(lines[index-2], lines[index-1]) if index >= 2 else None
        if direction and not stopped and not risk_exit:
            reversed_position = position is not None and position['side'] != direction
            if reversed_position:
                close_position(candle.open, candle.time, '反向信号')
            if not position and (not reversed_position or config.reverse_on_signal):
                opening_fee = config.order_margin*config.leverage*config.fee_bps/10000
                if (config.order_margin <= config.max_position_margin and
                        config.order_margin+opening_fee <= wallet and
                        wallet-day_start > -config.daily_loss_limit):
                    fill = execution_price(candle.open, direction, True)
                    sign = 1 if direction == 'long' else -1
                    position = {'side': direction, 'entry_price': fill, 'entry_time': candle.time,
                                'quantity': config.order_margin*config.leverage/fill, 'sign': sign,
                                'fee': opening_fee, 'stop': fill*(1-sign*config.stop_loss_pct/100),
                                'take': fill*(1+sign*config.take_profit_pct/100)}
                    wallet -= opening_fee
                    fees += opening_fee
        if position:
            sign = position['sign']
            stop_hit = candle.low <= position['stop'] if sign == 1 else candle.high >= position['stop']
            take_hit = candle.high >= position['take'] if sign == 1 else candle.low <= position['take']
            # 同一根同时触及止盈止损时采用保守的止损优先，不猜测蜡烛内部路径。
            if stop_hit:
                close_position(position['stop'], candle.close_time, '止损')
            elif take_hit:
                close_position(position['take'], candle.close_time, '止盈')
        equity = wallet + ((candle.close-position['entry_price'])*position['quantity']*position['sign'] if position else 0)
        if equity-day_start <= -config.daily_loss_limit:
            stopped = True
            if position:
                close_position(candle.close, candle.close_time, '每日亏损风控')
            equity = wallet
        if index == len(bars)-1 and position:
            close_position(candle.close, candle.close_time, '回测结束')
            equity = wallet
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, (peak-equity)/peak*100)
        curve.append({'time': candle.close_time, 'equity': equity})
    return {'symbol': symbol, 'bars': len(bars), 'start_time': bars[0].time,
            'end_time': bars[-1].close_time, 'initial_balance': config.initial_balance,
            'final_equity': wallet, 'return_pct': (wallet/config.initial_balance-1)*100,
            'max_drawdown_pct': maximum_drawdown, 'total_trades': len(trades),
            'win_rate': sum(t['pnl'] > 0 for t in trades)/len(trades)*100 if trades else 0,
            'fees': fees, 'trades': trades, 'equity_curve': curve, 'assumptions': [
                '仅采用已收盘蜡烛；上一根收盘交叉信号在下一根开盘成交，末尾仓位按末根收盘价结算。',
                '每次成交计入配置手续费和不利方向滑点；单币种独立使用初始资金，不能相加当作组合收益。',
                '同一根同时触及止盈止损按止损优先；跳空按开盘价成交；每日限额在开盘和收盘检查，不能保证损失上限。',
                '不包含资金费率、强平、维持保证金、盘口深度及真实成交延迟；历史结果不代表未来收益。',
                '最大回撤基于每根收盘权益，可能低估盘中回撤。']}
