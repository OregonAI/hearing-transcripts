"""The downloader. Its rules are code, not convention (SessionGateway ADR-0051):

- one request at a time, about 3 s apart, only inside 00:00-06:00 Pacific;
- each event fetched once (the record file `fetched.jsonl` in the working folder);
- MP3 only, never MP4;
- the exact User-Agent below on every request;
- the first 401, 403, 429 or any unexpected reply halts the run, with no retry.
"""

from __future__ import annotations

import hashlib
import http.client
import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from typing import TypeVar
from zoneinfo import ZoneInfo

from .clock import Clock

T = TypeVar("T")

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


def build_opener() -> urllib.request.OpenerDirector:
    """No proxies (ADR-0051, no evasion): an empty ProxyHandler stops urllib reading http(s)_proxy from the
    environment, and redirects are never followed."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect)


_opener = build_opener()


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


def _open(req: urllib.request.Request, what: str, pacer: _Pacer, read: Callable[[http.client.HTTPResponse], T]) -> T:
    """One request. Any answer that is not a 200 halts; there is no retry. `read` consumes the reply."""
    pacer.before_request()
    req.add_header("User-Agent", USER_AGENT)
    try:
        try:
            with _opener.open(req, timeout=TIMEOUT_SECONDS) as resp:
                if resp.status != 200:
                    raise Halt(f"{what}: the server answered {resp.status}; halting, no retry")
                return read(resp)
        finally:
            pacer.after_request()
    except urllib.error.HTTPError as err:
        raise Halt(f"{what}: the server answered {err.code}; halting, no retry") from None
    except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException) as err:
        raise Halt(f"{what}: no usable answer ({err!r}); halting, no retry") from None


def _is_mp3_start(head: bytes) -> bool:
    """An ID3v2 tag, or an MPEG audio frame sync (eleven set bits)."""
    return head[:3] == b"ID3" or (len(head) >= 2 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0)


def _save_mp3(resp: http.client.HTTPResponse, what: str, part: Path) -> tuple[str, int]:
    """Check the reply and write it to `part`, synced. Returns (sha256, bytes). Halts on anything but a whole MP3."""
    ctype = resp.headers.get_content_type()
    if not ctype.startswith("audio/"):
        raise Halt(f"{what}: the reply is {ctype!r}, not audio; halting, no retry")
    length = resp.headers.get("Content-Length", "").strip()
    if not length.isdigit():
        raise Halt(f"{what}: the reply has no usable Content-Length; halting, no retry")
    digest, size, first = hashlib.sha256(), 0, True
    with part.open("wb") as fh:
        while chunk := resp.read(1 << 20):
            if first:
                if not _is_mp3_start(chunk):
                    raise Halt(f"{what}: the body does not start like an MP3; halting, no retry")
                first = False
            fh.write(chunk)
            digest.update(chunk)
            size += len(chunk)
        if size == 0:
            raise Halt(f"{what}: the body is empty; halting, no retry")
        if size != int(length):
            raise Halt(f"{what}: got {size} bytes but Content-Length said {length}; halting, no retry")
        fh.flush()
        os.fsync(fh.fileno())
    return digest.hexdigest(), size


def _request(req: urllib.request.Request, what: str, pacer: _Pacer) -> tuple[int, bytes]:
    def read(resp: http.client.HTTPResponse) -> tuple[int, bytes]:
        return resp.status, resp.read()

    return _open(req, what, pacer, read)


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
        what = f"event {event_id} MP3"
        part, final = workdir / f"{event_id}.mp3.part", workdir / f"{event_id}.mp3"
        try:
            sha256, size = _open(urllib.request.Request(url, method="GET"), what, pacer, lambda r: _save_mp3(r, what, part))
            os.replace(part, final)  # the file is whole and synced; only now is it kept
        except BaseException:
            part.unlink(missing_ok=True)
            raise
        entry = {"event_id": event_id, "sha256": sha256, "bytes": size}
        with record.open("a") as fh:  # recorded only after the file is complete
            fh.write(json.dumps(entry) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        done.add(event_id)
        fetched.append(event_id)
    return fetched
