"""共享数据契约。金额均以泰达币计价，百分比以百分数传入。"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

INTERVALS = {"1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "4h": 14400, "1d": 86400}
SYMBOL_PATTERN = r"^[^\W_]{1,20}USDT$"


class StrategyConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["paper", "testnet", "live"] = "paper"
    market_source: Literal["demo", "binance"] = "demo"
    symbols: list[str] = Field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"], min_length=1, max_length=8)
    interval: Literal["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"] = "15m"
    leverage: int = Field(default=3, ge=1, le=20)
    margin_mode: Literal["isolated", "cross"] = "isolated"
    initial_balance: float = Field(default=10000, ge=100, le=10000000)
    order_margin: float = Field(default=100, ge=5, le=1000000)
    max_position_margin: float = Field(default=1000, ge=5, le=10000000)
    daily_loss_limit: float = Field(default=200, gt=0, le=10000000)
    stop_loss_pct: float = Field(default=2, gt=0, le=50)
    take_profit_pct: float = Field(default=4, gt=0, le=100)
    macd_fast: int = Field(default=12, ge=2, le=50)
    macd_slow: int = Field(default=26, ge=3, le=100)
    macd_signal: int = Field(default=9, ge=2, le=50)
    reverse_on_signal: bool = True
    fee_bps: float = Field(default=4, ge=0, le=100)
    slippage_bps: float = Field(default=2, ge=0, le=100)

    @model_validator(mode="after")
    def validate_relationships(self):
        if self.macd_fast >= self.macd_slow:
            raise ValueError("指标快线周期必须小于慢线周期")
        if self.order_margin > self.max_position_margin:
            raise ValueError("单笔保证金不能超过总保证金上限")
        if self.max_position_margin > self.initial_balance:
            raise ValueError("总保证金上限不能超过策略资金")
        if self.mode != "paper" and self.market_source != "binance":
            raise ValueError("测试网和实盘必须使用币安行情")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("币种不能重复")
        if any(not s.endswith("USDT") or not s.isalnum() or s != s.upper() or not 5 <= len(s) <= 24 for s in self.symbols):
            raise ValueError("请选择有效的泰达币永续合约")
        return self


class Candle(BaseModel):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int


class MarketSnapshot(BaseModel):
    symbol: str
    interval: str
    source: str
    candles: list[Candle]
    last_price: float
    change_pct: float = 0
    updated_at: int
    error: str | None = None
