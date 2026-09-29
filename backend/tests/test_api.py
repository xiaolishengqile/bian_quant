from fastapi.testclient import TestClient
import pytest
import stat

from backend.app import create_app


def make_client(tmp_path, password=""):
    app = create_app(db_path=str(tmp_path / "test.db"), password=password, background=False, allowed_hosts=["testserver"])
    return TestClient(app, client=("127.0.0.1", 51000))


def test_config_lifecycle_and_persistence(tmp_path):
    with make_client(tmp_path) as c:
        initial = c.get("/api/state").json()
        assert initial["config"]["mode"] == "paper"
        assert initial["status"]["state"] == "stopped"
        config = {**initial["config"], "symbols": ["ETHUSDT"], "interval": "1m"}
        assert c.put("/api/config", json=config).status_code == 200
        assert c.post("/api/start").status_code == 200
        assert c.get("/api/state").json()["status"]["state"] == "running"
        assert c.put("/api/config", json=config).status_code == 409
        assert c.post("/api/stop").status_code == 200
    with make_client(tmp_path) as c:
        state = c.get("/api/state").json()
        assert state["config"]["symbols"] == ["ETHUSDT"]
        assert state["status"]["state"] == "stopped"


def test_market_backtest_and_invalid_settings(tmp_path):
    with make_client(tmp_path) as c:
        market = c.get("/api/market?symbol=BTCUSDT&interval=1h")
        assert market.status_code == 200
        payload = market.json()
        assert payload["source"] == "demo"
        assert len(payload["candles"]) >= 100
        assert payload["indicators"]
        assert c.get("/api/market?symbol=../secret").status_code == 422
        result = c.post("/api/backtest", json={"symbol": "BTCUSDT"})
        assert result.status_code == 200
        assert result.json()["assumptions"]
        assert result.json()["bars"] > 100
        config = c.get("/api/state").json()["config"]
        assert c.put("/api/config", json={**config, "leverage": 999}).status_code == 422


def test_live_start_is_locked_without_deployment_switch(tmp_path, monkeypatch):
    monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)
    with make_client(tmp_path, "test-console-password") as c:
        assert c.post("/api/login", json={"password": "test-console-password"}).status_code == 200
        config = c.get("/api/state").json()["config"]
        changed = c.put("/api/config", json={**config, "mode": "live", "market_source": "binance"})
        assert changed.status_code == 200
        response = c.post("/api/start")
        assert response.status_code == 409
        assert c.get("/api/state").json()["orders"] == []


def test_web_credentials_are_private_persistent_and_cannot_bypass_live_gate(tmp_path, monkeypatch):
    monkeypatch.delenv("BINANCE_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_API_SECRET", raising=False)
    monkeypatch.delenv("ENABLE_LIVE_TRADING", raising=False)
    login_password = "test-console-password"
    headers = {"origin": "https://testserver"}
    payload = {"key": "web-key", "secret": "private-secret", "password": login_password}
    with make_client(tmp_path, login_password) as c:
        assert c.put("/api/credentials/live", json=payload, headers=headers).status_code == 401
        assert c.post("/api/login", json={"password": login_password}).status_code == 200
        assert c.put("/api/credentials/live", json={**payload, "password": "wrong"}, headers=headers).status_code == 403
        assert c.put("/api/credentials/live", json=payload).status_code == 403
        response = c.put("/api/credentials/live", json=payload, headers=headers)
        assert response.status_code == 200
        assert response.json()["connections"]["live_managed"] is True
        assert response.json()["connections"]["live_enabled"] is False
        assert "private-secret" not in response.text
        assert "web-key" not in c.get("/api/state").text
        secret_file = tmp_path / "test.db.credentials"
        assert stat.S_IMODE(secret_file.stat().st_mode) == 0o600
        config = c.get("/api/state").json()["config"]
        assert c.put("/api/config", json={**config, "mode": "live", "market_source": "binance"}).status_code == 200
        assert c.post("/api/start").status_code == 409
        assert c.app.state.engine.credentials.get("live") == ("web-key", "private-secret")
    with make_client(tmp_path, login_password) as c:
        c.post("/api/login", json={"password": login_password})
        assert c.get("/api/state").json()["connections"]["live_configured"] is True
        assert c.request("DELETE", "/api/credentials/live", json={"password": login_password}, headers=headers).status_code == 200
        assert c.get("/api/state").json()["connections"]["live_configured"] is False


def test_second_app_cannot_reset_running_persistent_state(tmp_path):
    with make_client(tmp_path) as first:
        assert first.post("/api/start").status_code == 200
        with pytest.raises(RuntimeError, match="正在运行"):
            with make_client(tmp_path):
                pass
        assert first.app.state.engine.storage.load()["status"]["state"] == "running"


def test_live_config_cannot_be_saved_without_console_password(tmp_path):
    with make_client(tmp_path) as c:
        config = c.get("/api/state").json()["config"]
        response = c.put("/api/config", json={**config, "mode": "live", "market_source": "binance"})
        assert response.status_code == 409
        assert c.get("/api/state").json()["config"]["mode"] == "paper"


def test_persisted_live_mode_requires_password_before_any_worker(tmp_path, monkeypatch):
    with make_client(tmp_path, "test-console-password") as c:
        c.post("/api/login", json={"password": "test-console-password"})
        config = c.get("/api/state").json()["config"]
        assert c.put("/api/config", json={**config, "mode": "live", "market_source": "binance"}).status_code == 200
    calls = []
    async def tick(self):
        calls.append(True)
    monkeypatch.setattr("backend.engine.TradingEngine.tick", tick)
    app = create_app(db_path=str(tmp_path / "test.db"), password="", background=True, allowed_hosts=["testserver"])
    with pytest.raises(RuntimeError, match="十二位"):
        with TestClient(app, client=("127.0.0.1", 51000)):
            pass
    assert calls == []


@pytest.mark.parametrize("symbol", ["4USDT", "币安人生USDT"])
def test_market_accepts_short_and_unicode_exchange_symbols(tmp_path, symbol):
    from backend.market import MarketService
    observed = []
    class FixtureMarket:
        async def get_market(self, config, requested, limit=300):
            observed.append(requested)
            demo = await MarketService().get_market(config, "BTCUSDT", limit)
            return demo.model_copy(update={"symbol": requested})
    app = create_app(db_path=str(tmp_path / "symbols.db"), password="", market=FixtureMarket(), background=False, allowed_hosts=["testserver"])
    with TestClient(app, client=("127.0.0.1", 51000)) as c:
        assert c.get("/api/market", params={"symbol": symbol}).status_code == 200
        assert c.post("/api/backtest", json={"symbol": symbol}).status_code == 200
    assert observed == [symbol, symbol]


def test_symbol_list_uses_selected_exchange_environment(tmp_path):
    environments = []

    class FixtureMarket:
        async def get_symbols(self, *, testnet=False):
            environments.append(testnet)
            return [{"symbol": "BTCUSDT", "base_asset": "BTC", "quote_asset": "USDT"}]

    app = create_app(db_path=str(tmp_path / "environments.db"), password="", market=FixtureMarket(),
                     background=False, allowed_hosts=["testserver"])
    with TestClient(app, client=("127.0.0.1", 51000)) as c:
        config = c.get("/api/state").json()["config"]
        for mode in ["testnet", "paper"]:
            assert c.put("/api/config", json={**config, "mode": mode, "market_source": "binance"}).status_code == 200
            assert c.get("/api/symbols").status_code == 200
    assert environments == [True, False]
