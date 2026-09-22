"""交易所边界测试；所有请求都由内存传输接管，不访问账户。"""
import asyncio
import hashlib
import hmac
from urllib.parse import parse_qs

import httpx
import pytest

from backend.models import StrategyConfig


NOW = 1_790_000_000_000


def exchange_info():
    return {"symbols": [{
        "symbol": "BTCUSDT", "baseAsset": "BTC", "quoteAsset": "USDT",
        "marginAsset": "USDT", "contractType": "PERPETUAL", "status": "TRADING",
        "quantityPrecision": 5,
        "filters": [
            {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "1000"},
            {"filterType": "MARKET_LOT_SIZE", "stepSize": "0.005", "minQty": "0.005", "maxQty": "10"},
            {"filterType": "MIN_NOTIONAL", "notional": "5"},
        ],
    }]}


class ExchangeFixture:
    def __init__(self):
        self.requests = []
        self.positions = []
        self.open_orders = []
        self.algo_orders = []
        self.hedge = False
        self.multi_asset = False
        self.fail_post = False
        self.status = "FILLED"
        self.query_missing = False
        self.keep_position = False
        self.fee_unavailable = False
        self.balance = "1000"
        self.available = "850"
        self.info = exchange_info()
        self.last_order = None

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path
        raw = request.url.query.decode() or request.content.decode()
        params = {key: value[0] for key, value in parse_qs(raw).items()}
        if path == "/fapi/v1/time":
            data = {"serverTime": NOW}
        elif path == "/fapi/v1/exchangeInfo":
            data = self.info
        elif path == "/fapi/v1/positionSide/dual":
            data = {"dualSidePosition": self.hedge}
        elif path == "/fapi/v1/multiAssetsMargin":
            data = {"multiAssetsMargin": self.multi_asset}
        elif path == "/fapi/v1/accountConfig":
            data = {"canTrade": True, "dualSidePosition": self.hedge, "multiAssetsMargin": self.multi_asset}
        elif path == "/fapi/v3/positionRisk":
            data = self.positions
        elif path == "/fapi/v1/openOrders":
            data = self.open_orders
        elif path == "/fapi/v1/openAlgoOrders":
            data = self.algo_orders
        elif path == "/fapi/v3/account":
            data = {"assets": [{"asset": "USDT", "walletBalance": self.balance, "availableBalance": self.available}]}
        elif path == "/fapi/v1/marginType":
            return httpx.Response(400, json={"code": -4046, "msg": "No need to change margin type."})
        elif path == "/fapi/v1/leverage":
            data = {"leverage": 3, "symbol": "BTCUSDT", "maxNotionalValue": "1000000"}
        elif path == "/fapi/v1/userTrades":
            if self.fee_unavailable:
                return httpx.Response(503, json={"msg": "unavailable"})
            data = [{"orderId": 123, "qty": self.last_order["executedQty"], "commission": "0.12", "commissionAsset": "USDT"}]
        elif path == "/fapi/v1/order" and request.method == "POST":
            self.last_order = {"symbol": "BTCUSDT", "orderId": 123,
                               "clientOrderId": params["newClientOrderId"], "status": self.status,
                               "executedQty": params["quantity"] if self.status == "FILLED" else "0.005",
                               "origQty": params["quantity"], "avgPrice": "60001"}
            if params.get("reduceOnly") == "true" and not self.keep_position:
                self.positions = []
            if self.fail_post:
                raise httpx.ReadTimeout("secret-key must never reach the UI", request=request)
            data = self.last_order
        elif path == "/fapi/v1/order" and request.method == "GET":
            if self.query_missing:
                return httpx.Response(400, json={"code": -2013, "msg": "secret-key"})
            data = self.last_order
        elif path == "/fapi/v1/order" and request.method == "DELETE":
            data = {"status": "CANCELED"}
        else:
            raise AssertionError(f"Unexpected request: {request.method} {path}")
        return httpx.Response(200, json=data)


def broker(monkeypatch, fixture, **overrides):
    from backend.exchange import BinanceBroker
    monkeypatch.setenv("BINANCE_TESTNET_API_KEY", "test-key")
    monkeypatch.setenv("BINANCE_TESTNET_API_SECRET", "secret-key")
    config = StrategyConfig(mode="testnet", market_source="binance", symbols=["BTCUSDT"], **overrides)
    return BinanceBroker(config, transport=httpx.MockTransport(fixture), clock=lambda: NOW)


def params(request):
    return dict(httpx.QueryParams(request.url.query.decode() or request.content.decode()))


def test_preflight_signs_and_applies_each_symbol_settings(monkeypatch):
    fixture = ExchangeFixture()
    client = broker(monkeypatch, fixture)
    result = asyncio.run(client.preflight())
    assert result == {"wallet_balance": 1000.0, "available_balance": 850.0, "positions": []}
    signed = [r for r in fixture.requests if "X-MBX-APIKEY" in r.headers]
    assert signed
    for request in signed:
        raw = request.url.query.decode() or request.content.decode()
        payload, signature = raw.rsplit("&signature=", 1)
        assert signature == hmac.new(b"secret-key", payload.encode(), hashlib.sha256).hexdigest()
        assert request.headers["X-MBX-APIKEY"] == "test-key"
        assert "secret-key" not in str(request.url)
        assert request.url.host == "demo-fapi.binance.com"
    setting = next(r for r in fixture.requests if r.url.path.endswith("marginType"))
    assert params(setting)["marginType"] == "ISOLATED"
    assert params(next(r for r in fixture.requests if r.url.path.endswith("leverage")))["leverage"] == "3"


