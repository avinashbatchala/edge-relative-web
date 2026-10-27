"""Schwab US history adapter; candle caches never contain credentials."""
import hashlib
import json
import os
import threading
import time
from pathlib import Path
import pandas as pd
from .contracts import Instrument
from .indicators import TZ, parse_candles, candle_timestamp
from .sessions import continuous_grid


class ProviderError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message
        super().__init__(message)


class SchwabProvider:
    def __init__(self, cache: Path):
        self.cache = cache
        cache.mkdir(parents=True, exist_ok=True)
        self.api = None
        self._auth_lock = threading.Lock()

    @staticmethod
    def configured():
        return bool(os.getenv("SCHWAB_APP_KEY") and os.getenv("SCHWAB_APP_SECRET"))

    def connect(self):
        with self._auth_lock:
            if self.api is not None:
                return self.api
            if not self.configured():
                raise ProviderError("credentials_missing", "Set SCHWAB_APP_KEY and SCHWAB_APP_SECRET on the backend, then run backend/auth_schwab.py.")
            try:
                from schwabdev import Client
                token_path = Path(os.getenv("SCHWAB_TOKENS_DB", "data/schwab/tokens.db")).expanduser()
                token_path.parent.mkdir(parents=True, exist_ok=True)
                def require_auth(*args, **kwargs):
                    raise RuntimeError("Interactive authorization required")
                candidate = Client(os.environ["SCHWAB_APP_KEY"], os.environ["SCHWAB_APP_SECRET"],
                    os.getenv("SCHWAB_CALLBACK_URL", "https://127.0.0.1"), tokens_db=str(token_path),
                    call_on_auth=require_auth, open_browser_for_auth=False)
                if not candidate.tokens.access_token:
                    candidate.close()
                    raise RuntimeError("Interactive authorization required")
                self.api = candidate
                return self.api
            except ImportError:
                raise ProviderError("sdk_missing", "Install backend requirements including schwabdev.") from None
            except Exception:
                raise ProviderError("authentication_failed", "Schwab authorization failed. Run backend/auth_schwab.py to authorize or renew access.") from None

    def resolve(self, catalog):
        api = self.connect()
        result = []
        try:
            for item in catalog:
                symbol = item.schwab_symbol or item.symbol
                response = api.instruments(symbol, "symbol-search")
                response.raise_for_status()
                hits = [row for row in response.json().get("instruments", []) if row.get("symbol") == symbol]
                if len(hits) != 1:
                    raise ProviderError("instrument_unresolved", f"Schwab could not resolve {symbol} exactly.")
                result.append(item.model_copy(update={"schwab_symbol": symbol}))
            return result
        except ProviderError:
            raise
        except Exception:
            raise ProviderError("instrument_fetch_failed", "Schwab instrument lookup failed.") from None

    @staticmethod
    def _history(api, instrument, start, end, interval):
        response = api.price_history(instrument.schwab_symbol or instrument.symbol,
            periodType="day" if interval == 5 else "year",
            frequencyType="minute" if interval == 5 else "daily",
            frequency=5 if interval == 5 else 1,
            startDate=start.to_pydatetime(), endDate=end.to_pydatetime(),
            needExtendedHoursData=False)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("candles"), list):
            raise ValueError("Invalid Schwab candle payload")
        return {"candles": [[r["datetime"], r["open"], r["high"], r["low"], r["close"], r.get("volume")] for r in payload["candles"]]}

    def fetch(self, instrument: Instrument, start, end, interval=5, refresh=False):
        api = self.connect()
        start = pd.Timestamp(start).tz_convert(TZ)
        end = pd.Timestamp(end).tz_convert(TZ)
        rows = []
        chunks = []
        cursor = start
        while cursor < end:
            stop = min(cursor + pd.Timedelta(days=29 if interval == 5 else 179), end)
            key = hashlib.sha256(
                f"schwab|{instrument.schwab_symbol or instrument.symbol}|{cursor}|{stop}|{interval}|{instrument.session_profile}|v4".encode()
            ).hexdigest()
            file = self.cache / f"{key}.json"
            immutable = stop.normalize() < pd.Timestamp.now(tz=TZ).normalize()
            if immutable and file.exists() and not refresh:
                try:
                    response = json.loads(file.read_text())
                except (ValueError, OSError):
                    response = None
            else:
                response = None
            if response is None:
                for attempt in range(3):
                    try:
                        response = self._history(api, instrument, cursor, stop, interval)
                        break
                    except Exception:
                        if attempt == 2:
                            raise ProviderError(
                                "history_fetch_failed",
                                f"Schwab history fetch failed for {instrument.symbol}; check authentication, entitlement and request limits.",
                            ) from None
                        time.sleep(2**attempt)
                time.sleep(0.4)
            payload = (
                response.get("payload", response) if isinstance(response, dict) else {}
            )
            if not isinstance(payload, dict) or "candles" not in payload:
                raise ProviderError(
                    "history_schema",
                    f"Schwab returned no candle payload for {instrument.symbol}.",
                )
            if immutable:
                temporary = file.with_suffix(".tmp")
                temporary.write_text(json.dumps(response))
                temporary.replace(file)
            chunks.append((file, cursor, stop, response, immutable))
            # Schwab includes the end timestamp and may return a partial boundary
            # candle. Let the next chunk own that candle rather than combining
            # incompatible endpoint observations. In-chunk duplicates still fail.
            rows.extend(
                row for row in payload["candles"]
                if interval != 5 or cursor <= candle_timestamp(row[0]) < stop
            )
            cursor = stop
        if not rows and interval != 5:
            raise ProviderError(
                "history_empty",
                f"{instrument.symbol}: Schwab returned no candles for this range.",
            )
        try:
            data = parse_candles(
                {"candles": rows},
                interval=interval,
                now=min(end, pd.Timestamp.now(tz=TZ)),
                instrument=instrument.symbol,
                session_profile=instrument.session_profile,
                allow_unusable=interval == 5,
            )
            data = data.loc[
                data.index >= (start if interval == 5 else start.normalize())
            ]
            if data.empty and interval != 5:
                raise ValueError("No data")
            if interval == 5:
                data.attrs["_cache_chunks"] = [
                    (str(file), left.isoformat(), right.isoformat())
                    for file, left, right, _, immutable in chunks
                    if immutable
                ]
                data = self.repair_gaps(instrument, data, start, end)
            return data
        except ValueError:
            raise ProviderError(
                "history_invalid",
                f"{instrument.symbol}: no usable history or conflicting/malformed candles. Verify date range and instrument.",
            ) from None

    def repair_gaps(self, instrument, data, start, end, session_dates=None):
        """Retry actual completed-session holes; never forward-fill or synthesize OHLCV.

        Dates must be observed locally or by a peer, not inferred from weekdays.
        At most two attempts per contiguous range and eight calls per instrument.
        """
        start, end = pd.Timestamp(start).tz_convert(TZ), pd.Timestamp(end).tz_convert(
            TZ
        )
        cutoff = min(end, pd.Timestamp.now(tz=TZ) - pd.Timedelta(seconds=20))
        dates = session_dates if session_dates is not None else data.index.normalize()
        grid = continuous_grid(dates, instrument, start=start, asof=cutoff)
        attrs = dict(data.attrs)
        result = data.reindex(grid).copy()
        report = dict(attrs.get("gap_recovery", {}))
        report.setdefault("requests", 0)
        report.setdefault("recovered_price_bars", 0)
        report.setdefault("recovered_volume_bars", 0)
        report.setdefault("repaired_timestamps", [])
        report.setdefault("failed_requests", 0)
        prices = ["open", "high", "low", "close"]

        def missing():
            price = result[prices].isna().any(axis=1)
            volume = (
                result.volume.isna() & ~price
                if instrument.kind != "index"
                else price & False
            )
            return price, volume

        price, volume = missing()
        holes = grid[price | volume]
        groups = []
        for stamp in holes:
            if not groups or stamp - groups[-1][-1] != pd.Timedelta(minutes=5):
                groups.append([])
            groups[-1].append(stamp)
        api = None
        for group in groups:
            for attempt in range(2):
                price, volume = missing()
                wanted = pd.DatetimeIndex(
                    [t for t in group if price.loc[t] or volume.loc[t]]
                )
                if wanted.empty or report["requests"] >= 8:
                    break
                if api is None:
                    api = self.connect()
                report["requests"] += 1
                try:
                    response = self._history(api, instrument, wanted[0], wanted[-1] + pd.Timedelta(minutes=5), 5)
                    payload = (
                        response.get("payload", response)
                        if isinstance(response, dict)
                        else {}
                    )
                    if not payload.get("candles"):
                        continue
                    recovered = parse_candles(
                        response,
                        now=cutoff,
                        instrument=instrument.symbol,
                        session_profile=instrument.session_profile,
                    )
                    for stamp in wanted.intersection(recovered.index):
                        bar = recovered.loc[stamp]
                        if bar[prices].isna().any():
                            continue
                        changed = False
                        if price.loc[stamp]:
                            result.loc[stamp, prices] = bar[prices]
                            if pd.notna(bar.volume):
                                result.loc[stamp, "volume"] = bar.volume
                            report["recovered_price_bars"] += 1
                            changed = True
                        elif (
                            volume.loc[stamp]
                            and pd.notna(bar.volume)
                            and bar[prices].equals(result.loc[stamp, prices])
                        ):
                            result.loc[stamp, "volume"] = bar.volume
                            report["recovered_volume_bars"] += 1
                            changed = True
                        if (
                            changed
                            and stamp.isoformat() not in report["repaired_timestamps"]
                        ):
                            report["repaired_timestamps"].append(stamp.isoformat())
                except Exception:
                    # Broker failures can contain tokens; diagnostics never retain exceptions.
                    report["failed_requests"] += 1
                finally:
                    time.sleep(0.4)
        price, volume = missing()
        report["remaining_price_gaps"] = int(price.sum())
        report["remaining_volume_gaps"] = int(volume.sum())
        report["unresolved_timestamps"] = [t.isoformat() for t in grid[price | volume]]
        report["request_budget"] = 8
        result.attrs = {**attrs, "gap_recovery": report}
        self._persist_repairs(result)
        return result

    def _persist_repairs(self, data):
        # Preserve raw broker rows (including excluded auction rows); replace only
        # timestamps repaired from a validated response, even on the peer-date pass.
        repaired = set(data.attrs["gap_recovery"]["repaired_timestamps"])
        if not repaired:
            return
        for path, left, right in data.attrs.get("_cache_chunks", []):
            file = Path(path)
            selected = data.loc[
                (data.index >= pd.Timestamp(left)) & (data.index < pd.Timestamp(right))
            ]
            updates = {
                stamp.isoformat(): [
                    stamp.isoformat(),
                    *[None if pd.isna(v) else float(v) for v in bar],
                ]
                for stamp, bar in selected.iterrows()
                if stamp.isoformat() in repaired
            }
            if not updates:
                continue
            try:
                response = json.loads(file.read_text())
                payload = response.get("payload", response)
                original = [
                    row
                    for row in payload["candles"]
                    if candle_timestamp(row[0]).isoformat() not in updates
                ]
                payload["candles"] = original + list(updates.values())
                temporary = file.with_suffix(".tmp")
                temporary.write_text(json.dumps(response))
                temporary.replace(file)
            except (ValueError, OSError, KeyError, IndexError, TypeError):
                # A cache write failure must not discard verified in-memory prices.
                data.attrs["gap_recovery"]["cache_write_failed"] = True
