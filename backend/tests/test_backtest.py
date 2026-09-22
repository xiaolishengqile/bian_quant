import pytest

from backend.backtest import run_backtest
from backend.models import Candle, StrategyConfig


def test_closed_signal_fills_only_at_next_open_and_includes_costs():
    closes = [100, 99, 98, 97, 98, 130]
    candles = [Candle(time=i*60000, close_time=(i+1)*60000-1,
                      open=120 if i == 5 else value, high=max(value, 120 if i == 5 else value),
                      low=min(value, 120 if i == 5 else value), close=value, volume=1)
               for i, value in enumerate(closes)]
    cfg = StrategyConfig(symbols=['BTCUSDT'], macd_fast=2, macd_slow=3, macd_signal=2,
                         stop_loss_pct=20, take_profit_pct=50)
    result = run_backtest(candles, cfg, 'BTCUSDT')
    assert result['trades'][0]['entry_time'] == 300000
    assert result['trades'][0]['entry_price'] == pytest.approx(120.024)
    assert result['fees'] > 0
    assert result['total_trades'] == 1
    assert any('资金费' in assumption for assumption in result['assumptions'])
    assert any('强平' in assumption for assumption in result['assumptions'])


def test_last_bar_signal_cannot_create_a_trade_without_next_open():
    candles = [Candle(time=i*60000, close_time=(i+1)*60000-1, open=v, high=v, low=v, close=v, volume=1)
               for i, v in enumerate([100, 99, 98, 97, 98])]
    cfg = StrategyConfig(macd_fast=2, macd_slow=3, macd_signal=2)
    result = run_backtest(candles, cfg, 'BTCUSDT')
    assert result['total_trades'] == 0
    assert result['final_equity'] == cfg.initial_balance


def test_same_bar_touching_both_bounds_uses_conservative_stop_first():
    candles = [Candle(time=i*60000, close_time=(i+1)*60000-1, open=v,
                      high=120 if i==5 else v, low=70 if i==5 else v, close=v, volume=1)
               for i, v in enumerate([100, 99, 98, 97, 98, 100])]
    result = run_backtest(candles, StrategyConfig(macd_fast=2, macd_slow=3, macd_signal=2), 'BTCUSDT')
    assert result['trades'][0]['reason'] == '止损'
    assert result['trades'][0]['pnl'] < 0


def test_gap_stop_uses_actual_next_open_instead_of_ideal_stop_price():
    candles = [Candle(time=i*60000, close_time=(i+1)*60000-1, open=v,
                      high=v, low=v, close=v, volume=1)
               for i, v in enumerate([100, 99, 98, 97, 98, 98, 80])]
    result = run_backtest(candles, StrategyConfig(macd_fast=2, macd_slow=3, macd_signal=2), 'BTCUSDT')
    assert result['trades'][0]['reason'] == '跳空止损'
    assert result['trades'][0]['exit_price'] == pytest.approx(79.984)


@pytest.mark.parametrize('fee_bps,slippage_bps', [(4, 0), (0, 4)])
def test_opening_cost_daily_limit_exits_before_profitable_intrabar_move(fee_bps, slippage_bps):
    candles = [Candle(time=i*60000, close_time=(i+1)*60000-1,
                      open=98 if i == 5 else value, high=value,
                      low=98 if i == 5 else value, close=value, volume=1)
               for i, value in enumerate([100, 99, 98, 97, 98, 110])]
    cfg = StrategyConfig(macd_fast=2, macd_slow=3, macd_signal=2,
                         daily_loss_limit=.1, fee_bps=fee_bps, slippage_bps=slippage_bps)
    result = run_backtest(candles, cfg, 'BTCUSDT')
    trade = result['trades'][0]
    assert trade['reason'] == '每日亏损风控'
    assert trade['exit_time'] == trade['entry_time']
    assert result['final_equity'] < cfg.initial_balance


def test_opening_slippage_crossing_stop_exits_at_current_market_price():
    candles = [Candle(time=i*60000, close_time=(i+1)*60000-1,
                      open=value, high=value, low=value, close=value, volume=1)
               for i, value in enumerate([100, 99, 98, 97, 98, 98])]
    cfg = StrategyConfig(macd_fast=2, macd_slow=3, macd_signal=2,
                         stop_loss_pct=.1, slippage_bps=100, fee_bps=0)
    result = run_backtest(candles, cfg, 'BTCUSDT')
    trade = result['trades'][0]
    assert trade['exit_time'] == trade['entry_time']
    assert trade['exit_price'] == pytest.approx(98*.99)
