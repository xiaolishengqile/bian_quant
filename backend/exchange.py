"""单向泰达币永续交易。只有确定全成的订单才交给引擎记账。"""
import asyncio
import math
import os
import re
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_DOWN

from backend.binance_http import BinanceAPIError, BinanceHTTP, LIVE_URL, TESTNET_URL, is_usdt_perpetual, now_ms
from backend.models import StrategyConfig


class OrderNotSentError(RuntimeError):
    """本次操作尚未进入下单请求；可修正配置后由用户重新启动。"""


@contextmanager
def before_submission():
    try:
        yield
    except RuntimeError as error:
        raise OrderNotSentError(str(error)) from None
    except Exception:
        raise OrderNotSentError("下单前检查失败，订单尚未发送，请核对配置与连接") from None


def connection_status() -> dict:
    return {
        "testnet_configured": bool(os.getenv("BINANCE_TESTNET_API_KEY") and os.getenv("BINANCE_TESTNET_API_SECRET")),
        "live_configured": bool(os.getenv("BINANCE_API_KEY") and os.getenv("BINANCE_API_SECRET")),
        "live_enabled": os.getenv("ENABLE_LIVE_TRADING", "").lower() == "true",
    }


def decimal(value) -> Decimal:
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            raise InvalidOperation
        return result
    except (InvalidOperation, ValueError, TypeError):
        raise RuntimeError("交易所金额或数量无效") from None


