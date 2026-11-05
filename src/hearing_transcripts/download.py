"""The downloader. Its rules are code, not convention (SessionGateway ADR-0051):

- one request at a time, about 3 s apart, only inside 00:00-06:00 Pacific;
- each event fetched once (the record file `fetched.jsonl` in the working folder);
- MP3 only, never MP4;
- the exact User-Agent below on every request;
- the first 401, 403, 429 or any unexpected reply halts the run, with no retry.
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .clock import Clock

USER_AGENT = "SessionGateway-transcripts/1 (+https://github.com/OregonAI/SessionGateway)"
RECORD_FILE = "fetched.jsonl"
TIMEOUT_SECONDS = 120
PACE_SECONDS = 3.0
PACIFIC = ZoneInfo("America/Los_Angeles")
WINDOW_START_HOUR = 0  # 00:00 Pacific, inclusive
WINDOW_END_HOUR = 6  # 06:00 Pacific, exclusive


class Halt(Exception):
    """The run stopped and waits for the owner. Nothing retries around it."""


class OutsideWindow(Exception):
    """The run was started outside 00:00-06:00 Pacific."""


@dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str
    client_id: str = "4879615486"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # a redirect is an unexpected reply, not something to follow
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _check_window(clock: Clock) -> None:
    hour = clock.now().astimezone(PACIFIC).hour
    if not WINDOW_START_HOUR <= hour < WINDOW_END_HOUR:
        raise OutsideWindow("the downloader runs only between 00:00 and 06:00 Pacific; refusing to continue")


class _Pacer:
    """Keeps requests about PACE_SECONDS apart and inside the window. Called before every request."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.last: datetime | None = None

    def before_request(self) -> None:
        if self.last is not None:
            wait = PACE_SECONDS - (self.clock.now() - self.last).total_seconds()
            if wait > 0:
                self.clock.sleep(wait)
        _check_window(self.clock)  # after the wait, so a run never sends a request outside the window

    def after_request(self) -> None:
        self.last = self.clock.now()


def _request(req: urllib.request.Request, what: str, pacer: _Pacer) -> tuple[int, bytes]:
    """One request. Any answer that is not a 200 halts; there is no retry."""
    pacer.before_request()
    req.add_header("User-Agent", USER_AGENT)
    try:
        try:
            with _opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
                status, body = resp.status, resp.read()
        finally:
            pacer.after_request()
    except urllib.error.HTTPError as err:
        raise Halt(f"{what}: the server answered {err.code}; halting, no retry") from None
    except (urllib.error.URLError, TimeoutError, OSError) as err:
        raise Halt(f"{what}: no usable answer ({err}); halting, no retry") from None
    if status != 200:
        raise Halt(f"{what}: the server answered {status}; halting, no retry")
    return status, body


def _audio_url(event_id: str, config: Config, pacer: _Pacer) -> str:
    payload = {
        "clientID": config.client_id,
        "eventID": event_id,
        "showDownloadLinks": True,
    }
    req = urllib.request.Request(
        f"{config.base_url.rstrip('/')}/Event/getDetailed",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": "embedder",
            "wsc-api-key": config.api_key,
        },
    )
    _, body = _request(req, f"event {event_id} getDetailed", pacer)
    try:
        url = json.loads(body)["data"]["downloadLinks"]["audioDownloadURI"]
    except (ValueError, KeyError, TypeError):
        raise Halt(f"event {event_id} getDetailed: unexpected body; halting, no retry") from None
    if not isinstance(url, str) or not url:
        raise Halt(f"event {event_id} getDetailed: no audio address in the reply; halting, no retry")
    if not urlsplit(url).path.lower().endswith(".mp3"):
        raise Halt(f"event {event_id}: the audio address is not an MP3; halting, nothing requested")
    return url


def _fetched_ids(record: Path) -> set[str]:
    if not record.exists():
        return set()
    return {json.loads(line)["event_id"] for line in record.read_text().splitlines() if line.strip()}


def run_download(event_ids: list[str], config: Config, workdir: Path, clock: Clock) -> list[str]:
    """Fetch each event's MP3 once. Returns the ids fetched in this run."""
    _check_window(clock)  # refuse to start outside the window
    pacer = _Pacer(clock)
    workdir.mkdir(parents=True, exist_ok=True)
    record = workdir / RECORD_FILE
    done = _fetched_ids(record)
    fetched: list[str] = []
    for event_id in event_ids:
        if event_id in done:
            continue
        url = _audio_url(event_id, config, pacer)
        _, audio = _request(urllib.request.Request(url, method="GET"), f"event {event_id} MP3", pacer)
        (workdir / f"{event_id}.mp3").write_bytes(audio)
        entry = {"event_id": event_id, "sha256": hashlib.sha256(audio).hexdigest(), "bytes": len(audio)}
        with record.open("a") as fh:
            fh.write(json.dumps(entry) + "\n")
        done.add(event_id)
        fetched.append(event_id)
    return fetched
