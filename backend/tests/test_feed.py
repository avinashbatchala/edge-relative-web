import threading
from types import SimpleNamespace
import pandas as pd
from app.contracts import Instrument
from app.feed import extract_quotes, FeedWorker
from app.service import Workspace
from app.indicators import TZ


def test_schwab_quotes_and_invalid_values():
    item = Instrument(symbol="AAPL", kind="stock")
    payload = {"AAPL": {"quote": {"lastPrice": 200, "tradeTime": 1720000000000}}}
    quote = extract_quotes(payload, [item])[0]
    assert quote.price == 200 and quote.time == 1720000000 and quote.provisional
    payload["AAPL"]["quote"]["lastPrice"] = float("nan")
    assert extract_quotes(payload, [item]) == []
    assert extract_quotes({}, [item]) == []


def test_publication_grace_and_session_close(tmp_path):
    w = Workspace(tmp_path, tmp_path / "cache")
    assert w.expected_slot(pd.Timestamp("2026-10-12 09:35:10", tz=TZ)) is None
    assert w.expected_slot(pd.Timestamp("2026-10-12 09:35:21", tz=TZ)) == pd.Timestamp("2026-10-12 09:30", tz=TZ)
    assert w.expected_slot(pd.Timestamp("2026-10-12 16:01", tz=TZ)) == pd.Timestamp("2026-10-12 15:55", tz=TZ)


def test_worker_emits_and_stops():
    received = threading.Event()
    class Response:
        def raise_for_status(self): pass
        def json(self): return {"AAPL": {"quote": {"lastPrice": 200, "tradeTime": 1720000000000}}}
    api = SimpleNamespace(quotes=lambda symbols: Response())
    worker = FeedWorker(SimpleNamespace(connect=lambda: api), [Instrument(symbol="AAPL", kind="stock")], lambda kind, payload: received.set() if kind == "quote" else None)
    worker.start()
    assert received.wait(2)
    worker.stop()
    assert not worker.thread.is_alive()
