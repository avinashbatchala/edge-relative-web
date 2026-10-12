"""Pure directional classification; never authorizes a trade."""

import math
from .contracts import ScannerRow


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def classify(current, previous):
    current, previous = number(current), number(previous)
    if current is None or previous is None:
        return "unavailable", ["RRS unavailable or warming up"]
    if current > 0 and current > previous:
        return "bullish", ["Positive and rising RRS"]
    if current < 0 and current < previous:
        return "bearish", ["Negative and falling RRS"]
    return "mixed", ["RRS does not meet a directional condition"]


def make_row(symbol, bars, features, market, request, stale=False, historical=False):
    last = features.iloc[-1]
    prior = features.iloc[-2] if len(features) > 1 else {}
    direction, reasons = classify(last.get("rrs"), prior.get("rrs"))
    values = {
        key: number(last.get(key))
        for key in ["rrs", "rrv", "sector_rrs", "sector_state"]
    }
    regime = number(market.iloc[-1].get("regime"))
    close = number(bars.iloc[-1].close)
    quality = "historical" if historical else "ready"
    if close is None:
        quality = "missing"
        direction = "unavailable"
        reasons = ["Latest aligned stock candle is missing"]
    elif direction == "unavailable":
        quality = "warmup"
    if stale:
        quality = "stale"
        direction = "unavailable"
        reasons = [
            "Stock or price benchmark has not reached the expected completed candle"
        ]
    sign = 1 if direction == "bullish" else -1 if direction == "bearish" else 0
    for enabled, value, name in [
        (request.market_filter, regime, "market"),
        (request.sector_filter, values["sector_state"], "sector"),
    ]:
        if enabled:
            if value is None or (name == "market" and value == 0):
                direction = "unavailable"
                reasons.append(f"{name.title()} filter unavailable")
            elif sign and value != sign:
                direction = "mixed"
                reasons.append(f"{name.title()} filter is not aligned")
    if request.volume_filter:
        if values["rrv"] is None:
            direction = "unavailable"
            reasons.append("Volume proxy or momentum unavailable")
        elif values["rrv"] < request.min_volume_momentum:
            direction = "mixed"
            reasons.append("Volume momentum below configured threshold")
    return ScannerRow(
        symbol=symbol,
        candle_time=int(bars.index[-1].timestamp()),
        close=close,
        previous_rrs=number(prior.get("rrs")),
        relative_volatility=number(last.get("rel_volatility")),
        market_regime=int(regime) if regime is not None else None,
        direction=direction,
        quality=quality,
        reasons=reasons,
        **values,
    )
