"""Predeclared liquid-stock research universe, not index constituents or advice."""

from app.contracts import Instrument

SECTORS = {
    "NIFTY IT": ["TCS", "INFY", "HCLTECH", "WIPRO"],
    "NIFTY BANK": ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK"],
    "NIFTY PHARMA": ["SUNPHARMA", "CIPLA", "DRREDDY"],
    "NIFTY AUTO": ["MARUTI", "M&M", "BAJAJ-AUTO"],
    "NIFTY FMCG": ["HINDUNILVR", "ITC", "NESTLEIND"],
    "NIFTY METAL": ["TATASTEEL", "JSWSTEEL", "HINDALCO"],
}
COLD_STOCKS = {"HCLTECH", "AXISBANK", "DRREDDY", "MARUTI", "NESTLEIND", "HINDALCO"}
INDEX_SYMBOLS = {
    "NIFTY 50": "NSE-NIFTY",
    "NIFTY IT": "NSE-NIFTYIT",
    "NIFTY BANK": "NSE-BANKNIFTY",
    "NIFTY PHARMA": "NSE-NIFTYPHARMA",
    "NIFTY AUTO": "NSE-NIFTYAUTO",
    "NIFTY FMCG": "NSE-NIFTYFMCG",
    "NIFTY METAL": "NSE-NIFTYMETAL",
}


def instruments():
    # No exchange tokens are guessed: offline history does not require them.
    # Broker symbols are accepted only if the historical endpoint returns
    # usable candles; no instrument/live/trading endpoint is called.
    stocks = [
        Instrument(
            symbol=s,
            kind="stock",
            sector=sector,
            groww_symbol="NSE-" + s,
            session_profile="nse_cas",
        )
        for sector, names in SECTORS.items()
        for s in names
    ]
    indices = [
        Instrument(
            symbol=name, kind="index", groww_symbol=symbol, session_profile="nse_cas"
        )
        for name, symbol in INDEX_SYMBOLS.items()
    ]
    return (
        stocks
        + indices
        + [Instrument(symbol="NIFTYBEES", kind="etf", groww_symbol="NSE-NIFTYBEES")]
    )
