import pytest
from pydantic import ValidationError
from backend.models import StrategyConfig


@pytest.mark.parametrize("change", [
    {"macd_fast": 26}, {"leverage": 0}, {"leverage": 21},
    {"order_margin": 2000}, {"max_position_margin": 20000},
    {"mode": "live"}, {"symbols": ["BTCUSDT", "BTCUSDT"]},
    {"symbols": []}, {"stop_loss_pct": float("nan")},
    {"symbols": ["BTC/USDT"]}, {"symbols": ["USDT"]}, {"unknown_option": 1},
])
def test_invalid_config_rejected(change):
    with pytest.raises(ValidationError):
        StrategyConfig(**change)


def test_custom_contract_settings_round_trip():
    config = StrategyConfig(symbols=["SOLUSDT"], interval="1h", leverage=5, margin_mode="cross")
    assert StrategyConfig.model_validate(config.model_dump()) == config
