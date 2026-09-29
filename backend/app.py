"""控制台接口宿主；交易循环独立于浏览器连接。"""
import asyncio
import contextlib
import hmac
import ipaddress
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.models import SYMBOL_PATTERN, StrategyConfig
from backend.security import install_security
from backend.instance_lock import InstanceLock

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)


class SymbolRequest(BaseModel):
    symbol: str | None = Field(default=None, pattern=SYMBOL_PATTERN)


class BacktestRequest(BaseModel):
    symbol: str = Field(pattern=SYMBOL_PATTERN)
    interval: Literal["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"] | None = None


def create_app(db_path=None, password=None, market=None, background=True, allowed_hosts=None):
    from backend.engine import TradingEngine
    from backend.exchange import connection_status
    from backend.market import MarketService
    from backend.indicators import calculate_macd
    from backend.backtest import run_backtest

    password = os.getenv("CONSOLE_PASSWORD", "") if password is None else password
    market = market or MarketService()
    database_path = str(db_path or os.getenv("QUANT_DB_PATH", ROOT / "data" / "quant.db"))
    engine = None
    instance_lock = InstanceLock(database_path + ".lock")
    cycle_error = None

    async def worker():
        nonlocal cycle_error
        while True:
            try:
                await engine.tick()
                cycle_error = None
            except asyncio.CancelledError:
                raise
            except Exception:
                cycle_error = "后台轮询暂未完成，请检查运行日志与行情连接"
                logger.error(cycle_error)
            await asyncio.sleep(5)

    @asynccontextmanager
    async def lifespan(app):
        nonlocal engine
        instance_lock.acquire()
        task = None
        try:
            engine = TradingEngine(database_path, market)
            app.state.engine = engine
            if engine.config.mode == "live" and len(password) < 12:
                raise RuntimeError("已保存的实盘账户须配置至少十二位控制台口令，后台尚未启动")
            task = asyncio.create_task(worker()) if background else None
            yield
        finally:
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if engine is not None:
                engine.close()
            instance_lock.release()
            if hasattr(market, "close"):
                result = market.close()
                if asyncio.iscoroutine(result):
                    await result

    app = FastAPI(title="合约量化工作台", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    hosts = allowed_hosts or ["localhost", "127.0.0.1", "[::1]"] + [h.strip() for h in os.getenv("CONSOLE_ALLOWED_HOSTS", "").split(",") if h.strip()]
    install_security(app, password, hosts)

    @app.exception_handler(RuntimeError)
    async def runtime_error(request: Request, exc: RuntimeError):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def value_error(request: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    async def snapshot():
        state = await engine.snapshot()
        state["connections"] = connection_status(engine.credentials)
        if cycle_error:
            state["status"]["last_error"] = cycle_error
        return state

    @app.get("/api/state")
    async def state():
        return await snapshot()

    async def credential_input(request: Request) -> dict:
        if len(password) < 12:
            raise HTTPException(409, "请先在服务器设置至少十二位控制台口令并重启")
        try:
            host = request.url.hostname or ""
            local_host = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local_host = host == "localhost"
        if not local_host and urlsplit(request.headers.get("origin", "")).scheme != "https":
            raise HTTPException(403, "远程配置交易密钥须通过加密网页访问")
        if len(await request.body()) > 2048:
            raise HTTPException(400, "交易密钥输入过长")
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(400, "请输入有效的配置") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("password"), str) or not hmac.compare_digest(payload["password"], password):
            raise HTTPException(403, "控制台口令不正确")
        return payload

    def ensure_credentials_editable():
        if engine.data["status"]["state"] == "running" or engine.data["positions"] or engine.storage.unresolved():
            raise HTTPException(409, "请先停止策略、确认空仓并处理未知订单，再修改交易密钥")

    @app.put("/api/credentials/{mode}")
    async def save_credentials(mode: Literal["testnet", "live"], request: Request):
        payload = await credential_input(request)
        key, secret = payload.get("key"), payload.get("secret")
        if (not isinstance(key, str) or not isinstance(secret, str) or
                not all(1 <= len(value) <= 512 and not any(char.isspace() or ord(char) < 32 for char in value)
                        for value in (key, secret))):
            raise HTTPException(400, "请填写有效的接口标识和签名密钥")
        async with engine.lock:
            ensure_credentials_editable()
            engine.credentials.save(mode, key, secret)
            engine._log(f'{"实盘" if mode == "live" else "测试网"}交易密钥已更新')
        return await snapshot()

    @app.delete("/api/credentials/{mode}")
    async def remove_credentials(mode: Literal["testnet", "live"], request: Request):
        await credential_input(request)
        async with engine.lock:
            ensure_credentials_editable()
            engine.credentials.remove(mode)
            engine._log(f'{"实盘" if mode == "live" else "测试网"}网页交易密钥已移除')
        return await snapshot()

    @app.put("/api/config")
    async def save_config(config: StrategyConfig):
        if config.mode == "live" and len(password) < 12:
            raise HTTPException(409, "选择实盘前，请先在服务器设置至少十二位控制台口令并重启服务")
        await engine.save_config(config)
        return await snapshot()

    @app.post("/api/start")
    async def start():
        if engine.config.mode == "live":
            if os.getenv("ENABLE_LIVE_TRADING", "").lower() != "true":
                raise HTTPException(409, "实盘尚未开启，请在服务器配置实盘开关")
            if len(password) < 12:
                raise HTTPException(409, "实盘须先设置至少十二位控制台口令")
        await engine.start()
        return await snapshot()

    @app.post("/api/stop")
    async def stop():
        await engine.stop()
        return await snapshot()

    @app.post("/api/flatten")
    async def flatten(payload: SymbolRequest | None = None):
        await engine.flatten(payload.symbol if payload else None)
        return await snapshot()

    @app.post("/api/reset-paper")
    async def reset_paper():
        await engine.reset_paper()
        return await snapshot()

    @app.get("/api/market")
    async def get_market(
        symbol: str = Query(default="BTCUSDT", pattern=SYMBOL_PATTERN),
        interval: Literal["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"] | None = None,
    ):
        config = engine.config.model_copy(update={"interval": interval or engine.config.interval})
        data = await market.get_market(config, symbol, 300)
        return {**data.model_dump(), "indicators": calculate_macd(data.candles, config.macd_fast, config.macd_slow, config.macd_signal)}

    @app.get("/api/symbols")
    async def symbols():
        if engine.config.market_source == "demo":
            assets = [("BTC", "比特币"), ("ETH", "以太坊"), ("SOL", "索拉纳"), ("BNB", "币安币"), ("XRP", "瑞波币"), ("DOGE", "狗狗币")]
            return {"symbols": [{"symbol": f"{symbol}USDT", "base_asset": symbol, "quote_asset": "USDT", "name": name} for symbol, name in assets], "source": "demo"}
        return {"symbols": await market.get_symbols(testnet=engine.config.mode == "testnet"), "source": "binance"}

    backtest_lock = asyncio.Lock()

    @app.post("/api/backtest")
    async def backtest(payload: BacktestRequest):
        if backtest_lock.locked():
            raise HTTPException(409, "已有回测正在运行，请稍候")
        async with backtest_lock:
            config = engine.config.model_copy(update={"interval": payload.interval or engine.config.interval})
            data = await market.get_market(config, payload.symbol, 1000)
            # 数据源毫秒时间戳；尚未收盘的蜡烛不能用于历史回测。
            import time
            now = int(time.time() * 1000)
            candles = [c for c in data.candles if c.close_time < now]
            result = await asyncio.to_thread(run_backtest, candles, config, payload.symbol)
            result["source"] = data.source
            return result

    dist = ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/", StaticFiles(directory=dist, html=True), name="console")
    else:
        @app.get("/")
        async def missing_build():
            return JSONResponse({"detail": "前端尚未构建，请在前端目录运行构建命令后重启服务"}, status_code=503)
    return app
