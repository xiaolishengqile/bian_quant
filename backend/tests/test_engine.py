import asyncio
import pytest

import backend.engine as module
from backend.engine import TradingEngine
from backend.models import Candle, MarketSnapshot, StrategyConfig

NOW = 1_800_000_000_000


class Market:
    def __init__(self):
        self.values = [100, 99, 98, 97]
        self.price = 97
        self.unclosed = False

    async def get_market(self, config, symbol, limit=300):
        candles = [Candle(time=NOW-600000+i*60000, close_time=NOW-540001+i*60000,
                          open=v, high=v, low=v, close=v, volume=1)
                   for i, v in enumerate(self.values)]
        if self.unclosed:
            candles[-1].close_time = NOW+59999
        return MarketSnapshot(symbol=symbol, interval=config.interval, source=config.market_source,
                              candles=candles, last_price=self.price, updated_at=NOW)


def config(**changes):
    return StrategyConfig(symbols=['BTCUSDT'], macd_fast=2, macd_slow=3, macd_signal=2,
                          stop_loss_pct=20, take_profit_pct=50, **changes)


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setattr(module, '_now_ms', lambda: NOW)
    market = Market()
    item = TradingEngine(str(tmp_path/'trading.db'), market)
    run(item.save_config(config()))
    yield item, market
    item.close()


async def open_long(engine, market):
    await engine.start()
    market.values.append(98)
    market.price = 98
    await engine.tick()


def test_start_never_chases_old_signal_and_unclosed_candle_is_ignored(engine):
    item, market = engine
    market.values.append(98)
    run(item.start())
    run(item.tick())
    assert run(item.snapshot())['orders'] == []
    run(item.stop())
    market.values = [100, 99, 98, 97]
    run(item.start())
    market.values.append(98)
    market.unclosed = True
    run(item.tick())
    assert run(item.snapshot())['positions'] == []


def test_signal_is_only_processed_once_and_fees_reduce_equity(engine):
    item, market = engine
    run(open_long(item, market))
    run(item.tick())
    state = run(item.snapshot())
    assert len(state['positions']) == 1
    assert len(state['orders']) == 1
    assert state['summary']['fees'] == pytest.approx(0.12)
    assert state['summary']['equity'] < 10000
    assert state['positions'][0]['entry_price'] > 98


def test_reverse_closes_before_opening_opposite_side(engine):
    item, market = engine
    run(open_long(item, market))
    market.values.extend([97, 96])
    market.price = 96
    run(item.tick())
    state = run(item.snapshot())
    assert [o['action'] for o in reversed(state['orders'])] == ['open', 'close', 'open']
    assert state['positions'][0]['side'] == 'short'


def test_stopped_strategy_still_closes_at_stop_loss(engine):
    item, market = engine
    run(open_long(item, market))
    run(item.stop())
    market.price = 70
    run(item.tick())
    state = run(item.snapshot())
    assert state['positions'] == []
    assert state['orders'][0]['reason'] == '止损'
    assert state['status']['state'] == 'stopped'


def test_total_margin_limit_blocks_second_symbol(engine):
    item, market = engine
    run(item.save_config(config().model_copy(update={'symbols': ['BTCUSDT', 'ETHUSDT'], 'max_position_margin': 100})))
    run(open_long(item, market))
    state = run(item.snapshot())
    assert len(state['positions']) == 1
    assert state['summary']['exposure'] == 100


def test_paper_restart_preserves_positions_orders_and_stops_strategy(engine, tmp_path):
    item, market = engine
    run(open_long(item, market))
    restored = TradingEngine(str(tmp_path/'trading.db'), market)
    state = run(restored.snapshot())
    assert len(state['positions']) == 1
    assert len(state['orders']) == 1
    assert state['status']['state'] == 'stopped'
    restored.close()


