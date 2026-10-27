import sys
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import pytest
from app.provider import SchwabProvider, ProviderError


def test_missing_credentials(monkeypatch, tmp_path):
    for key in ("SCHWAB_APP_KEY", "SCHWAB_APP_SECRET"):
        monkeypatch.delenv(key, raising=False)
    provider = SchwabProvider(tmp_path)
    assert not provider.configured()
    with pytest.raises(ProviderError, match="SCHWAB_APP_KEY"):
        provider.connect()


def test_concurrent_client_reuse_and_noninteractive_auth(monkeypatch, tmp_path):
    monkeypatch.setenv("SCHWAB_APP_KEY", "key")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "secret")
    monkeypatch.setenv("SCHWAB_TOKENS_DB", str(tmp_path / "tokens.db"))
    calls = []
    def client(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(tokens=SimpleNamespace(access_token="token"))
    monkeypatch.setitem(sys.modules, "schwabdev", SimpleNamespace(Client=client))
    provider = SchwabProvider(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        clients = list(pool.map(lambda _: provider.connect(), range(16)))
    assert all(c is clients[0] for c in clients) and len(calls) == 1
    assert calls[0]["open_browser_for_auth"] is False
    with pytest.raises(RuntimeError):
        calls[0]["call_on_auth"]()


def test_auth_errors_hide_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("SCHWAB_APP_KEY", "key")
    monkeypatch.setenv("SCHWAB_APP_SECRET", "secret")
    monkeypatch.setenv("SCHWAB_TOKENS_DB", str(tmp_path / "tokens.db"))
    def client(*args, **kwargs): raise RuntimeError("private-credential")
    monkeypatch.setitem(sys.modules, "schwabdev", SimpleNamespace(Client=client))
    with pytest.raises(ProviderError) as error:
        SchwabProvider(tmp_path).connect()
    assert error.value.code == "authentication_failed"
    assert "private-credential" not in str(error.value)


def test_sdk_missing_authorization_is_rejected_without_stdin(monkeypatch, tmp_path):
    monkeypatch.setenv("SCHWAB_APP_KEY", "a" * 32)
    monkeypatch.setenv("SCHWAB_APP_SECRET", "b" * 16)
    monkeypatch.setenv("SCHWAB_TOKENS_DB", str(tmp_path / "tokens.db"))
    with pytest.raises(ProviderError) as error:
        SchwabProvider(tmp_path / "cache").connect()
    assert error.value.code == "authentication_failed"
