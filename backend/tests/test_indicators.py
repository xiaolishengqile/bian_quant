import pytest

from backend.indicators import calculate_macd
from backend.models import Candle


def candles(values):
    return [Candle(time=i*60000, close_time=(i+1)*60000-1, open=v, high=v, low=v, close=v, volume=1) for i, v in enumerate(values)]


def test_macd_requires_warmup_and_detects_first_golden_cross():
    result = calculate_macd(candles([100, 99, 98, 97, 98]), 2, 3, 2)
    assert [r['histogram'] for r in result[:3]] == [None, None, None]
    assert result[3]['histogram'] == pytest.approx(0)
    assert result[4]['histogram'] == pytest.approx(1 / 9)


def test_future_candles_do_not_change_prior_indicators():
    prior = calculate_macd(candles([100, 99, 98, 97, 98]), 2, 3, 2)
    extended = calculate_macd(candles([100, 99, 98, 97, 98, 10000]), 2, 3, 2)
    assert prior == extended[:5]