@pytest.mark.parametrize("guard", ["hedge", "multi_asset", "positions", "open_orders", "algo_orders"])
def test_preflight_refuses_external_exposure_without_account_mutations(monkeypatch, guard):
    fixture = ExchangeFixture()
    if guard == "positions":
        fixture.positions = [{"symbol": "ETHUSDT", "positionAmt": "0.1", "entryPrice": "3000", "positionSide": "BOTH"}]
    else:
        setattr(fixture, guard, True if guard in {"hedge", "multi_asset"} else [{"symbol": "ETHUSDT"}])
    with pytest.raises(RuntimeError):
        asyncio.run(broker(monkeypatch, fixture).preflight())
    assert all(r.method == "GET" for r in fixture.requests)


def test_live_gate_and_missing_credentials_prevent_network(monkeypatch):
    from backend.exchange import BinanceBroker, connection_status
    for name in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET", "ENABLE_LIVE_TRADING"):
        monkeypatch.delenv(name, raising=False)
    fixture = ExchangeFixture()
    live = BinanceBroker(StrategyConfig(mode="live", market_source="binance"), transport=httpx.MockTransport(fixture))
    with pytest.raises(RuntimeError):
        asyncio.run(live.preflight())
    assert connection_status() == {"testnet_configured": False, "live_configured": False, "live_enabled": False}
    monkeypatch.setenv("BINANCE_API_KEY", "test-key")
    monkeypatch.setenv("BINANCE_API_SECRET", "secret-key")
    with pytest.raises(RuntimeError):
        asyncio.run(live.preflight())
    assert fixture.requests == []


def test_market_quantity_uses_step_not_display_precision_and_records_fee(monkeypatch):
    fixture = ExchangeFixture()
    client = broker(monkeypatch, fixture)
    async def scenario():
        await client.preflight()
        return await client.open_position("BTCUSDT", "long", 123, 60000, "bq-open-1")
    result = asyncio.run(scenario())
    assert result["quantity"] == 0.005
    assert result["price"] == 60001
    assert result["fee"] == 0.12
    assert result["fee_estimated"] is False
    order = next(r for r in fixture.requests if r.url.path.endswith("/order") and r.method == "POST")
    assert params(order)["quantity"] == "0.005"
    assert params(order)["positionSide"] == "BOTH"
    assert params(order)["newClientOrderId"] == "bq-open-1"


def test_below_minimum_notional_never_submits_order(monkeypatch):
    fixture = ExchangeFixture()
    fixture.info["symbols"][0]["filters"][-1]["notional"] = "500"
    client = broker(monkeypatch, fixture)
    async def scenario():
        await client.preflight()
        await client.open_position("BTCUSDT", "long", 123, 60000, "bq-small")
    with pytest.raises(RuntimeError, match="最小"):
        asyncio.run(scenario())
    assert not any(r.method == "POST" and r.url.path.endswith("/order") for r in fixture.requests)


@pytest.mark.parametrize("status,missing", [("PARTIALLY_FILLED", False), ("NEW", False), ("FILLED", True)])
def test_unknown_or_partial_order_queries_same_id_and_never_resubmits(monkeypatch, status, missing):
    fixture = ExchangeFixture()
    fixture.fail_post, fixture.status, fixture.query_missing = True, status, missing
    client = broker(monkeypatch, fixture)
    async def scenario():
        await client.preflight()
        await client.open_position("BTCUSDT", "long", 123, 60000, "bq-uncertain")
    with pytest.raises(RuntimeError, match="成交|订单") as error:
        asyncio.run(scenario())
    assert "secret-key" not in str(error.value)
    posts = [r for r in fixture.requests if r.method == "POST" and r.url.path.endswith("/order")]
    queries = [r for r in fixture.requests if r.method == "GET" and r.url.path.endswith("/order")]
    assert len(posts) == len(queries) == 1
    assert params(queries[0])["origClientOrderId"] == "bq-uncertain"


def test_lost_response_recovers_filled_order_without_duplicate(monkeypatch):
    fixture = ExchangeFixture()
    fixture.fail_post = True
    fixture.fee_unavailable = True
    client = broker(monkeypatch, fixture)
    async def scenario():
        await client.preflight()
        result = await client.open_position("BTCUSDT", "short", 123, 60000, "bq-once")
        with pytest.raises(RuntimeError, match="重复"):
            await client.open_position("BTCUSDT", "short", 123, 60000, "bq-once")
        return result
    result = asyncio.run(scenario())
    assert result["quantity"] == 0.005
    assert result["fee_estimated"] is True
    assert result["fee"] == pytest.approx(0.120002)
    assert sum(r.method == "POST" and r.url.path.endswith("/order") for r in fixture.requests) == 1


