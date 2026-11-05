"""The time seam: anything that reads the time or waits takes a clock, so tests inject their own."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    def monotonic(self) -> float:
        """Seconds on a clock that never steps; pacing uses this, the window uses `now`."""
        ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
