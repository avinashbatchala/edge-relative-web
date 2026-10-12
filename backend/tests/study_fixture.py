# Deterministic fixtures are confined to tests; never imported by the application.
from app.indicators import *


def synthetic_data(symbols=("TCS", "HDFCBANK", "SUNPHARMA")):
    rng = np.random.default_rng(42)
    days = pd.bdate_range("2026-08-03", periods=14, tz=TZ)
    idx = pd.DatetimeIndex(
        [
            t
            for day in days
            for t in pd.date_range(
                day + pd.Timedelta(hours=9, minutes=15), periods=75, freq="5min"
            )
        ]
    )
    k = np.arange(len(idx))
    driver = 0.00018 * np.sin(k / 80) + rng.normal(0, 0.00055, len(idx))

    def make(base, ret, volume=True):
        close = base * np.exp(np.cumsum(ret))
        op = np.r_[close[0] / np.exp(ret[0]), close[:-1]]
        spread = base * rng.uniform(0.0002, 0.001, len(idx))
        vol = rng.lognormal(11, 0.5, len(idx)) * (
            1 + 0.5 * np.cos((k % 75) / 75 * 2 * np.pi)
        )
        return pd.DataFrame(
            {
                "open": op,
                "high": np.maximum(op, close) + spread,
                "low": np.minimum(op, close) - spread,
                "close": close,
                "volume": vol if volume else np.nan,
            },
            index=idx,
        )

    benchmark = make(24500, driver, False)
    proxy = make(270, driver + rng.normal(0, 0.00015, len(idx)))
    stocks = {
        s: make(
            base,
            driver + rng.normal(0, 0.00065, len(idx)) + 0.00015 * np.sin(k / 60 + i),
        )
        for i, s in enumerate(symbols)
        for base in [[3200, 1700, 1650][i % 3]]
    }
    sectors = {
        SECTORS[s]: make(
            30000 + 1000 * i,
            driver + rng.normal(0, 0.0004, len(idx)) + 0.0001 * np.cos(k / 90 + i),
            False,
        )
        for i, s in enumerate(symbols)
        if s in SECTORS
    }
    didx = pd.bdate_range(end=days[-1], periods=160, tz=TZ)
    daily = pd.DataFrame(
        {"close": 24500 * np.exp(np.cumsum(rng.normal(0.0004, 0.008, len(didx))))},
        index=didx,
    )
    # Make daily closes for displayed sessions agree with synthetic intraday sessions.
    for day, group in benchmark.groupby(benchmark.index.normalize()):
        daily.loc[day, "close"] = group.close.iloc[-1]
    return stocks, benchmark, proxy, sectors, daily


def run_studies(stocks, benchmark, proxy, sectors, daily, p=PARAMS):
    validate_params(p)
    frames = {
        "market": benchmark,
        "volume_proxy": proxy,
        **{"stock:" + k: v for k, v in stocks.items()},
        **{"sector:" + k: v for k, v in sectors.items()},
    }
    aligned, report = aligned_grid(frames)
    b = aligned["market"]
    market = market_state(b, daily, p)
    results = {}
    for symbol in stocks:
        s = aligned["stock:" + symbol]
        result = oscillators(s, b, aligned["volume_proxy"], p)
        sector_name = SECTORS.get(symbol)
        if sector_name in sectors:
            result = result.join(
                sector_strength(aligned["sector:" + sector_name], b, p)
            )
        else:
            for name in ["sector_rrs", "sector_fast", "sector_slow", "sector_state"]:
                result[name] = np.nan
        results[symbol] = {
            "bars": s,
            "features": result,
            "sector": sector_name or "UNMAPPED",
        }
    return results, b, market, report
