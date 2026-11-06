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
- **transcribe** ([SessionGateway#132](https://github.com/OregonAI/SessionGateway/issues/132)): turns each fetched MP3
  into a transcript file, then deletes the MP3.

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
kept or redistributed: it is hashed, transcribed, then deleted (the transcribe step).

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

## The transcriber

```sh
uv run hearing-transcripts transcribe --workdir work --model small.en --device cpu          # every fetched event that still has its MP3
uv run hearing-transcripts transcribe --workdir work --model small.en --device cuda 2026010001
```

It makes no request to Invintus. For each event it runs faster-whisper with word timestamps (`language` en, `beam_size`
5; compute type `int8` on cpu, `float16` on cuda) on `<id>.mp3`, and writes `<id>.transcript.json` in the working
folder.

- **The file** is SessionGateway's transcript format, version 1 ([ADR-0054](https://github.com/OregonAI/SessionGateway/blob/main/docs/adr/0054-the-transcript-file-is-one-meeting-with-a-version-that-only-increases-and-the-read-attaches-words-to-turns-by-their-seconds.md)):
  `event_id`, `audio` (the MP3's sha256 and duration), `model` (the weights and revision as `repo@commit`, and the
  settings), `made_at`, and `segments` with words. Of faster-whisper's `Segment`, `id`, `seek` and `tokens` are dropped;
  `Word.word` becomes `text`; `temperature` is left out when the model gives none.
- **The vendored schema** is `src/hearing_transcripts/schemas/transcript-v1.schema.json`, a byte copy of SessionGateway's
  file. `transcript-v1.source.json` beside it records the SessionGateway commit it came from and its sha256, and a test
  fails when the two disagree. Version 1 is never edited: a new format is a new `transcript-v2` file and a new writer.
  The writer refuses (writes nothing) if its own version is not the schema's `format_version`.
- **Validation gates the write.** The document is validated in memory, written to `.part`, synced, renamed, read back
  and validated again, the directory is synced, and only then is the MP3 deleted. If validation fails nothing is written
  and the MP3 is kept. Validation also refuses NaN and Infinity anywhere (SessionGateway's reader takes finite numbers
  only, and JSON Schema's `minimum` lets NaN through), and the file is written with `allow_nan=False`. `made_at` is the
  injected clock's time in UTC.
  The MP3's sha256 must match `fetched.jsonl`, or it is kept and not transcribed. A transcript that already exists is
  never overwritten; if its MP3 is still there (a run stopped before the delete) and the file parses, validates, is for
  this event and names that MP3's hash, the MP3 is deleted. Otherwise the MP3 is kept (exit 6 for a file that is corrupt,
  invalid or another event's).
- The model is taken from the local cache (`~/.cache/huggingface`) when it is there and downloaded from Hugging Face
  only if it is not. That is the only network use.

Exit codes of `transcribe` (an earlier event's transcript stays done when a later one fails):

| Code | Meaning |
| --- | --- |
| 0 | Done |
| 1 | Bad usage or unusable input: an event not in `fetched.jsonl`, an MP3 missing or not matching its recorded hash, ids not digits |
| 6 | A transcript failed validation (including a readback that does not parse, or an existing file that is corrupt, invalid or for another event): MP3 kept |
| 7 | `--device cuda` but the CUDA libraries or the GPU are not usable |

### GPU setup (optional, no system CUDA)

The CUDA 12 libraries that CTranslate2 needs come as pip wheels in the tool's own environment, as the `gpu` extra
(`nvidia-cublas-cu12`, `nvidia-cudnn-cu12`):

```sh
uv sync --extra gpu            # or, as an installed tool: uv tool install ".[gpu]"
uv run hearing-transcripts transcribe --workdir work --model small.en --device cuda
```

Nothing is added to `LD_LIBRARY_PATH`: with `--device cuda` the tool loads `libcublas` and `libcudnn` from the wheels'
folders itself before the model loads. Only the NVIDIA driver must be installed on the machine (`nvidia-smi` works).
A plain `uv sync` removes the wheels again. Without them `--device cuda` exits 7 and says to run `uv sync --extra gpu`.
The CPU path needs none of this.

## Tests

```sh
uv sync
uv run pytest
```

The transcriber's tests run the real `tiny.en` model on CPU over `tests/fixtures/tts-fixture.mp3`, a few seconds of
synthetic speech (espeak-ng reading a sentence written for this repository; see `tests/fixtures/README.md`; never
Legislature audio). The model is downloaded in setup, not in a test: CI's setup step caches `~/.cache/huggingface` and
downloads `tiny.en` before `pytest`; locally, run once
`uv run python -c "from faster_whisper.utils import download_model; download_model('tiny.en')"`. A test that finds the
model missing fails (the guard blocks the download) rather than skipping.

The downloader's tests use a local fake server started in the test. They make no request to Invintus and need no GPU. A session-wide
guard in `tests/conftest.py` makes any connect or name lookup other than to `127.0.0.1` / `::1` raise, and CI clears the
proxy variables.

## License

MIT, see `LICENSE`.
