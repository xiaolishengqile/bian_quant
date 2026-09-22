# 并行实施共享接口

所有 Python（编程语言）模块导入 `backend.models`。时间戳统一毫秒。配置字段名使用模型定义的下划线命名。

## 行情与交易适配（backend/exchange.py，backend/market.py）
- `MarketService()`；`async get_market(config: StrategyConfig, symbol: str, limit: int = 300) -> MarketSnapshot`；`async get_symbols(*, testnet: bool = False) -> list[dict]`，元素 `{symbol, base_asset, quote_asset}`。测试网与实盘分别拉取并缓存合约列表，行情须通过周期和连续性检查。
- `BinanceBroker(config: StrategyConfig)`；`async preflight() -> dict`，返回 `{wallet_balance, available_balance, positions: list[dict]}`，无凭据/双向持仓/多资产保证金/外部持仓或挂单须拒绝启动（首次启动不接管已有真实仓位）。
- `async get_account() -> dict` 返回 `{wallet_balance, available_balance}`，分别为钱包余额与可用余额。
- `async open_position(symbol: str, side: str, margin: float, price: float, client_id: str) -> dict`；side 为 long/short。返回 `{quantity, price, fee, order_id}`，只有确认全部成交才返回。实盘交易所数量精度/最小名义金额校验，返回实际价格与数量。
- `async close_position(symbol: str, side: str, quantity: float, client_id: str) -> dict`；返回同上，必须 reduceOnly（仅减仓），成交后确认空仓。
- `async get_positions() -> list[dict]`，`async cancel_orders() -> None`（仅本程序订单，非账户全部）。
- 异常为 `RuntimeError` 或其子类，中文安全错误，不返回密钥/签名。明确发生在发送订单之前的校验失败使用 `OrderNotSentError`，允许用户修正参数后重启；未知成交错误必须保留未决意图并阻止引擎继续开仓，不能自动重发订单。
- `connection_status() -> dict` 同步函数，返回 `{testnet_configured, live_configured, live_enabled}`，仅取环境变量：BINANCE_TESTNET_API_KEY、BINANCE_TESTNET_API_SECRET、BINANCE_API_KEY、BINANCE_API_SECRET、ENABLE_LIVE_TRADING。

## 引擎（backend/engine.py、indicators.py、backtest.py、storage.py）
- `TradingEngine(db_path: str, market: MarketService)`
- `engine.config: StrategyConfig`，`async snapshot() -> dict`（字段如下）
- `async save_config(config)`；`async start()`；`async stop()`；`async flatten(symbol: str | None = None)`；`async tick()`；`async reset_paper()`；`engine.close()`。
- 单进程事件循环，方法使用异步锁；持久化配置、运行状态、订单意图、交易和仓位；自动循环由接口宿主调用 tick，每 5 秒一次。
- `calculate_macd(candles: list[Candle], fast: int, slow: int, signal: int) -> list[dict]`，元素 `{time, macd, signal, histogram}`，指标未预热的值用 None。
- `run_backtest(candles: list[Candle], config: StrategyConfig, symbol: str) -> dict`，返回 `{symbol, bars, start_time, end_time, initial_balance, final_equity, return_pct, max_drawdown_pct, total_trades, win_rate, fees, trades: list, equity_curve: [{time,equity}], assumptions: list[str]}`。

## 网页接口（由主代理实现）
- `GET /api/state` -> `{config, status, summary, positions, orders, logs, connections}`。
- status `{state: stopped|running|error|risk_stopped, last_tick, last_error, started_at}`。
- summary `{initial_balance, wallet_balance, equity, unrealized_pnl, realized_pnl, fees, total_trades, win_rate, exposure, daily_pnl, account_synced, available_balance}`。真实账户未同步时可用余额为 null，界面不展示初始模拟资金为真实余额。
- positions `[{symbol, side: long|short, quantity, entry_price, mark_price, leverage, margin, unrealized_pnl, stop_loss, take_profit, opened_at}]`。
- orders `[{id, timestamp, symbol, side, action: open|close, quantity, price, fee, realized_pnl, reason, mode, status}]`。
- logs `[{id, timestamp, level: info|warning|error, message}]`。
- connections `{testnet_configured, live_configured, live_enabled}`。
- `GET /api/market?symbol=BTCUSDT&interval=15m` -> MarketSnapshot 全部字段加 `indicators`（指标结果），不会静默退回演示行情。
- `GET /api/symbols` -> `{symbols:[{symbol,base_asset,quote_asset}],source: binance|demo,error?:string}`。
- `PUT /api/config` JSON 为完整 StrategyConfig -> 新 state。
- `POST /api/start`、`POST /api/stop`、`POST /api/flatten`（可选正文 `{symbol}`）、`POST /api/reset-paper` -> 新 state。
- `POST /api/backtest` JSON `{symbol, interval?}` -> 回测结果，使用当前已保存配置、最多 1000 根行情。
- 错误 HTTP 400/409/503 `{detail: 中文说明}`。
- 登录：`GET /api/auth` -> `{required, authenticated}`；`POST /api/login` 正文 `{password}`，成功设置 HttpOnly（脚本不可读）会话 Cookie（浏览器凭据）；`POST /api/logout`。
- 本机默认无口令；公网监听强制配置 CONSOLE_PASSWORD。接口同源防护。实盘 API（程序接口）需要口令和部署开关。

## 界面
全中文。英文缩写如 MACD 下方附中文名称。币种代码下方标注中文或“泰达币永续”。模式、行情来源和资金单位始终清楚。默认停止、无持仓、无成交，不伪造收益。
