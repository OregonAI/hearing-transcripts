"""No proxies: the environment's proxy settings must never route the downloader's traffic (ADR-0051, no evasion)."""

from __future__ import annotations

import importlib.util
import sys
import urllib.request

import pytest

from conftest import DUMMY_KEY
from hearing_transcripts import download

PROXY_VARS = ["http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "ALL_PROXY"]


@pytest.fixture
def proxy_env(monkeypatch):
    # A proxy that nothing listens on: any request that honours it cannot reach the fake.
    for var in PROXY_VARS:
        monkeypatch.setenv(var, "http://127.0.0.1:9")
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)


def test_the_opener_carries_no_proxy(proxy_env):
    opener = download.build_opener()

    # An empty ProxyHandler registers no *_open methods, so the opener simply has no proxy handler at all.
    proxy_handlers = [h for h in opener.handlers if isinstance(h, urllib.request.ProxyHandler)]
    assert [h.proxies for h in proxy_handlers] == []
    assert not any(hasattr(h, "proxy_open") for h in opener.handlers)


def _import_fresh_copy():
    """A second copy of the module, imported now, so anything it builds at import time sees the proxy variables."""
    spec = importlib.util.spec_from_file_location("hearing_transcripts._fresh_download", download.__file__)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses looks its own module up here
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def test_with_proxy_variables_set_requests_still_go_straight_to_the_fake(proxy_env, fake, clock, tmp_path):
    fresh = _import_fresh_copy()
    fetched = fresh.run_download(
        ["2026010001"],
        fresh.Config(base_url=fake.base_url, api_key=DUMMY_KEY, download_host=fake.download_host, require_https=False),
        tmp_path,
        clock,
    )

    assert fetched == ["2026010001"]
    assert fake.paths() == ["/Event/getDetailed", "/media/2026010001_audio.mp3"]
