"""真实行情不得静默变为演示数据。"""
import asyncio

import httpx
import pytest

from backend.models import StrategyConfig


NOW = 1_790_000_000_000


def test_demo_is_explicit_deterministic_and_closed_history_does_not_change():
    from backend.market import MarketService
    clock = [NOW]
    service = MarketService(clock=lambda: clock[0])
    first = asyncio.run(service.get_market(StrategyConfig(), "BTCUSDT", 60))
    again = asyncio.run(service.get_market(StrategyConfig(), "BTCUSDT", 60))
    assert first == again
    assert first.source == "demo"
    assert len(first.candles) == 60
    clock[0] += 15 * 60_000
    next_bar = asyncio.run(service.get_market(StrategyConfig(), "BTCUSDT", 60))
    assert first.candles[1:-1] == next_bar.candles[:-2]
    assert all(c.low <= min(c.open, c.close) <= max(c.open, c.close) <= c.high for c in first.candles)


def test_real_price_comes_from_fresh_ticker_not_last_closed_candle():
    from backend.market import MarketService
    hosts = []
    def handle(request):
        hosts.append(request.url.host)
        if request.url.path.endswith("klines"):
            return httpx.Response(200, json=[[NOW - 60_000, "60000", "61000", "59000", "60500", "10", NOW - 1, "0", 1, "0", "0", "0"]])
        if request.url.path.endswith("24hr"):
            return httpx.Response(200, json={"symbol": "BTCUSDT", "lastPrice": "62000", "priceChangePercent": "2.5", "closeTime": NOW})
        raise AssertionError(request.url.path)
    service = MarketService(transport=httpx.MockTransport(handle), clock=lambda: NOW)
    config = StrategyConfig(mode="testnet", market_source="binance", interval="1m")
    market = asyncio.run(service.get_market(config, "BTCUSDT", 50))
    assert market.last_price == 62000
    assert market.candles[-1].close == 60500
    assert market.change_pct == 2.5
    assert market.source == "binance"
    assert set(hosts) == {"demo-fapi.binance.com"}


def test_real_network_failure_never_returns_demo():
    from backend.market import MarketService
    def fail(request):
        raise httpx.ConnectError("private connection details", request=request)
    service = MarketService(transport=httpx.MockTransport(fail), clock=lambda: NOW)
    with pytest.raises(RuntimeError) as error:
        asyncio.run(service.get_market(StrategyConfig(market_source="binance"), "BTCUSDT"))
    assert "private connection details" not in str(error.value)


def test_stale_real_ticker_is_rejected():
    from backend.market import MarketService
    def handle(request):
        data = [[NOW - 60_000, "1", "1", "1", "1", "1", NOW - 1]] if request.url.path.endswith("klines") else {"lastPrice": "1", "closeTime": NOW - 120_000, "priceChangePercent": "0"}
        return httpx.Response(200, json=data)
    with pytest.raises(RuntimeError, match="过期"):
        asyncio.run(MarketService(transport=httpx.MockTransport(handle), clock=lambda: NOW).get_market(StrategyConfig(market_source="binance"), "BTCUSDT"))


def test_symbols_only_include_trading_usdt_perpetuals():
    from backend.market import MarketService
    base = {"symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT", "marginAsset": "USDT", "status": "TRADING", "contractType": "PERPETUAL"}
    items = [base, {**base, "symbol": "ETHUSDT", "status": "SETTLING"}, {**base, "symbol": "BTCUSDT_240927", "contractType": "CURRENT_QUARTER"}, {**base, "symbol": "BTCUSDC", "quoteAsset": "USDC"}]
    service = MarketService(transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"symbols": items})))
    assert asyncio.run(service.get_symbols()) == [{"symbol": "BTCUSDT", "base_asset": "BTC", "quote_asset": "USDT"}]