def test_daily_loss_stops_and_flattens_positions(engine):
    item, market = engine
    run(item.save_config(config(daily_loss_limit=10)))
    run(open_long(item, market))
    market.price = 90
    run(item.tick())
    state = run(item.snapshot())
    assert state['status']['state'] == 'risk_stopped'
    assert state['positions'] == []
    with pytest.raises(RuntimeError, match='每日'):
        run(item.start())


def test_utc_day_rollover_resets_daily_risk_base(engine, monkeypatch):
    item, market = engine
    run(open_long(item, market))
    run(item.flatten())
    assert run(item.snapshot())['summary']['daily_pnl'] < 0
    monkeypatch.setattr(module, '_now_ms', lambda: NOW+86400000)
    run(item.tick())
    assert run(item.snapshot())['summary']['daily_pnl'] == pytest.approx(0)


class Broker:
    def __init__(self, cfg):
        self.positions = []
        self.fail = False
        self.wallet = 10000
        self.available = 10000

    async def preflight(self):
        return {'wallet_balance': self.wallet, 'available_balance': self.available, 'positions': self.positions}

    async def get_account(self):
        return {'wallet_balance': self.wallet, 'available_balance': self.available}

    async def get_positions(self):
        return self.positions

    async def open_position(self, symbol, side, margin, price, client_id):
        if self.fail:
            raise RuntimeError('成交状态未知')
        self.positions = [{'symbol': symbol, 'side': side, 'quantity': 3, 'entry_price': price}]
        self.wallet -= .12
        return {'quantity': 3, 'price': price, 'fee': .12, 'order_id': '123'}

    async def close_position(self, symbol, side, quantity, client_id):
        self.wallet += (98-self.positions[0]['entry_price'])*quantity*(1 if side == 'long' else -1)-.12
        self.positions = []
        return {'quantity': quantity, 'price': 98, 'fee': .12, 'order_id': '124'}

    async def cancel_orders(self):
        pass


def test_unknown_real_order_blocks_retry_even_after_restart(engine, monkeypatch, tmp_path):
    item, market = engine
    monkeypatch.setattr(module, 'BinanceBroker', Broker)
    run(item.save_config(config(mode='testnet', market_source='binance')))
    run(item.start())
    item.broker.fail = True
    market.values.append(98)
    market.price = 98
    run(item.tick())
    assert run(item.snapshot())['status']['state'] == 'error'
    with pytest.raises(RuntimeError, match='未知|核对'):
        run(item.start())
    restored = TradingEngine(str(tmp_path/'trading.db'), market)
    with pytest.raises(RuntimeError, match='未知|核对'):
        run(restored.start())
    restored.close()


def test_config_and_reset_cannot_discard_open_positions(engine):
    item, market = engine
    run(open_long(item, market))
    with pytest.raises(RuntimeError):
        run(item.save_config(config()))
    run(item.stop())
    with pytest.raises(RuntimeError):
        run(item.reset_paper())


def test_daily_loss_includes_entry_fees_and_mark_to_market(engine):
    item, market = engine
    run(item.save_config(config(daily_loss_limit=.15, slippage_bps=0)))
    run(open_long(item, market))
    assert run(item.snapshot())['summary']['daily_pnl'] == pytest.approx(-.12)
    market.price = 97.98  # 未平仓亏损约0.061，加开仓费用后越过0.15限额。
    run(item.tick())
    state = run(item.snapshot())
    assert state['status']['state'] == 'risk_stopped'
    assert state['positions'] == []
    assert state['summary']['daily_pnl'] < -.15


def test_stop_loss_cannot_reopen_on_same_tick_reverse_signal(engine):
    item, market = engine
    run(open_long(item, market))
    market.values.extend([97, 70])
    market.price = 70
    run(item.tick())
    assert run(item.snapshot())['positions'] == []
    assert len(run(item.snapshot())['orders']) == 2


def test_reverse_option_can_close_without_reopening(engine):
    item, market = engine
    run(item.save_config(config(reverse_on_signal=False)))
    run(open_long(item, market))
    market.values.extend([97, 96])
    market.price = 96
    run(item.tick())
    assert run(item.snapshot())['positions'] == []
    assert len(run(item.snapshot())['orders']) == 2


