import asyncio
from app.contracts import Instrument
from app.feed import extract_quotes
from app.service import Workspace
import pandas as pd
from app.indicators import TZ


def test_equity_and_index_payload_contracts():
    stock = Instrument(symbol="TCS", kind="stock", exchange_token="11536")
    index = Instrument(symbol="NIFTY 50", kind="index", exchange_token="NIFTY")
    payload = {
        "ltp": {"NSE": {"CASH": {"11536": {"ltp": 3500, "tsInMillis": 1720000000000}}}}
    }
    quotes = extract_quotes(payload, [stock])
    assert (
        quotes[0].price == 3500
        and quotes[0].time == 1720000000
        and quotes[0].provisional
    )
    result = extract_quotes(
        {"NSE": {"CASH": {"NIFTY": {"value": 25000, "tsInMillis": 1720000000000}}}},
        [index],
        True,
    )
    assert result[0].symbol == "NIFTY 50"
    assert not extract_quotes(
        {
            "ltp": {
                "NSE": {
                    "CASH": {
                        "11536": {"ltp": float("nan"), "tsInMillis": 1720000000000}
                    }
                }
            }
        },
        [stock],
    )


def test_publication_grace_and_session_close(tmp_path):
    workspace = Workspace(tmp_path, tmp_path / "cache")
    assert workspace.expected_slot(pd.Timestamp("2026-10-12 09:20:10", tz=TZ)) is None
    assert workspace.expected_slot(
        pd.Timestamp("2026-10-12 09:20:21", tz=TZ)
    ) == pd.Timestamp("2026-10-12 09:15", tz=TZ)
    assert workspace.expected_slot(
        pd.Timestamp("2026-10-12 16:00", tz=TZ)
    ) == pd.Timestamp("2026-10-12 15:25", tz=TZ)


def test_slow_client_is_disconnected_without_silent_snapshot_loss(tmp_path):
    async def check():
        workspace = Workspace(tmp_path, tmp_path / "cache")
        queue = asyncio.Queue(maxsize=1)
        workspace.clients.add(queue)
        await workspace.publish("status", {})
        await workspace.publish("snapshot", {})
        assert queue not in workspace.clients and await queue.get() is None

    asyncio.run(check())


def test_sdk_150_unwrapped_ltp_payload():
    instrument = Instrument(symbol="TCS", kind="stock", exchange_token="11536")
    quote = extract_quotes(
        {"NSE": {"CASH": {"11536": {"ltp": 3500, "tsInMillis": 1720000000000}}}},
        [instrument],
    )
    assert len(quote) == 1 and quote[0].symbol == "TCS"


def test_feed_worker_is_cancellable_and_reuses_sdk_client(monkeypatch):
    import sys
    import threading
    from types import SimpleNamespace
    from app.feed import FeedWorker

    created = []
    received = threading.Event()
    emitted = []

    class SDKFeed:
        def __init__(self, api):
            created.append(self)

        def subscribe_ltp(self, items, on_data_received):
            on_data_received()

        def get_ltp(self):
            return {
                "NSE": {"CASH": {"11536": {"ltp": 3500, "tsInMillis": 1720000000000}}}
            }

        def unsubscribe_ltp(self, items):
            pass

    monkeypatch.setitem(sys.modules, "growwapi", SimpleNamespace(GrowwFeed=SDKFeed))
    provider = SimpleNamespace(feed_client=None, connect=lambda: object())
    instrument = Instrument(symbol="TCS", kind="stock", exchange_token="11536")

    def emit(kind, payload):
        emitted.append((kind, payload))
        if kind == "quote":
            received.set()

    for _ in range(2):
        received.clear()
        worker = FeedWorker(provider, [instrument], emit)
        worker.start()
        assert received.wait(2)
        worker.stop()
        assert not worker.thread.is_alive()
    assert len(created) == 1
    assert all(payload["provisional"] for kind, payload in emitted if kind == "quote")
