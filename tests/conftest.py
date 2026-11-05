from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from fake_invintus import FakeInvintus

class NetworkBlocked(RuntimeError):
    """A test tried to reach a non-loopback address."""


LOOPBACK = {"127.0.0.1", "::1"}
PROXY_VARS = ("http_proxy", "https_proxy", "all_proxy", "no_proxy")


def _guard(real):
    def guarded(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else None
        if self.family in (socket.AF_INET, socket.AF_INET6) and host not in LOOPBACK:
            raise NetworkBlocked(
                f"blocked: a test tried to connect to {address!r}; tests may connect only to 127.0.0.1 and ::1 "
                "(no request to Invintus or anything else, ever)"
            )
        return real(self, address, *args, **kwargs)

    return guarded


def _guard_lookup(real):
    def guarded(host, *args, **kwargs):
        if host not in LOOPBACK:
            raise NetworkBlocked(f"blocked: a test tried to look up {host!r}; tests may use only 127.0.0.1 and ::1")
        return real(host, *args, **kwargs)

    return guarded


@pytest.fixture(scope="session", autouse=True)
def no_network_but_loopback():
    """For the whole session: any connect to a non-loopback address raises NetworkBlocked, and proxy variables
    are removed so nothing can be routed through one."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(socket.socket, "connect", _guard(socket.socket.connect))
        mp.setattr(socket.socket, "connect_ex", _guard(socket.socket.connect_ex))
        mp.setattr(socket, "getaddrinfo", _guard_lookup(socket.getaddrinfo))
        for name in list(os.environ):
            if name.lower() in PROXY_VARS:
                mp.delenv(name)
        yield


PACIFIC = ZoneInfo("America/Los_Angeles")
DUMMY_KEY = "dummy-key-not-a-real-credential"


class FakeClock:
    """A clock tests control. `sleep` moves it forward and records the wait, so tests need no real waiting."""

    def __init__(self, start: datetime) -> None:
        self.current = start
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self.current

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.current += timedelta(seconds=seconds)


@pytest.fixture
def fake():
    server = FakeInvintus()
    server.start()
    yield server
    server.stop()


@pytest.fixture
def clock():
    # 02:00 Pacific, inside the 00:00-06:00 window.
    return FakeClock(datetime(2026, 11, 10, 2, 0, tzinfo=PACIFIC))


def fake_config(fake, **overrides):
    """A Config pointing at the local fake. The fake speaks plain http on 127.0.0.1, so the https rule is switched
    off here and only here; the command line never does that."""
    from hearing_transcripts.download import Config

    settings = {"base_url": fake.base_url, "api_key": DUMMY_KEY, "download_host": fake.download_host, "require_https": False}
    return Config(**{**settings, **overrides})