def test_symbol_lists_and_cache_are_separate_for_testnet():
    from backend.market import MarketService
    hosts = []
    def handle(request):
        hosts.append(request.url.host)
        base = "ETH" if request.url.host == "demo-fapi.binance.com" else "BTC"
        return httpx.Response(200, json={"symbols": [{"symbol": base + "USDT", "baseAsset": base,
            "quoteAsset": "USDT", "marginAsset": "USDT", "status": "TRADING", "contractType": "PERPETUAL"}]})
    service = MarketService(transport=httpx.MockTransport(handle), clock=lambda: NOW)
    async def scenario():
        assert (await service.get_symbols())[0]["symbol"] == "BTCUSDT"
        assert (await service.get_symbols(testnet=True))[0]["symbol"] == "ETHUSDT"
        assert (await service.get_symbols())[0]["symbol"] == "BTCUSDT"
        assert (await service.get_symbols(testnet=True))[0]["symbol"] == "ETHUSDT"
    asyncio.run(scenario())
    assert hosts == ["fapi.binance.com", "demo-fapi.binance.com"]


@pytest.mark.parametrize("case", ["gap", "duplicate", "wrong_interval", "reverse", "negative_volume"])
def test_invalid_candle_timeline_is_rejected_before_indicator_use(case):
    from backend.market import MarketService
    starts = [NOW - 180_000, NOW - 120_000, NOW - 60_000]
    rows = [[start, "1", "1", "1", "1", "1", start + 59_999] for start in starts]
    if case == "gap":
        rows.pop(1)
    elif case == "duplicate":
        rows[1] = rows[0]
    elif case == "wrong_interval":
        rows[0][6] += 60_000
    elif case == "reverse":
        rows.reverse()
    else:
        rows[0][5] = "-1"
    def handle(request):
        data = rows if request.url.path.endswith("klines") else {
            "symbol": "BTCUSDT", "lastPrice": "1", "closeTime": NOW, "priceChangePercent": "0"}
        return httpx.Response(200, json=data)
    service = MarketService(transport=httpx.MockTransport(handle), clock=lambda: NOW)
    with pytest.raises(RuntimeError, match="行情数据无效"):
        asyncio.run(service.get_market(StrategyConfig(market_source="binance", interval="1m"), "BTCUSDT"))


def test_malformed_environment_proxy_returns_safe_runtime_error(monkeypatch):
    from backend.market import MarketService
    monkeypatch.setenv("HTTPS_PROXY", "http://private-host:not-a-port")
    monkeypatch.setenv("NO_PROXY", "")
    with pytest.raises(RuntimeError) as error:
        asyncio.run(MarketService().get_symbols())
    assert "private-host" not in str(error.value)


@pytest.mark.parametrize("bypass,expected_proxy", [
    ("127.0.0.1,localhost,::1,::1/128", "http://proxy.example:8080"),
    ("::1/128,.binance.com", None),
    ("*", None),
    ("fapi.binance.com:443", None),
    ("binance.com.other.test", "http://proxy.example:8080"),
])
def test_ipv6_proxy_bypass_is_local_and_preserves_https_proxy(monkeypatch, bypass, expected_proxy):
    import os
    from backend.market import MarketService
    for key in ("http_proxy", "https_proxy", "all_proxy", "no_proxy", "ALL_PROXY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    monkeypatch.setenv("HTTP_PROXY", "http://wrong-proxy.example:8081")
    monkeypatch.setenv("NO_PROXY", bypass)
    selected = []
    def make_transport(**kwargs):
        selected.append(kwargs.get("proxy"))
        return httpx.MockTransport(lambda _: httpx.Response(200, json={"symbols": [{
            "symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT", "marginAsset": "USDT",
            "status": "TRADING", "contractType": "PERPETUAL"}]}))
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", make_transport)
    result = asyncio.run(MarketService().get_symbols())
    assert result[0]["symbol"] == "BTCUSDT"
    assert selected == [expected_proxy]
    assert os.environ["NO_PROXY"] == bypass