def test_fee_reserve_prevents_using_all_cash_as_margin(engine):
    item, market = engine
    run(item.save_config(config(initial_balance=100, max_position_margin=100)))
    run(open_long(item, market))
    assert run(item.snapshot())['positions'] == []


def test_unknown_intent_is_visible_for_manual_reconciliation(engine, monkeypatch):
    item, market = engine
    monkeypatch.setattr(module, 'BinanceBroker', Broker)
    run(item.save_config(config(mode='testnet', market_source='binance')))
    run(item.start())
    item.broker.fail = True
    market.values.append(98)
    run(item.tick())
    orders = run(item.snapshot())['orders']
    assert len(orders) == 1
    assert orders[0]['status'] == 'unknown'
    assert orders[0]['id'].startswith('bq-')


def test_stale_candles_cannot_trigger_delayed_open(engine, monkeypatch):
    item, market = engine
    run(item.start())
    market.values.append(98)
    original = market.get_market
    async def stale(*args):
        snapshot = await original(*args)
        snapshot.candles = [c.model_copy(update={'time': c.time-86400000, 'close_time': c.close_time-86400000}) for c in snapshot.candles]
        return snapshot
    monkeypatch.setattr(market, 'get_market', stale)
    run(item.tick())
    assert run(item.snapshot())['status']['state'] == 'error'
    assert run(item.snapshot())['positions'] == []


def test_failed_symbol_does_not_disable_other_position_stop_loss(engine, monkeypatch):
    item, market = engine
    run(item.save_config(config().model_copy(update={'symbols': ['BTCUSDT', 'ETHUSDT']})))
    run(open_long(item, market))
    run(item.stop())
    original = market.get_market
    async def partial(cfg, symbol, *args):
        if symbol == 'BTCUSDT':
            raise RuntimeError('该币种行情暂不可用')
        return await original(cfg, symbol, *args)
    monkeypatch.setattr(market, 'get_market', partial)
    market.price = 70
    run(item.tick())
    state = run(item.snapshot())
    assert [p['symbol'] for p in state['positions']] == ['BTCUSDT']
    assert state['status']['state'] == 'error'


def test_real_restart_checks_quantity_and_entry_before_risk_order(engine, monkeypatch, tmp_path):
    item, market = engine
    monkeypatch.setattr(module, 'BinanceBroker', Broker)
    run(item.save_config(config(mode='testnet', market_source='binance')))
    run(open_long(item, market))
    restored = TradingEngine(str(tmp_path/'trading.db'), market)
    restored.broker = item.broker
    restored.broker.positions[0]['entry_price'] = 110
    market.price = 70
    run(restored.tick())
    assert run(restored.snapshot())['status']['state'] == 'error'
    assert len(run(restored.snapshot())['positions']) == 1
    restored.close()


def test_flatten_all_stops_new_signals_before_closing_positions(engine):
    item, market = engine
    run(open_long(item, market))
    run(item.flatten())
    market.values.extend([97, 96])
    market.price = 96
    run(item.tick())
    state = run(item.snapshot())
    assert state['status']['state'] == 'stopped'
    assert state['positions'] == []
    assert len(state['orders']) == 2


def test_account_switch_restores_each_environments_balance_and_history(engine, monkeypatch):
    item, market = engine
    monkeypatch.setattr(module, 'BinanceBroker', Broker)
    run(open_long(item, market))
    run(item.flatten())
    paper_balance = run(item.snapshot())['summary']['wallet_balance']
    market.values = [100, 99, 98, 97]
    run(item.save_config(config(mode='testnet', market_source='binance')))
    assert run(item.snapshot())['orders'] == []
    run(open_long(item, market))
    run(item.flatten())
    live_balance = run(item.snapshot())['summary']['wallet_balance']
    run(item.save_config(config()))
    state = run(item.snapshot())
    assert len(state['orders']) == 2
    assert state['summary']['wallet_balance'] == pytest.approx(paper_balance)
    run(item.save_config(config(mode='testnet', market_source='binance', leverage=5)))
    state = run(item.snapshot())
    assert state['summary']['wallet_balance'] == pytest.approx(live_balance)
    assert state['config']['leverage'] == 5
    assert len(state['orders']) == 2