@pytest.mark.parametrize("keep_position", [False, True])
def test_close_is_reduce_only_and_requires_confirmed_flat(monkeypatch, keep_position):
    fixture = ExchangeFixture()
    client = broker(monkeypatch, fixture)
    async def scenario():
        await client.preflight()
        fixture.positions = [{"symbol": "BTCUSDT", "positionAmt": "-0.005", "entryPrice": "60000", "positionSide": "BOTH"}]
        fixture.keep_position = keep_position
        return await client.close_position("BTCUSDT", "short", 0.005, "bq-close")
    if keep_position:
        with pytest.raises(RuntimeError, match="空仓"):
            asyncio.run(scenario())
    else:
        assert asyncio.run(scenario())["quantity"] == 0.005
    order = next(r for r in fixture.requests if r.url.path.endswith("/order") and r.method == "POST")
    assert params(order)["reduceOnly"] == "true"
    assert params(order)["side"] == "BUY"


def test_cancel_orders_only_cancels_ids_submitted_by_this_instance(monkeypatch):
    fixture = ExchangeFixture()
    client = broker(monkeypatch, fixture)
    async def scenario():
        await client.preflight()
        await client.open_position("BTCUSDT", "long", 123, 60000, "bq-owned")
        fixture.open_orders = [{"symbol": "BTCUSDT", "clientOrderId": "bq-owned"}, {"symbol": "BTCUSDT", "clientOrderId": "external"}]
        await client.cancel_orders()
    asyncio.run(scenario())
    deletes = [r for r in fixture.requests if r.method == "DELETE"]
    assert len(deletes) == 1
    assert params(deletes[0])["origClientOrderId"] == "bq-owned"


def test_account_refresh_reads_exchange_wallet_and_available_balance(monkeypatch):
    fixture = ExchangeFixture()
    client = broker(monkeypatch, fixture)
    async def scenario():
        await client.preflight()
        fixture.balance, fixture.available = "991.75", "740.25"
        return await client.get_account()
    assert asyncio.run(scenario()) == {"wallet_balance": 991.75, "available_balance": 740.25}


@pytest.mark.parametrize("available", [None, "NaN", "Infinity"])
def test_account_invalid_available_balance_refuses_start(monkeypatch, available):
    fixture = ExchangeFixture()
    fixture.available = available
    with pytest.raises(RuntimeError):
        asyncio.run(broker(monkeypatch, fixture).preflight())
    assert all(request.method == "GET" for request in fixture.requests)


@pytest.mark.parametrize("case", ["minimum", "not_ready", "invalid_side", "existing_position", "read_failure", "close_mismatch"])
def test_pre_submission_failures_are_explicitly_not_sent(monkeypatch, case):
    from backend.exchange import OrderNotSentError
    fixture = ExchangeFixture()
    client = broker(monkeypatch, fixture)
    async def scenario():
        if case == "minimum":
            fixture.info["symbols"][0]["filters"][-1]["notional"] = "500"
        if case != "not_ready":
            await client.preflight()
        if case == "existing_position":
            fixture.positions = [{"symbol": "BTCUSDT", "positionAmt": "0.005", "entryPrice": "60000", "positionSide": "BOTH"}]
        if case == "read_failure":
            def unavailable(request):
                raise httpx.ReadTimeout("private connection info", request=request)
            client.http.transport = httpx.MockTransport(unavailable)
        if case == "close_mismatch":
            return await client.close_position("BTCUSDT", "long", 0.005, "bq-not-sent")
        return await client.open_position("BTCUSDT", "invalid" if case == "invalid_side" else "long", 123, 60000, "bq-not-sent")
    with pytest.raises(OrderNotSentError):
        asyncio.run(scenario())
    assert not any(request.method == "POST" and request.url.path.endswith("/order") for request in fixture.requests)


@pytest.mark.parametrize("case", ["unknown", "partial", "close_not_flat"])
def test_after_submission_failures_never_claim_not_sent(monkeypatch, case):
    from backend.exchange import OrderNotSentError
    fixture = ExchangeFixture()
    client = broker(monkeypatch, fixture)
    async def scenario():
        await client.preflight()
        if case == "unknown":
            fixture.fail_post = True
            fixture.query_missing = True
        if case == "partial":
            fixture.status = "PARTIALLY_FILLED"
        if case == "close_not_flat":
            fixture.positions = [{"symbol": "BTCUSDT", "positionAmt": "0.005", "entryPrice": "60000", "positionSide": "BOTH"}]
            fixture.keep_position = True
            return await client.close_position("BTCUSDT", "long", 0.005, "bq-sent")
        return await client.open_position("BTCUSDT", "long", 123, 60000, "bq-sent")
    with pytest.raises(RuntimeError) as error:
        asyncio.run(scenario())
    assert not isinstance(error.value, OrderNotSentError)
    assert sum(request.method == "POST" and request.url.path.endswith("/order") for request in fixture.requests) == 1
