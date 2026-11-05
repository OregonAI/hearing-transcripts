# Rules for agents

This repository holds a one-time backfill tool for SessionGateway (spec #123, tickets #131 and #132, ADR-0051 and ADR-0054 in SessionGateway).

- **No request to Invintus, ever, in tests, CI or by hand.** That means any `invintus.com` host and the media hosts.
  Tests run the downloader against the local fake server in `tests/fake_invintus.py`. Real runs are the owner's.
- **The downloader's rules are in code and tested; do not loosen them.** 00:00-06:00 Pacific window, one request at a
  time about 3 s apart, each event once, MP3 only, the exact User-Agent, a halt at the first 401, 403, 429 or any
  unexpected response (including a bad MP3 reply or any `http.client` error) with no retry. A halt writes the marker `HALTED.json`, and while it exists every run refuses (exit 5) and requests nothing; only the owner clears it, with `--clear-halt`. Every downloading run needs `--approved-run` (exit 4 without it). Never clear a marker or pass the flag yourself outside a test. No rotating addresses,
  proxies or disguised clients. Only the operator keeps the rest: one-time backfill, 2026R1 committee recordings only,
  runs from the desktop, and that the owner really approved the run.
- **The embedder key and the real base URL come from the environment only** (`HEARING_EMBEDDER_KEY`,
  `HEARING_API_BASE_URL`). Never write either into a file, a test or a commit. Tests use a dummy key. `HEARING_DOWNLOAD_HOST` optionally sets the expected MP3 host.
- **`tests/conftest.py` blocks every connect and name lookup but loopback for the whole session.** Do not weaken it.
- **Audio is never committed, kept or served.** `.gitignore` excludes it, with one exception: `tests/fixtures/tts-fixture.mp3`,
  synthetic speech from a text-to-speech program, not Legislature audio. Never add another audio file, and never use
  hearing audio as a fixture.
- **The transcriber** writes SessionGateway's format version 1 and validates against the vendored schema in
  `src/hearing_transcripts/schemas/`. Never edit that schema; update it only by copying SessionGateway's file and
  recording the new commit and sha256 beside it (and a changed format is a new version, not an edit). A file that fails
  validation is never written and its MP3 is kept; the MP3 is deleted only after the file is written and validated.
  Test downloads of the model belong in CI's setup step, not in a test.
- **Never touch SessionGateway's database.**
- Python 3.12, managed with `uv`. Run the tests with `uv run pytest`. Pass a clock to anything that waits or reads the
  time (`hearing_transcripts.clock`), so tests are fast and deterministic.
- Work test-first: a failing test in its own commit, then the code. One PR per ticket off `main` (the repository
  squash-merges). Commit messages name the ticket.