def test_demo_and_real_market_paper_accounts_have_separate_records(engine):
    item, market = engine
    run(open_long(item, market))
    run(item.flatten())
    run(item.save_config(config(market_source='binance')))
    assert run(item.snapshot())['orders'] == []
    assert run(item.snapshot())['summary']['wallet_balance'] == 10000
    run(item.save_config(config()))
    assert len(run(item.snapshot())['orders']) == 2


def test_real_account_funding_loss_triggers_daily_risk(engine, monkeypatch):
    item, market = engine
    monkeypatch.setattr(module, 'BinanceBroker', Broker)
    run(item.save_config(config(mode='testnet', market_source='binance')))
    run(open_long(item, market))
    item.broker.wallet -= 250
    run(item.tick())
    state = run(item.snapshot())
    assert state['status']['state'] == 'risk_stopped'
    assert state['positions'] == []
    assert state['summary']['daily_pnl'] < -250


def test_real_available_balance_blocks_order_despite_large_wallet(engine, monkeypatch):
    item, market = engine
    monkeypatch.setattr(module, 'BinanceBroker', Broker)
    run(item.save_config(config(mode='testnet', market_source='binance')))
    run(item.start())
    item.broker.available = 50
    market.values.append(98)
    market.price = 98
    run(item.tick())
    assert run(item.snapshot())['positions'] == []


def test_real_account_is_marked_unsynced_until_successful_preflight(engine, monkeypatch):
    item, market = engine
    monkeypatch.setattr(module, 'BinanceBroker', Broker)
    run(item.save_config(config(mode='testnet', market_source='binance')))
    state = run(item.snapshot())
    assert state['summary']['account_synced'] is False
    assert state['summary']['available_balance'] is None
    run(item.start())
    state = run(item.snapshot())
    assert state['summary']['account_synced'] is True
    assert state['summary']['available_balance'] == 10000


def test_paper_available_balance_excludes_occupied_margin(engine):
    item, market = engine
    run(open_long(item, market))
    state = run(item.snapshot())
    assert state['summary']['account_synced'] is True
    assert state['summary']['available_balance'] == pytest.approx(9899.88)


def test_actual_fill_exceeding_margin_cap_is_closed_and_stops_strategy(engine, monkeypatch):
    class ExcessFill(Broker):
        async def open_position(self, symbol, side, margin, price, client_id):
            self.positions = [{'symbol': symbol, 'side': side, 'quantity': 4, 'entry_price': price}]
            return {'quantity': 4, 'price': price, 'fee': .12, 'order_id': 'oversized'}
    item, market = engine
    monkeypatch.setattr(module, 'BinanceBroker', ExcessFill)
    run(item.save_config(config(mode='testnet', market_source='binance', max_position_margin=100)))
    run(open_long(item, market))
    state = run(item.snapshot())
    assert state['status']['state'] == 'risk_stopped'
    assert state['positions'] == []
    assert state['orders'][0]['reason'] == '保证金风控'


def test_confirmed_not_sent_order_is_rejected_and_allows_config_repair(engine, monkeypatch):
    from backend.exchange import OrderNotSentError
    class RejectedBroker(Broker):
        async def open_position(self, *args):
            raise OrderNotSentError('下单金额小于交易所最小金额')
    item, market = engine
    monkeypatch.setattr(module, 'BinanceBroker', RejectedBroker)
    run(item.save_config(config(mode='testnet', market_source='binance')))
    run(open_long(item, market))
    state = run(item.snapshot())
    assert state['status']['state'] == 'error'
    assert state['orders'][0]['status'] == 'rejected'
    assert state['positions'] == []
    assert state['summary']['wallet_balance'] == 10000
    run(item.save_config(config(mode='testnet', market_source='binance', order_margin=200)))
    run(item.start())
    run(item.tick())
    assert len(run(item.snapshot())['orders']) == 1
    assert run(item.snapshot())['status']['state'] == 'running'


