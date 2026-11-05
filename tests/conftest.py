from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from fake_invintus import FakeInvintus

class NetworkBlocked(RuntimeError):
    """A test tried to reach a non-loopback address."""


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
