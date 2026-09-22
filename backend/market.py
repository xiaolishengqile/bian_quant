"""公开行情与明确标注的演示行情；真实行情失败时绝不回退。"""
import asyncio
import hashlib
import math

from backend.binance_http import BinanceHTTP, LIVE_URL, TESTNET_URL, is_usdt_perpetual, now_ms
from backend.models import Candle, INTERVALS, MarketSnapshot, StrategyConfig


DEMO_PRICES = {"BTCUSDT": 64000, "ETHUSDT": 3200, "SOLUSDT": 150,
               "BNBUSDT": 580, "XRPUSDT": 0.6, "DOGEUSDT": 0.12,
               "ADAUSDT": 0.4, "AVAXUSDT": 30}


class MarketService:
    def __init__(self, *, transport=None, clock=now_ms):
        self.clock = clock
        self.clients = {False: BinanceHTTP(LIVE_URL, transport=transport, clock=clock),
                        True: BinanceHTTP(TESTNET_URL, transport=transport, clock=clock)}
        self._symbols: dict[bool, list[dict]] = {}
        self._symbols_at: dict[bool, int] = {}

    async def get_symbols(self, *, testnet: bool = False) -> list[dict]:
        if testnet in self._symbols and self.clock() - self._symbols_at[testnet] < 300_000:
            return [dict(item) for item in self._symbols[testnet]]
        data = await self.clients[testnet].request("GET", "/fapi/v1/exchangeInfo")
        try:
            symbols = [{"symbol": item["symbol"], "base_asset": item["baseAsset"],
                        "quote_asset": item["quoteAsset"]}
                       for item in data["symbols"] if is_usdt_perpetual(item)]
            if not symbols:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("币安交易对数据无效，请稍后重试") from None
        self._symbols[testnet] = sorted(symbols, key=lambda item: item["symbol"])
        self._symbols_at[testnet] = self.clock()
        return [dict(item) for item in self._symbols[testnet]]

    async def get_market(self, config: StrategyConfig, symbol: str, limit: int = 300) -> MarketSnapshot:
        if not symbol.isalnum() or not symbol.endswith("USDT") or symbol != symbol.upper():
            raise RuntimeError("请选择有效的泰达币永续合约")
        if not 1 <= limit <= 1500:
            raise RuntimeError("行情根数必须介于 1 至 1500")
        if config.market_source == "demo":
            return self._demo(config, symbol, limit)
        client = self.clients[config.mode == "testnet"]
        rows, ticker = await asyncio.gather(
            client.request("GET", "/fapi/v1/klines", {"symbol": symbol, "interval": config.interval, "limit": limit}),
            client.request("GET", "/fapi/v1/ticker/24hr", {"symbol": symbol}),
        )
        try:
            candles = [Candle(time=int(row[0]), open=float(row[1]), high=float(row[2]),
                              low=float(row[3]), close=float(row[4]), volume=float(row[5]),
                              close_time=int(row[6])) for row in rows]
            price = float(ticker["lastPrice"])
            updated = int(ticker["closeTime"])
            change = float(ticker["priceChangePercent"])
            if not candles or price <= 0 or not math.isfinite(price) or not math.isfinite(change):
                raise ValueError
            if any(not all(math.isfinite(x) for x in (c.open, c.high, c.low, c.close, c.volume))
                   or c.low <= 0 or c.low > min(c.open, c.close)
                   or c.high < max(c.open, c.close) or c.volume < 0 or c.close_time < c.time for c in candles):
                raise ValueError
        except (KeyError, IndexError, TypeError, ValueError):
            raise RuntimeError("币安行情数据无效，已停止使用该行情") from None
        if self.clock() - updated > 30_000 or updated - self.clock() > 5000:
            raise RuntimeError("币安最新成交价已过期，请检查网络和服务器时间")
        step = INTERVALS[config.interval] * 1000
        # 指标的每一步必须代表同一周期，不能把缺失或重复蜡烛当作正常历史。
        if (any(c.close_time - c.time != step - 1 for c in candles)
                or any(right.time - left.time != step for left, right in zip(candles, candles[1:]))):
            raise RuntimeError("币安行情数据无效，蜡烛周期或连续性异常")
        return MarketSnapshot(symbol=symbol, interval=config.interval, source="binance", candles=candles,
                              last_price=price, change_pct=change, updated_at=updated)

    def _demo(self, config: StrategyConfig, symbol: str, limit: int) -> MarketSnapshot:
        if symbol not in DEMO_PRICES:
            raise RuntimeError("该币种没有演示行情，请改用币安真实行情")
        now = self.clock()
        step = INTERVALS[config.interval] * 1000
        end = now // step * step
        base = DEMO_PRICES[symbol]
        phase = int(hashlib.sha256(symbol.encode()).hexdigest()[:8], 16) % 1000

        def price_at(timestamp):
            point = timestamp / step + phase
            return base * (1 + 0.026 * math.sin(point / 19) + 0.01 * math.sin(point / 4.7)
                           + 0.008 * math.sin(point / 131))

        candles = []
        for index in range(limit):
            start = end - (limit - 1 - index) * step
            close_time = start + step - 1
            opening, closing = price_at(start), price_at(min(start + step, now))
            wick = base * (0.001 + abs(math.sin(start / step + phase)) * 0.001)
            candles.append(Candle(time=start, open=opening, high=max(opening, closing) + wick,
                                  low=min(opening, closing) - wick, close=closing,
                                  volume=100 + 80 * abs(math.sin(start / step + phase)), close_time=close_time))
        last = price_at(now)
        return MarketSnapshot(symbol=symbol, interval=config.interval, source="demo", candles=candles,
                              last_price=last, change_pct=(last / price_at(now - 86_400_000) - 1) * 100,
                              updated_at=now)