def test_partial_reverse_close_never_opens_opposite_order(engine, monkeypatch):
    class PartialCloseBroker(Broker):
        async def close_position(self, symbol, side, quantity, client_id):
            self.positions[0]['quantity'] = quantity/2
            return {'quantity': quantity/2, 'price': 96, 'fee': .06, 'order_id': 'partial'}
    item, market = engine
    monkeypatch.setattr(module, 'BinanceBroker', PartialCloseBroker)
    run(item.save_config(config(mode='testnet', market_source='binance')))
    run(open_long(item, market))
    market.values.extend([97, 96])
    market.price = 96
    run(item.tick())
    run(item.tick())
    state = run(item.snapshot())
    assert state['status']['state'] == 'error'
    assert len(state['orders']) == 2
    assert state['orders'][0]['status'] == 'unknown'
    assert item.broker.positions[0]['side'] == 'long'
    with pytest.raises(RuntimeError, match='未知|核对'):
        run(item.start())


def test_paper_restart_still_protects_restored_position(engine, tmp_path):
    item, market = engine
    run(open_long(item, market))
    restored = TradingEngine(str(tmp_path/'trading.db'), market)
    try:
        market.price = 70
        run(restored.tick())
        state = run(restored.snapshot())
        assert state['status']['state'] == 'stopped'
        assert state['positions'] == []
        assert state['orders'][0]['reason'] == '止损'
    finally:
        restored.close()


def test_daily_loss_remains_latched_after_partial_data_failure_and_restart(engine, monkeypatch, tmp_path):
    item, market = engine
    run(item.save_config(config(daily_loss_limit=10).model_copy(update={'symbols': ['BTCUSDT', 'ETHUSDT']})))
    run(open_long(item, market))
    original = market.get_market

    async def partial(cfg, symbol, *args):
        if symbol == 'ETHUSDT':
            raise RuntimeError('行情暂不可用')
        return await original(cfg, symbol, *args)

    monkeypatch.setattr(market, 'get_market', partial)
    market.price = 90
    run(item.tick())
    assert [p['symbol'] for p in run(item.snapshot())['positions']] == ['ETHUSDT']
    monkeypatch.setattr(market, 'get_market', original)
    market.price = 110
    restored = TradingEngine(str(tmp_path/'trading.db'), market)
    try:
        run(restored.tick())
        state = run(restored.snapshot())
        assert state['summary']['daily_pnl'] > 0  # 反弹不撤销此前已触发的当日风险退出。
        assert state['positions'] == []
        assert state['status']['state'] == 'risk_stopped'
        with pytest.raises(RuntimeError, match='每日'):
            run(restored.start())
        monkeypatch.setattr(module, '_now_ms', lambda: NOW+86400000)
        run(restored.tick())
        assert run(restored.snapshot())['status']['state'] == 'stopped'
        assert not restored._daily_limit()
    finally:
        restored.close()


def test_start_rechecks_daily_loss_after_syncing_real_wallet(engine, monkeypatch):
    item, market = engine
    monkeypatch.setattr(module, 'BinanceBroker', Broker)
    run(item.save_config(config(mode='testnet', market_source='binance')))
    run(item.start())
    run(item.stop())

    class ReducedWallet(Broker):
        def __init__(self, cfg):
            super().__init__(cfg)
            self.wallet = 9700
            self.available = 9700

    monkeypatch.setattr(module, 'BinanceBroker', ReducedWallet)
    with pytest.raises(RuntimeError, match='每日'):
        run(item.start())
    assert run(item.snapshot())['status']['state'] != 'running'
    assert run(item.snapshot())['orders'] == []
