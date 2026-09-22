"""从网页接口贯通指标、模拟成交和进程恢复，全部使用隔离数据库。"""
from fastapi.testclient import TestClient

import backend.engine as engine_module
from backend.app import create_app
from backend.models import Candle, MarketSnapshot


def test_api_signal_reversal_restart_and_flatten(tmp_path, monkeypatch):
    interval = 900_000
    start_time = 1_800_000_000_000
    clock = [start_time + 4 * interval]
    monkeypatch.setattr(engine_module, "_now_ms", lambda: clock[0])

    class ReplayMarket:
        prices = [100, 99, 98, 97]

        async def get_market(self, config, symbol, limit=300):
            candles = [Candle(time=start_time + i * interval,
                              close_time=start_time + (i + 1) * interval - 1,
                              open=price, high=price, low=price, close=price, volume=1)
                       for i, price in enumerate(self.prices)]
            return MarketSnapshot(symbol=symbol, interval=config.interval, source="demo",
                                  candles=candles, last_price=self.prices[-1], updated_at=clock[0])

    market = ReplayMarket()

    def client():
        app = create_app(db_path=str(tmp_path / "workflow.db"), password="", market=market,
                         background=False, allowed_hosts=["testserver"])
        return TestClient(app, client=("127.0.0.1", 51000))

    with client() as c:
        config = c.get("/api/state").json()["config"]
        config.update(symbols=["BTCUSDT"], macd_fast=2, macd_slow=3, macd_signal=2,
                      stop_loss_pct=20, take_profit_pct=50)
        assert c.put("/api/config", json=config).status_code == 200
        assert c.post("/api/start").status_code == 200
        assert c.get("/api/state").json()["orders"] == []
        for price in [98, 97, 96]:
            market.prices.append(price)
            clock[0] += interval
            c.portal.call(c.app.state.engine.tick)
            c.portal.call(c.app.state.engine.tick)  # 重复轮询不能重复成交。
        state = c.get("/api/state").json()
        assert [(o["action"], o["side"]) for o in reversed(state["orders"])] == [
            ("open", "long"), ("close", "long"), ("open", "short")]
        assert state["positions"][0]["side"] == "short"
        assert state["summary"]["fees"] > 0
        assert c.put("/api/config", json=config).status_code == 409
        assert c.post("/api/reset-paper").status_code == 409

    with client() as c:
        state = c.get("/api/state").json()
        assert state["status"]["state"] == "stopped"
        assert len(state["positions"]) == 1
        assert len(state["orders"]) == 3
        assert c.put("/api/config", json=config).status_code == 409
        flattened = c.post("/api/flatten")
        assert flattened.status_code == 200
        state = flattened.json()
        assert state["positions"] == []
        assert len(state["orders"]) == 4
        assert state["summary"]["total_trades"] == 2
        assert state["status"]["state"] == "stopped"