class BinanceBroker:
    def __init__(self, config: StrategyConfig, *, transport=None, clock=now_ms):
        self.config = config.model_copy(deep=True)
        self.http = BinanceHTTP(TESTNET_URL if config.mode == "testnet" else LIVE_URL, transport=transport, clock=clock)
        self._rules: dict[str, dict] = {}
        self._used_ids: set[str] = set()
        self._ready = False
        self._lock = asyncio.Lock()

    def _credentials(self) -> tuple[str, str]:
        if self.config.mode not in {"testnet", "live"}:
            raise RuntimeError("模拟盘不能调用交易所下单接口")
        if self.config.mode == "live" and not connection_status()["live_enabled"]:
            raise RuntimeError("实盘部署开关未开启")
        prefix = "BINANCE_TESTNET" if self.config.mode == "testnet" else "BINANCE"
        key, secret = os.getenv(prefix + "_API_KEY"), os.getenv(prefix + "_API_SECRET")
        if not key or not secret:
            raise RuntimeError("服务器尚未配置所选环境的币安密钥")
        return key, secret

    async def _signed(self, method, path, params=None):
        return await self.http.request(method, path, params, credentials=self._credentials())

    async def preflight(self) -> dict:
        async with self._lock:
            self._ready = False
            self._credentials()
            await self.http.sync_time()
            mode = await self._signed("GET", "/fapi/v1/accountConfig")
            if not isinstance(mode, dict) or mode.get("canTrade") is not True:
                raise RuntimeError("账户没有合约交易权限，或无法确认账户配置")
            if mode.get("dualSidePosition") is not False:
                raise RuntimeError("账户必须使用单向持仓；请先在交易所核对，程序不会修改全局持仓模式")
            if mode.get("multiAssetsMargin") is not False:
                raise RuntimeError("本版本只支持单资产保证金，请先在交易所核对账户模式")
            positions = await self.get_positions()
            if positions:
                raise RuntimeError("账户已有外部或未核对持仓，禁止启动；请先到交易所核对并平仓")
            orders = await self._signed("GET", "/fapi/v1/openOrders")
            algo_orders = await self._signed("GET", "/fapi/v1/openAlgoOrders")
            if not isinstance(orders, list) or not isinstance(algo_orders, list):
                raise RuntimeError("无法核对账户挂单，禁止启动")
            if orders or algo_orders:
                raise RuntimeError("账户存在挂单或条件订单，禁止启动；请先在交易所处理")
            account = await self.get_account()
            await self._load_rules()
            for symbol in self.config.symbols:
                self._symbol_rule(symbol)
                try:
                    await self._signed("POST", "/fapi/v1/marginType", {
                        "symbol": symbol, "marginType": "ISOLATED" if self.config.margin_mode == "isolated" else "CROSSED"})
                except BinanceAPIError as error:
                    if error.code != -4046:  # 已处于所选保证金模式是明确的幂等成功。
                        raise
                leverage = await self._signed("POST", "/fapi/v1/leverage", {"symbol": symbol, "leverage": self.config.leverage})
                if leverage.get("leverage") != self.config.leverage:
                    raise RuntimeError("交易所未确认所选杠杆，禁止启动")
            self._ready = True
            return {**account, "positions": []}

    async def get_account(self) -> dict:
        data = await self._signed("GET", "/fapi/v3/account")
        try:
            asset = next(item for item in data["assets"] if item["asset"] == "USDT")
            wallet, available = float(decimal(asset["walletBalance"])), float(decimal(asset["availableBalance"]))
            if not math.isfinite(wallet) or not math.isfinite(available):
                raise ValueError
        except (KeyError, TypeError, ValueError, StopIteration):
            raise RuntimeError("无法读取泰达币钱包及可用余额，禁止继续交易") from None
        return {"wallet_balance": wallet, "available_balance": available}

    async def _load_rules(self):
        data = await self.http.request("GET", "/fapi/v1/exchangeInfo")
        try:
            self._rules = {item["symbol"]: item for item in data["symbols"] if is_usdt_perpetual(item)}
        except (KeyError, TypeError):
            raise RuntimeError("无法读取合约交易规则") from None

    def _symbol_rule(self, symbol):
        if symbol not in self.config.symbols or symbol not in self._rules:
            raise RuntimeError("币种不在策略范围或不是可交易的泰达币永续合约")
        return self._rules[symbol]

    def _quantity(self, symbol: str, requested: Decimal, price: Decimal | None = None, *, closing=False) -> Decimal:
        filters = self._symbol_rule(symbol).get("filters", [])
        lots = [item for item in filters if item.get("filterType") in {"LOT_SIZE", "MARKET_LOT_SIZE"}]
        if not lots:
            raise RuntimeError("合约缺少数量规则，禁止下单")
        steps = [decimal(item.get("stepSize", 0)) for item in lots if decimal(item.get("stepSize", 0)) > 0]
        if not steps:
            raise RuntimeError("合约数量步长无效，禁止下单")
        scale = 10 ** max(0, max(-step.as_tuple().exponent for step in steps))
        step = Decimal(math.lcm(*(int(value * scale) for value in steps))) / scale
        quantity = (requested / step).to_integral_value(rounding=ROUND_DOWN) * step
        if closing and quantity != requested:
            raise RuntimeError("平仓数量不符合交易所精度，须人工核对，避免残留仓位")
        if quantity <= 0 or any(quantity < decimal(item.get("minQty", 0)) for item in lots):
            raise RuntimeError("下单数量小于交易所最小数量")
        if any(decimal(item.get("maxQty", 0)) > 0 and quantity > decimal(item["maxQty"]) for item in lots):
            raise RuntimeError("下单数量超过交易所最大数量")
        if not closing and price is not None:
            for item in filters:
                if item.get("filterType") in {"MIN_NOTIONAL", "NOTIONAL"}:
                    minimum = decimal(item.get("notional", item.get("minNotional", 0)))
                    if quantity * price < minimum:
                        raise RuntimeError("下单名义金额小于交易所最小金额")
                    maximum = decimal(item.get("maxNotional", 0))
                    if maximum > 0 and quantity * price > maximum:
                        raise RuntimeError("下单名义金额超过交易所上限")
        return quantity

    async def get_positions(self) -> list[dict]:
        rows = await self._signed("GET", "/fapi/v3/positionRisk")
        if not isinstance(rows, list):
            raise RuntimeError("交易所持仓数据无效")
        positions = []
        try:
            for item in rows:
                amount = decimal(item["positionAmt"])
                if amount == 0:
                    continue
                if item.get("positionSide") != "BOTH":
                    raise RuntimeError("检测到双向持仓，须人工核对")
                positions.append({"symbol": item["symbol"], "side": "long" if amount > 0 else "short",
                                  "quantity": float(abs(amount)), "entry_price": float(decimal(item["entryPrice"]))})
        except (KeyError, TypeError):
            raise RuntimeError("交易所持仓数据无效") from None
        return positions

    async def open_position(self, symbol: str, side: str, margin: float, price: float, client_id: str) -> dict:
        async with self._lock:
            with before_submission():
                if not self._ready:
                    raise RuntimeError("必须通过账户启动检查后才能开仓")
                self._validate_order(side, client_id)
                value, reference = decimal(margin), decimal(price)
                if value <= 0 or reference <= 0:
                    raise RuntimeError("保证金和参考价格必须大于零")
                quantity = self._quantity(symbol, value * self.config.leverage / reference, reference)
                if any(item["symbol"] == symbol for item in await self.get_positions()):
                    raise RuntimeError("开仓前检测到已有仓位，须人工核对")
            # 提交边界：从此处开始的异常绝不能声称“未发送”。
            return await self._execute(symbol, "BUY" if side == "long" else "SELL", quantity, client_id)

    async def close_position(self, symbol: str, side: str, quantity: float, client_id: str) -> dict:
        async with self._lock:
            with before_submission():
                self._validate_order(side, client_id)
                self._credentials()
                if not self._rules:
                    await self.http.sync_time()
                    await self._load_rules()
                requested = self._quantity(symbol, decimal(quantity), closing=True)
                positions = [item for item in await self.get_positions() if item["symbol"] == symbol]
                if len(positions) != 1 or positions[0]["side"] != side or decimal(positions[0]["quantity"]) != requested:
                    raise RuntimeError("交易所仓位与本地平仓数量不一致，须人工核对")
            result = await self._execute(symbol, "SELL" if side == "long" else "BUY", requested, client_id, closing=True)
            if any(item["symbol"] == symbol for item in await self.get_positions()):
                raise RuntimeError("平仓成交后未确认空仓，已停止继续交易，请到交易所核对")
            return result

    def _validate_order(self, side: str, client_id: str):
        if side not in {"long", "short"}:
            raise RuntimeError("交易方向无效")
        if not isinstance(client_id, str) or not re.fullmatch(r"[.A-Za-z0-9_:/-]{1,36}", client_id):
            raise RuntimeError("订单标识无效")
        if client_id in self._used_ids:
            raise RuntimeError("禁止重复使用订单标识，请人工核对已有订单")

    async def _execute(self, symbol, side, quantity, client_id, *, closing=False):
        self._used_ids.add(client_id)
        payload = {"symbol": symbol, "side": side, "type": "MARKET", "positionSide": "BOTH",
                   "quantity": format(quantity, "f"), "newClientOrderId": client_id, "newOrderRespType": "RESULT"}
        if closing:
            payload["reduceOnly"] = "true"
        try:
            order = await self._signed("POST", "/fapi/v1/order", payload)
        except RuntimeError:
            order = None
        if not isinstance(order, dict) or order.get("status") != "FILLED":
            # 只查询原订单，任何错误均禁止再次发送下单请求。
            try:
                order = await self._signed("GET", "/fapi/v1/order", {"symbol": symbol, "origClientOrderId": client_id})
            except RuntimeError:
                raise RuntimeError("订单成交状态未知，禁止自动重试；请到交易所核对订单和仓位") from None
        try:
            if (not isinstance(order, dict) or order.get("status") != "FILLED" or order.get("symbol") != symbol
                    or order.get("clientOrderId") != client_id or decimal(order["executedQty"]) != quantity
                    or decimal(order["origQty"]) != quantity):
                raise RuntimeError("订单未确认全部成交，已停止继续交易；请到交易所核对")
            executed = decimal(order["executedQty"])
            average = decimal(order.get("avgPrice", 0))
            if average <= 0:
                average = decimal(order.get("cumQuote", 0)) / executed
            order_id = order["orderId"]
            if average <= 0 or not order_id:
                raise RuntimeError("订单成交详情不完整，须人工核对")
        except (KeyError, TypeError, InvalidOperation):
            raise RuntimeError("订单成交详情不完整，须人工核对") from None
        fee, estimated = await self._fee(symbol, order_id, executed, average)
        return {"quantity": float(executed), "price": float(average), "fee": float(fee),
                "order_id": str(order_id), "fee_estimated": estimated}

    async def _fee(self, symbol, order_id, quantity, price):
        try:
            trades = await self._signed("GET", "/fapi/v1/userTrades", {"symbol": symbol, "orderId": order_id, "limit": 1000})
            relevant = [item for item in trades if str(item["orderId"]) == str(order_id)]
            if relevant and all(item["commissionAsset"] == "USDT" for item in relevant):
                if sum((decimal(item["qty"]) for item in relevant), Decimal(0)) == quantity:
                    return sum((decimal(item["commission"]) for item in relevant), Decimal(0)), False
        except (RuntimeError, TypeError, KeyError):
            pass
        # 成交已确认时，费用查询失败不能丢弃仓位；明确标记估计费用供日志展示。
        return quantity * price * decimal(self.config.fee_bps) / 10_000, True

    async def cancel_orders(self) -> None:
        async with self._lock:
            orders = await self._signed("GET", "/fapi/v1/openOrders")
            if not isinstance(orders, list):
                raise RuntimeError("无法核对挂单，取消操作已停止")
            for order in orders:
                if order.get("clientOrderId") in self._used_ids:
                    await self._signed("DELETE", "/fapi/v1/order", {
                        "symbol": order["symbol"], "origClientOrderId": order["clientOrderId"]})
