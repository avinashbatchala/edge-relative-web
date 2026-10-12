"""Blocking SDK worker emits only provisional price observations."""

import math
import threading
import time
from datetime import datetime, timezone
from .contracts import Quote


def extract_quotes(payload, instruments, index=False):
    tree = payload.get("index_value", payload) if index else payload.get("ltp", payload)
    quotes = []
    for item in instruments:
        row = (
            tree.get(item.exchange, {})
            .get(item.segment, {})
            .get(item.exchange_token, {})
        )
        try:
            price = float(row["value" if index else "ltp"])
            timestamp = float(row["tsInMillis"]) / 1000
            if (
                math.isfinite(price)
                and price > 0
                and math.isfinite(timestamp)
                and timestamp > 0
            ):
                quotes.append(
                    Quote(symbol=item.symbol, price=price, time=int(timestamp))
                )
        except (KeyError, TypeError, ValueError):
            continue
    return quotes


class FeedWorker:
    def __init__(self, provider, instruments, emit):
        self.provider = provider
        self.instruments = instruments
        self.emit = emit
        self.stop_event = threading.Event()
        self.thread = None
        self.feed = None
        self.last_seen = 0.0
        self.last_quotes = {}
        self.state = "disabled"

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self.run, name="groww-feed", daemon=True)
        self.thread.start()

    def run(self):
        equities = [item for item in self.instruments if item.kind != "index"]
        indices = [item for item in self.instruments if item.kind == "index"]
        fields = lambda items: [
            {
                "exchange": i.exchange,
                "segment": i.segment,
                "exchange_token": i.exchange_token,
            }
            for i in items
        ]
        while not self.stop_event.is_set():
            try:
                from growwapi import GrowwFeed

                self.state = "connecting"
                self.emit("feed_status", {"state": self.state})
                if self.provider.feed_client is None:
                    self.provider.feed_client = GrowwFeed(self.provider.connect())
                self.feed = self.provider.feed_client

                def receive(index=False):
                    if self.stop_event.is_set():
                        return
                    payload = (
                        self.feed.get_index_value() if index else self.feed.get_ltp()
                    )
                    for quote in extract_quotes(
                        payload, indices if index else equities, index
                    ):
                        signature = (quote.time, quote.price)
                        if self.last_quotes.get(quote.symbol) == signature:
                            continue
                        self.last_quotes[quote.symbol] = signature
                        self.last_seen = time.monotonic()
                        if self.state != "connected":
                            self.state = "connected"
                            self.emit("feed_status", {"state": self.state})
                        self.emit("quote", quote.model_dump())

                if equities:
                    self.feed.subscribe_ltp(
                        fields(equities), on_data_received=lambda *args: receive()
                    )
                if indices:
                    self.feed.subscribe_index_value(
                        fields(indices), on_data_received=lambda *args: receive(True)
                    )
                # SDK 1.5 starts its own daemon socket thread during construction.
                # Keep our lifecycle monitor cancellable instead of joining consume().
                while not self.stop_event.wait(1):
                    if (
                        self.state == "connected"
                        and time.monotonic() - self.last_seen > 60
                    ):
                        self.state = "stale"
                        self.emit("feed_status", {"state": self.state})
            except Exception:
                # SDK exception text can include credentials: publish fixed text only.
                self.state = "disconnected"
                self.emit("feed_status", {"state": self.state})
            finally:
                if self.feed:
                    try:
                        if equities:
                            self.feed.unsubscribe_ltp(fields(equities))
                        if indices:
                            self.feed.unsubscribe_index_value(fields(indices))
                    except Exception:
                        pass
            self.stop_event.wait(5)

    def stop(self):
        self.stop_event.set()
        if self.feed:
            try:
                equities = [i for i in self.instruments if i.kind != "index"]
                indices = [i for i in self.instruments if i.kind == "index"]
                fields = lambda items: [
                    {
                        "exchange": i.exchange,
                        "segment": i.segment,
                        "exchange_token": i.exchange_token,
                    }
                    for i in items
                ]
                if equities:
                    self.feed.unsubscribe_ltp(fields(equities))
                if indices:
                    self.feed.unsubscribe_index_value(fields(indices))
            except Exception:
                pass
        # The monitor is cancellable; the SDK owns its daemon socket thread.
        if self.thread:
            self.thread.join(timeout=0.5)
