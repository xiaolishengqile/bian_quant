"""单进程策略执行器；所有资金变更均在异步锁内串行执行。"""
import asyncio
import math
import time
import uuid
from datetime import datetime, timezone

from backend.models import INTERVALS, StrategyConfig
from backend.storage import Storage, account_key
from backend.indicators import calculate_macd, signal_direction
from backend.exchange import BinanceBroker, OrderNotSentError, connection_status
from backend.credentials import CredentialStore


def _now_ms():
    return int(time.time() * 1000)


class TradingEngine:
    def __init__(self, db_path: str, market):
        self.market = market
        self.storage = Storage(db_path)
        self.credentials = CredentialStore(db_path)
        self.lock = asyncio.Lock()
        self.broker = None
        self.data = self.storage.load() or self._initial(StrategyConfig())
        self.config = StrategyConfig.model_validate(self.data['config'])
        self.data['status']['state'] = 'risk_stopped' if self.data.get('daily_loss_day') == self._day() else 'stopped'
        if self.storage.unresolved():
            self.data['status']['state'] = 'error'
            self.data['status']['last_error'] = '存在成交状态未知的订单，请核对交易所和本地记录，禁止重新开仓'
        self.storage.save(self.data)

    def _initial(self, config):
        return {'config': config.model_dump(), 'status': {'state': 'stopped', 'last_tick': None,
                'last_error': None, 'started_at': None}, 'positions': {}, 'last_seen': {},
                'wallet': config.initial_balance, 'baseline': config.initial_balance,
                'realized': 0, 'fees': 0, 'trades': 0, 'wins': 0,
                'day': self._day(), 'day_start_equity': config.initial_balance}

    def _day(self):
        return datetime.fromtimestamp(_now_ms()/1000, timezone.utc).date().isoformat()

    async def save_config(self, config):
        async with self.lock:
            if self.data['status']['state'] == 'running' or self.data['positions']:
                raise RuntimeError('请先停止策略并平仓，再修改交易配置')
            if self.storage.unresolved():
                raise RuntimeError('存在未知订单，核对完成前不能修改配置')
            candidate = StrategyConfig.model_validate(config)
            switching = account_key(candidate.model_dump()) != account_key(self.config.model_dump())
            target = self.storage.load_account(candidate.model_dump()) if switching else self.data
            if target is None:
                target = self._initial(candidate)
            elif candidate.initial_balance != target['config']['initial_balance']:
                if target['fees'] or target['trades']:
                    raise RuntimeError('该账户已有成交，初始资金不可直接修改；请恢复原金额或先重置该模拟账户')
                target = self._initial(candidate)
            self.config = candidate
            self.data = target
            self.data['config'] = candidate.model_dump()
            self.data['status']['state'] = 'stopped'
            self._roll_day()
            self.broker = None
            self.storage.save(self.data)
            if switching:
                self._log('已切换独立账户，余额与成交历史按模式及行情来源分别保存')

    def _equity(self):
        return self.data['wallet'] + sum(p['unrealized_pnl'] for p in self.data['positions'].values())

    def _roll_day(self):
        if self.data['day'] != self._day():
            self.data['day'] = self._day()
            self.data['day_start_equity'] = self._equity()
            self.data.pop('daily_loss_day', None)
            if self.data['status']['state'] == 'risk_stopped':
                self.data['status']['state'] = 'stopped'
                self.data['status']['last_error'] = None

    def _daily_limit(self):
        return (self.data.get('daily_loss_day') == self.data['day'] or
                self._equity() - self.data['day_start_equity'] <= -self.config.daily_loss_limit)

    def _log(self, message, level='info'):
        self.storage.log(_now_ms(), level, message)

    def _error(self, message):
        self.data['status'].update(state='error', last_error=message)
        self._log(message, 'error')
        self.storage.save(self.data)

    async def _market(self, symbol):
        snapshot = await self.market.get_market(self.config, symbol)
        if snapshot.error or not math.isfinite(snapshot.last_price) or snapshot.last_price <= 0:
            raise RuntimeError('行情异常，已暂停开仓')
        if snapshot.source != self.config.market_source:
            raise RuntimeError('行情来源与配置不一致，已暂停开仓')
        if _now_ms() - snapshot.updated_at > 60000:
            raise RuntimeError('行情已过期，已暂停开仓')
        candles = self._closed(snapshot)
        if not candles or _now_ms()-candles[-1].close_time > INTERVALS[self.config.interval]*1000+60000:
            raise RuntimeError('已收盘行情已过期，已暂停开仓')
        return snapshot

    def _closed(self, snapshot):
        return sorted({c.time: c for c in snapshot.candles
                       if c.close_time <= min(_now_ms(), snapshot.updated_at)}.values(), key=lambda c: c.time)

    async def _reconcile(self):
        if self.config.mode == 'paper':
            return
        if self.broker is None:
            self.broker = BinanceBroker(self.config, credentials=self.credentials)
        remote = await self.broker.get_positions()
        local = self.data['positions']
        if len(remote) != len(local):
            raise RuntimeError('交易所仓位与本地记录不一致，请核对；已禁止下单')
        for position in remote:
            known = local.get(position['symbol'])
            if (not known or known['side'] != position['side'] or
                    not math.isclose(known['quantity'], position['quantity'], rel_tol=1e-8, abs_tol=1e-10) or
                    not math.isclose(known['entry_price'], position['entry_price'], rel_tol=1e-6, abs_tol=1e-8)):
                raise RuntimeError('交易所仓位与本地记录不一致，请核对；已禁止下单')
        await self._sync_account()

    async def _sync_account(self):
        account = await self.broker.get_account()
        balance, available = float(account['wallet_balance']), float(account['available_balance'])
        if not math.isfinite(balance) or not math.isfinite(available):
            raise RuntimeError('交易所账户余额异常，已禁止开仓')
        self.data.update(wallet=balance, available_balance=available)

    async def start(self):
        async with self.lock:
            self._roll_day()
            if self.storage.unresolved():
                raise RuntimeError('存在未知订单，请先核对交易所，禁止重新开仓')
            if self._daily_limit():
                self.data['daily_loss_day'] = self.data['day']
                self.storage.save(self.data)
                raise RuntimeError('已触发每日亏损上限，请等待下一自然日')
            if self.data['status']['state'] == 'running':
                return
            try:
                if self.config.mode != 'paper':
                    if self.data['positions']:
                        await self._reconcile()
                        raise RuntimeError('已有真实仓位，请先核对并平仓后再启动；停止期间继续风控')
                    self.broker = BinanceBroker(self.config, credentials=self.credentials)
                    account = await self.broker.preflight()
                    if account.get('positions'):
                        raise RuntimeError('账户存在外部仓位，禁止接管')
                    balance = float(account['wallet_balance'])
                    if not math.isfinite(balance) or balance < self.config.order_margin:
                        raise RuntimeError('交易所可用资金不足')
                    first_account = not self.data.get('account_initialized')
                    self.data['wallet'] = balance
                    self.data['available_balance'] = float(account['available_balance'])
                    if first_account:
                        self.data.update(baseline=balance, day_start_equity=balance, account_initialized=True)
                    if self._daily_limit():
                        self.data['daily_loss_day'] = self.data['day']
                        raise RuntimeError('已触发每日亏损上限，请等待下一自然日')
                for symbol in self.config.symbols:
                    candles = self._closed(await self._market(symbol))
                    if len(candles) < self.config.macd_slow + self.config.macd_signal - 1:
                        raise RuntimeError('已收盘行情不足，指标尚未预热')
                    self.data['last_seen'][symbol] = candles[-1].time
                self.data['status'].update(state='running', last_error=None, started_at=_now_ms())
                self._log('策略已启动，从下一根新收盘蜡烛开始识别信号')
                self.storage.save(self.data)
            except Exception as exc:
                self._error(str(exc))
                raise RuntimeError(str(exc)) from None

    async def stop(self):
        async with self.lock:
            self.data['status']['state'] = 'error' if self.storage.unresolved() else 'stopped'
            self._log('已停止开仓，已有仓位继续执行止盈止损')
            self.storage.save(self.data)

    async def _execute(self, symbol, side, action, price, reason):
        if any(order['symbol'] == symbol for order in self.storage.unresolved()):
            raise RuntimeError('该币种有未知订单，请在交易所核对后处理')
        position = self.data['positions'].get(symbol)
        order = {'id': 'bq-'+uuid.uuid4().hex, 'timestamp': _now_ms(), 'symbol': symbol,
                 'side': side, 'action': action, 'reason': reason, 'mode': self.config.mode,
                 'status': 'pending'}
        self.storage.intent(order)
        try:
            if self.config.mode == 'paper':
                buying = (side == 'long') == (action == 'open')
                fill_price = price * (1 + (1 if buying else -1)*self.config.slippage_bps/10000)
                quantity = (self.config.order_margin*self.config.leverage/fill_price
                            if action == 'open' else position['quantity'])
                fill = {'quantity': quantity, 'price': fill_price,
                        'fee': quantity*fill_price*self.config.fee_bps/10000}
            elif action == 'open':
                fill = await self.broker.open_position(symbol, side, self.config.order_margin, price, order['id'])
            else:
                fill = await self.broker.close_position(symbol, side, position['quantity'], order['id'])
            quantity, fill_price, fee = (float(fill[key]) for key in ('quantity', 'price', 'fee'))
            if not all(math.isfinite(v) for v in (quantity, fill_price, fee)) or min(quantity, fill_price) <= 0 or fee < 0:
                raise RuntimeError('成交结果异常，必须人工核对')
            if action == 'close' and not math.isclose(quantity, position['quantity'], rel_tol=1e-8):
                raise RuntimeError('未确认全部平仓，必须人工核对')
            order.update(quantity=quantity, price=fill_price, fee=fee, realized_pnl=0, status='filled')
            if 'order_id' in fill:
                order['exchange_order_id'] = str(fill['order_id'])
            order['fee_estimated'] = bool(fill.get('fee_estimated', False))
            self.data['wallet'] -= fee
            self.data['fees'] += fee
            self.data['realized'] -= fee
            if self.config.mode != 'paper':
                self.data['available_balance'] -= fee
            sign = 1 if side == 'long' else -1
            if action == 'open':
                self.data['positions'][symbol] = {
                    'symbol': symbol, 'side': side, 'quantity': quantity, 'entry_price': fill_price,
                    'mark_price': price, 'leverage': self.config.leverage,
                    'margin': quantity*fill_price/self.config.leverage,
                    'unrealized_pnl': (price-fill_price)*quantity*sign,
                    'stop_loss': fill_price*(1-sign*self.config.stop_loss_pct/100),
                    'take_profit': fill_price*(1+sign*self.config.take_profit_pct/100),
                    'opened_at': _now_ms(), 'open_fee': fee}
                if self.config.mode != 'paper':
                    self.data['available_balance'] -= quantity*fill_price/self.config.leverage
            else:
                gross = (fill_price-position['entry_price'])*quantity*sign
                net = gross-fee-position['open_fee']
                order['realized_pnl'] = net
                self.data['wallet'] += gross
                if self.config.mode != 'paper':
                    self.data['available_balance'] += position['margin']+gross
                self.data['realized'] += gross
                self.data['trades'] += 1
                self.data['wins'] += int(net > 0)
                del self.data['positions'][symbol]
            self.storage.complete(order, self.data)
            if fill.get('fee_estimated'):
                self._log('本次成交手续费暂按配置费率估算，请以交易所账单为准', 'warning')
            self._log(f'{symbol} 已确认'+('开多' if side == 'long' else '开空') if action == 'open'
                      else f'{symbol} 已确认平仓：{reason}')
        except OrderNotSentError as exc:
            order.update(quantity=0, price=0, fee=0, realized_pnl=0, status='rejected')
            self.data['status'].update(state='error', last_error=f'订单未发送：{exc}；修正配置后可重新启动')
            self.storage.complete(order, self.data)
            raise RuntimeError(self.data['status']['last_error']) from None
        except Exception as exc:
            self.data['status'].update(state='error', last_error=f'订单状态未知：{exc}；请核对交易所，禁止重发')
            self.storage.mark_unknown(order['id'], self.data)
            raise RuntimeError(self.data['status']['last_error']) from None

    async def _close(self, symbol, reason):
        position = self.data['positions'][symbol]
        await self._execute(symbol, position['side'], 'close', position['mark_price'], reason)

    def _can_open(self):
        if self.storage.unresolved() or self._daily_limit():
            return False
        used = sum(p['margin'] for p in self.data['positions'].values())
        fee = self.config.order_margin*self.config.leverage*self.config.fee_bps/10000
        if self.config.mode != 'paper' and self.config.order_margin+fee > self.data.get('available_balance', 0):
            return False
        return (used+self.config.order_margin <= self.config.max_position_margin+1e-8 and
                self.config.order_margin+fee <= min(self.data['wallet'], self._equity())-used)

    async def _risk(self, available):
        closed = set()
        margins = [position['margin'] for position in self.data['positions'].values()]
        excess_margin = (sum(margins) > self.config.max_position_margin+1e-6 or
                         any(margin > self.config.order_margin+1e-6 for margin in margins))
        daily_limit = self._daily_limit()
        if daily_limit:
            # 风控触发后锁存到次日；行情恢复、权益反弹或进程重启不能撤销退出。
            self.data['daily_loss_day'] = self.data['day']
        if daily_limit or excess_margin:
            reason = '保证金风控' if excess_margin else '每日亏损风控'
            self.data['status'].update(state='risk_stopped', last_error='已触发'+reason)
            for symbol in list(self.data['positions']):
                if symbol in available:
                    await self._close(symbol, reason)
                    closed.add(symbol)
            return closed
        for symbol, position in list(self.data['positions'].items()):
            if symbol not in available:
                continue
            sign = 1 if position['side'] == 'long' else -1
            if sign*(position['mark_price']-position['stop_loss']) <= 0:
                await self._close(symbol, '止损')
                closed.add(symbol)
            elif sign*(position['mark_price']-position['take_profit']) >= 0:
                await self._close(symbol, '止盈')
                closed.add(symbol)
        return closed

    async def tick(self):
        async with self.lock:
            self._roll_day()
            self.data['status']['last_tick'] = _now_ms()
            try:
                if self.data['status']['state'] == 'running' or self.data['positions']:
                    await self._reconcile()
                    snapshots = {}
                    for symbol in set(self.config.symbols) | set(self.data['positions']):
                        try:
                            snapshots[symbol] = await self._market(symbol)
                        except RuntimeError as exc:
                            self._error(str(exc))
                            continue
                        position = self.data['positions'].get(symbol)
                        if position:
                            position['mark_price'] = snapshots[symbol].last_price
                            position['unrealized_pnl'] = (position['mark_price']-position['entry_price'])*position['quantity']*(1 if position['side']=='long' else -1)
                    risk_closed = await self._risk(snapshots)
                    for symbol in self.config.symbols:
                        if symbol not in snapshots:
                            continue
                        candles = self._closed(snapshots[symbol])
                        if not candles or candles[-1].time <= self.data['last_seen'].get(symbol, -1):
                            continue
                        self.data['last_seen'][symbol] = candles[-1].time
                        self.storage.save(self.data)
                        if self.data['status']['state'] != 'running' or len(candles) < 2 or symbol in risk_closed:
                            continue
                        indicators = calculate_macd(candles, self.config.macd_fast, self.config.macd_slow, self.config.macd_signal)
                        direction = signal_direction(indicators[-2], indicators[-1])
                        position = self.data['positions'].get(symbol)
                        if not direction or position and direction == position['side']:
                            continue
                        if position:
                            await self._close(symbol, '反向信号')
                            if not self.config.reverse_on_signal:
                                continue
                        if self._can_open():
                            await self._execute(symbol, direction, 'open', snapshots[symbol].last_price, '指标金叉' if direction=='long' else '指标死叉')
                            await self._risk(snapshots)
                        else:
                            self._log(f'{symbol} 开仓被保证金或每日亏损限额阻止', 'warning')
                    await self._risk(snapshots)
            except Exception as exc:
                self._error(str(exc))
            self.storage.save(self.data)

    async def flatten(self, symbol=None):
        async with self.lock:
            if symbol is None:
                self.data['status']['state'] = 'error' if self.storage.unresolved() else 'stopped'
                self.storage.save(self.data)
            if symbol is not None and symbol not in self.config.symbols:
                raise RuntimeError('币种不在当前策略中')
            try:
                await self._reconcile()
                for name in list(self.data['positions']):
                    if symbol is None or name == symbol:
                        snapshot = await self._market(name)
                        self.data['positions'][name]['mark_price'] = snapshot.last_price
                        await self._close(name, '手动平仓')
                self.storage.save(self.data)
            except Exception as exc:
                self._error(str(exc))
                raise RuntimeError(str(exc)) from None

    async def reset_paper(self):
        async with self.lock:
            if self.config.mode != 'paper' or self.data['status']['state'] == 'running' or self.data['positions']:
                raise RuntimeError('仅可重置已停止且无仓位的模拟账户')
            self.data = self._initial(self.config)
            self.storage.reset(self.data)
            self._log('模拟账户资金与成交记录已重置')

    async def snapshot(self):
        async with self.lock:
            positions = [{k: v for k, v in p.items() if k != 'open_fee'} for p in self.data['positions'].values()]
            used_margin = sum(p['margin'] for p in positions)
            return {'config': self.config.model_dump(), 'status': dict(self.data['status']),
                    'positions': positions, 'orders': self.storage.orders(), 'logs': self.storage.logs(),
                    'connections': connection_status(self.credentials), 'summary': {
                        'account_synced': self.config.mode == 'paper' or bool(self.data.get('account_initialized')),
                        'available_balance': self.data['wallet']-used_margin if self.config.mode == 'paper'
                        else self.data.get('available_balance'),
                        'initial_balance': self.data['baseline'], 'wallet_balance': self.data['wallet'],
                        'equity': self._equity(), 'unrealized_pnl': self._equity()-self.data['wallet'],
                        'realized_pnl': self.data['realized'], 'fees': self.data['fees'],
                        'total_trades': self.data['trades'],
                        'win_rate': self.data['wins']/self.data['trades']*100 if self.data['trades'] else 0,
                        'exposure': used_margin,
                        'daily_pnl': self._equity()-self.data['day_start_equity']}}

    def close(self):
        self.storage.close()
