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

## The downloader's rules (enforced in code)

- Runs only between 00:00 and 06:00 Pacific. Outside that window it refuses to start.
- One request at a time, about 3 seconds apart.
- Each event is fetched once. A record file holds the fetched event IDs with the audio's sha256.
- MP3 only, never MP4 or video.
- The User-Agent is exactly `SessionGateway-transcripts/1 (+https://github.com/OregonAI/SessionGateway)`.
- It halts the whole run at the first 401, 403 or 429, or any unexpected response, and does not retry. The owner
  decides what happens next.
- No rotating addresses, no disguised clients, no proxies.
- Audio is never kept or redistributed: it is hashed, transcribed, then deleted.

Runs are approved by the owner one at a time and happen from the GPU desktop.

## Running it (operator)

The operator supplies the configuration in the environment. Nothing below is committed in this repository.

```sh
export HEARING_API_BASE_URL=...      # the Invintus API base URL, from the operator
export HEARING_EMBEDDER_KEY=...      # the embedder key, from the operator; never commit it
uv run hearing-transcripts download --workdir work 2026010001 2026010002
```

## Tests

```sh
uv sync
uv run pytest
```

The tests use a local fake server started in the test. They make no request to Invintus and need no GPU.

## License

MIT, see `LICENSE`.
