import base64
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from app.provider import GrowwProvider, ProviderError


@pytest.fixture
def auth(monkeypatch, tmp_path):
    for name in ("GROWW_TOTP_TOKEN", "GROWW_TOTP_SECRET", "GROWW_ACCESS_TOKEN", "GROWW_API_KEY", "GROWW_API_SECRET"):
        monkeypatch.delenv(name, raising=False)
    calls = []

    class SDK:
        @staticmethod
        def get_access_token(**kwargs):
            calls.append(kwargs)
            return "opaque-token"

        def __init__(self, token):
            self.token = token

    monkeypatch.setitem(sys.modules, "growwapi", SimpleNamespace(GrowwAPI=SDK))
    return GrowwProvider(tmp_path), calls, SDK


def test_totp_precedence_and_concurrent_reuse(auth, monkeypatch):
    provider, calls, _ = auth
    monkeypatch.setenv("GROWW_TOTP_TOKEN", "totp-key")
    monkeypatch.setenv("GROWW_TOTP_SECRET", "JBSWY3DPEHPK3PXP")
    monkeypatch.setenv("GROWW_ACCESS_TOKEN", "old-manual-token")
    assert provider.configured()
    with ThreadPoolExecutor(max_workers=8) as pool:
        clients = list(pool.map(lambda _: provider.connect(), range(16)))
    assert all(client is clients[0] for client in clients)
    assert len(calls) == 1
    assert calls[0]["api_key"] == "totp-key"
    assert len(calls[0]["totp"]) == 6
    provider.feed_client = object()
    provider._refresh_at = 0
    assert provider.connect() is not clients[0]
    assert provider.feed_client is None
    assert len(calls) == 2


def test_manual_token_and_legacy_flow(auth, monkeypatch):
    provider, calls, _ = auth
    monkeypatch.setenv("GROWW_ACCESS_TOKEN", "manual")
    assert provider.connect().token == "manual"
    assert calls == []
    monkeypatch.delenv("GROWW_ACCESS_TOKEN")
    provider.api = None
    monkeypatch.setenv("GROWW_API_KEY", "key")
    monkeypatch.setenv("GROWW_API_SECRET", "secret")
    provider.connect()
    assert calls == [{"api_key": "key", "secret": "secret"}]


def test_expiry_and_sanitized_failure(auth, monkeypatch):
    provider, _, sdk = auth
    monkeypatch.setenv("GROWW_TOTP_TOKEN", "key")
    monkeypatch.setenv("GROWW_TOTP_SECRET", "JBSWY3DPEHPK3PXP")
    import time
    expiry = int(time.time()) + 120
    payload = base64.urlsafe_b64encode(json.dumps({"exp": expiry}).encode()).decode().rstrip("=")
    monkeypatch.setattr(sdk, "get_access_token", lambda **kwargs: f"header.{payload}.signature")
    provider.connect()
    assert provider._refresh_at <= expiry
    provider._refresh_at = 0

    def fail(**kwargs):
        raise RuntimeError("private-credential")

    monkeypatch.setattr(sdk, "get_access_token", fail)
    with pytest.raises(ProviderError) as error:
        provider.connect()
    assert error.value.code == "authentication_failed"
    assert "private-credential" not in str(error.value)
