"""以简单均值预热的指数平滑指标；每个结果只读取其之前的收盘价。"""
from backend.models import Candle


def _ema(values: list[float | None], period: int) -> list[float | None]:
    result = []
    seed = []
    current = None
    alpha = 2 / (period + 1)
    for value in values:
        if value is None:
            result.append(None)
            continue
        if current is None:
            seed.append(value)
            if len(seed) == period:
                current = sum(seed) / period
        else:
            current += alpha * (value - current)
        result.append(current)
    return result


def calculate_macd(candles: list[Candle], fast: int, slow: int, signal: int) -> list[dict]:
    if not 1 <= fast < slow or signal < 1:
        raise ValueError('指标周期不合法')
    closes = [c.close for c in candles]
    fast_line, slow_line = _ema(closes, fast), _ema(closes, slow)
    differences = [None if a is None or b is None else a-b for a, b in zip(fast_line, slow_line)]
    signal_line = _ema(differences, signal)
    return [{'time': candle.time, 'macd': difference, 'signal': average,
             'histogram': None if difference is None or average is None else difference-average}
            for candle, difference, average in zip(candles, differences, signal_line)]


def signal_direction(previous: dict, current: dict) -> str | None:
    before, after = previous['histogram'], current['histogram']
    if before is None or after is None:
        return None
    if before <= 0 < after:
        return 'long'
    if before >= 0 > after:
        return 'short'
    return None
