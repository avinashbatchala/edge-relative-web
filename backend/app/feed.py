"""Blocking SDK worker emits only provisional price observations."""

import math
import threading
import time
from datetime import datetime, timezone
from .contracts import Quote


def extract_quotes(payload, instruments, index=False):
    quotes = []
    for item in instruments:
        row = payload.get(item.schwab_symbol or item.symbol, {}).get("quote", {})
        try:
            price = float(row["lastPrice"])
            timestamp = float(row["tradeTime"]) / 1000
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
        self.thread = threading.Thread(target=self.run, name="schwab-feed", daemon=True)
        self.thread.start()

    def run(self):
        while not self.stop_event.is_set():
            try:
                response = self.provider.connect().quotes([i.schwab_symbol or i.symbol for i in self.instruments])
                response.raise_for_status()
                quotes = extract_quotes(response.json(), self.instruments)
                for quote in quotes:
                    signature = (quote.time, quote.price)
                    if self.last_quotes.get(quote.symbol) == signature:
                        continue
                    self.last_quotes[quote.symbol] = signature
                    self.last_seen = time.monotonic()
                    self.emit("quote", quote.model_dump())
                self.state = "connected" if self.last_seen and time.monotonic() - self.last_seen < 60 else "stale"
            except Exception:
                self.state = "disconnected"
            if self.state != getattr(self, "_published_state", None):
                self.emit("feed_status", {"state": self.state})
                self._published_state = self.state
            self.stop_event.wait(5)

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=0.5)
