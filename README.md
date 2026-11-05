# hearing-transcripts

Machine transcripts of Oregon Legislature committee hearings, for
[SessionGateway](https://github.com/OregonAI/SessionGateway). This is a **one-time backfill** of the 2026 Regular
Session (2026R1) committee hearings, not a service.

- Spec: [SessionGateway#123](https://github.com/OregonAI/SessionGateway/issues/123).
- Ticket for this repository and its downloader: [SessionGateway#131](https://github.com/OregonAI/SessionGateway/issues/131).
- The decision, its risk, limits and stop rules: SessionGateway ADR-0051,
  `docs/adr/0051-hearing-audio-is-fetched-through-the-invintus-embedder-interface-once-and-the-owner-accepts-the-risk.md`.

The transcripts are machine transcripts of the official recordings. They are not an official record.

## What is here

- **download**: takes Invintus event IDs, writes MP3s to a working folder, and records what it fetched so nothing is
  fetched twice.
- **transcribe** (a later ticket): turns each MP3 into a transcript file, then deletes the MP3.

It never touches SessionGateway's database.

## The downloader's rules

Enforced in code (each has a test against a local fake server):

- Runs only between 00:00 and 06:00 Pacific. Outside that window it refuses to start (exit 3), and it re-checks before
  every request.
- One request at a time, about 3 seconds apart, measured on a monotonic clock.
- Each event is fetched once. `fetched.jsonl` in the working folder holds `event_id`, `sha256` and `bytes` for each
  fetched event. A line that is not a record (a torn last line, say) makes the run refuse to start and name the line.
- MP3 only, never MP4 or video. The audio address must be `https` on the download host (default
  `m-download.invintus.com`, the host of the MP3 URL the research captured; override with `HEARING_DOWNLOAD_HOST`) and
  end in `.mp3`, or the run halts without requesting it. The reply must be an `audio/*` type with a Content-Length that
  matches the bytes read, and the body must start like an MP3 (an ID3 header or an MPEG frame sync). It is written to
  `<id>.mp3.part`, synced, then renamed; a fetch is recorded only after that.
- The User-Agent is exactly `SessionGateway-transcripts/1 (+https://github.com/OregonAI/SessionGateway)`.
- It halts the whole run at the first 401, 403 or 429, or any unexpected reply (another status, a redirect, an
  unexpected body, a bad MP3 reply, any `http.client` error), and does not retry. The owner decides what happens
  next.
- No proxies (`http_proxy` and the like are ignored), no redirects followed, no rotating addresses, no disguised
  clients.
- Event IDs must be digits only.
- **The halt marker.** When the downloader halts for any reason (a refusal, an unexpected reply, an http error, a
  damaged record) it writes `HALTED.json` in the working folder, naming the event ID, the request, the reason and the
  time. While it exists every run refuses to start (exit 5) and makes no request. Only the owner clears it:
  `download --clear-halt --workdir <dir>` prints the marker and removes it.
- **The approval flag.** Every downloading run needs `--approved-run`. Without it the tool refuses (exit 4) and makes
  no request.

Not enforced by the code, because only the operator can: that this is a one-time backfill, that only 2026R1 committee
recordings are fetched, and that runs happen from the GPU desktop. (The owner's approval of each run is carried by `--approved-run`; the code can check the flag, not who typed it.) Audio is never
kept or redistributed: it is hashed, transcribed, then deleted (the transcribe step is a later ticket).

## Running it (operator)

The operator supplies the configuration in the environment. Nothing below is committed in this repository.

```sh
export HEARING_API_BASE_URL=...      # the Invintus API base URL, from the operator
export HEARING_EMBEDDER_KEY=...      # the embedder key, from the operator; never commit it
export HEARING_CLIENT_ID=...         # optional; the Invintus client ID (default 4879615486)
export HEARING_DOWNLOAD_HOST=...     # optional; the expected MP3 host (default m-download.invintus.com)
uv run hearing-transcripts download --approved-run --workdir work 2026010001 2026010002

# after a halt, once the owner has decided what happens next:
uv run hearing-transcripts download --clear-halt --workdir work
```

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | Done (also `--clear-halt`, whether or not a marker was there) |
| 1 | Bad usage: missing configuration, no event IDs, an event ID that is not digits |
| 2 | Halted: a refusal or an unexpected reply, or a damaged record file; the marker is written, nothing is retried |
| 3 | Outside the 00:00-06:00 Pacific window |
| 4 | Refused: no `--approved-run`; nothing requested |
| 5 | Refused: a halt marker exists; nothing requested until the owner runs `--clear-halt` |

## Tests

```sh
uv sync
uv run pytest
```

The tests use a local fake server started in the test. They make no request to Invintus and need no GPU. A session-wide
guard in `tests/conftest.py` makes any connect or name lookup other than to `127.0.0.1` / `::1` raise, and CI clears the
proxy variables.

## License

MIT, see `LICENSE`.
