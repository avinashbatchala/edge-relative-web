"""Opt-in Schwab history smoke check. Requires prior interactive authorization."""
from pathlib import Path
from dotenv import load_dotenv
import pandas as pd
from app.contracts import Instrument
from app.indicators import TZ
from app.provider import SchwabProvider

if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    provider = SchwabProvider(Path("data/candles"))
    end = pd.Timestamp.now(tz=TZ)
    for symbol in ("AAPL", "MSFT", "NVDA"):
        data = provider.fetch(Instrument(symbol=symbol, kind="stock"), end - pd.Timedelta(days=7), end)
        print(symbol, len(data), data.attrs.get("gap_recovery", {}))
