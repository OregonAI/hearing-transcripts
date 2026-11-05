"""A local fake of the two Invintus endpoints the downloader uses. Tests never contact the real service.

It mimics the documented `Event/getDetailed` response (`data.downloadLinks.audioDownloadURI`) and serves an MP3
endpoint. It records every request so tests can check what was asked for, and each event can be given a canned
response to play out a refusal or an odd reply.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class Seen:
    method: str
    path: str
    headers: dict[str, str]
    body: bytes


def audio_bytes(event_id: str) -> bytes:
    return b"ID3-fake-mp3-for-" + event_id.encode()


def http_response(
    body: bytes,
    *,
    status: str = "200 OK",
    ctype: str | None = "audio/mpeg",
    length: int | None | str = "auto",
) -> bytes:
    """Raw bytes of a whole HTTP/1.0 reply, for replies the normal handler would never send.

    `length="auto"` sends the true Content-Length, `None` sends none, an int sends that (so a short body is a truncation).
    """
    lines = [f"HTTP/1.0 {status}"]
    if ctype is not None:
        lines.append(f"Content-Type: {ctype}")
    if length == "auto":
        lines.append(f"Content-Length: {len(body)}")
    elif length is not None:
        lines.append(f"Content-Length: {length}")
    return ("\r\n".join(lines) + "\r\n\r\n").encode() + body


@dataclass
class FakeInvintus:
    # event id -> (status, body bytes) to send instead of the normal getDetailed reply
    detail_override: dict[str, tuple[int, bytes]] = field(default_factory=dict)
    # event id -> (status, body bytes) to send instead of the MP3
    media_override: dict[str, tuple[int, bytes]] = field(default_factory=dict)
    # event id -> the exact bytes to write to the socket instead of any reply (garbage, truncation, no length)
    detail_raw: dict[str, bytes] = field(default_factory=dict)
    media_raw: dict[str, bytes] = field(default_factory=dict)
    # event id -> a whole audio URI to advertise instead of the normal one (wrong host, userinfo tricks)
    audio_uri_override: dict[str, str] = field(default_factory=dict)
    # event id -> audio URI path to advertise instead of the normal one
    audio_path_override: dict[str, str] = field(default_factory=dict)
    seen: list[Seen] = field(default_factory=list)
    base_url: str = ""
    _server: ThreadingHTTPServer | None = None

    def start(self) -> None:
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args: object) -> None:  # keep test output quiet
                pass

            def _record(self, body: bytes = b"") -> None:
                fake.seen.append(Seen(self.command, self.path, {k.lower(): v for k, v in self.headers.items()}, body))

            def _send(self, status: int, body: bytes, ctype: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                self._record(body)
                if self.path != "/Event/getDetailed":
                    return self._send(404, b"{}", "application/json")
                event_id = str(json.loads(body)["eventID"])
                if event_id in fake.detail_raw:
                    return self.wfile.write(fake.detail_raw[event_id])
                if event_id in fake.detail_override:
                    status, payload = fake.detail_override[event_id]
                    return self._send(status, payload, "application/json")
                audio = fake.audio_path_override.get(event_id, f"/media/{event_id}_audio.mp3")
                uri = fake.audio_uri_override.get(event_id, f"{fake.base_url}{audio}")
                reply = {
                    "data": {
                        "eventID": event_id,
                        "downloadLinks": {
                            "videoDownloadURI": f"{fake.base_url}/media/{event_id}.mp4",
                            "audioDownloadURI": uri,
                        },
                    }
                }
                self._send(200, json.dumps(reply).encode(), "application/json")

            def do_GET(self) -> None:
                self._record()
                name = self.path.rsplit("/", 1)[-1]
                event_id = name.removesuffix(".mp4").removesuffix(".mp3").removesuffix("_audio")
                if event_id in fake.media_raw:
                    return self.wfile.write(fake.media_raw[event_id])
                if event_id in fake.media_override:
                    status, payload = fake.media_override[event_id]
                    return self._send(status, payload, "text/plain")
                if self.path.endswith("_audio.mp3"):
                    return self._send(200, audio_bytes(event_id), "audio/mpeg")
                self._send(200, b"fake-video", "video/mp4")

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(target=self._server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()

    @property
    def download_host(self) -> str:
        """host:port the fake serves its MP3s from, the value Config.download_host needs to accept them."""
        return self.base_url.removeprefix("http://")

    def paths(self) -> list[str]:
        return [s.path for s in self.seen]
