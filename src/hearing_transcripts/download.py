"""The downloader (stub: the behavior comes test by test)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .clock import Clock


class Halt(Exception):
    """The run stopped and waits for the owner. Nothing retries around it."""


class OutsideWindow(Exception):
    """The run was started outside 00:00-06:00 Pacific."""


@dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str
    client_id: str = "4879615486"


def run_download(event_ids: list[str], config: Config, workdir: Path, clock: Clock) -> list[str]:
    raise NotImplementedError
