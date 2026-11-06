"""Command line. The embedder key and the real base URL come from the environment only; neither is in this repository."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from .clock import Clock, SystemClock
from .transcribe import CudaUnavailable, Engine, TranscriptInvalid, WhisperEngine, run_transcribe
from .download import DEFAULT_DOWNLOAD_HOST, HALT_MARKER, Config, Halt, HaltMarkerPresent, InvalidEventId, OutsideWindow, read_halt_marker, run_download


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None, clock: Clock | None = None, require_https: bool = True,
         engine_factory: Callable[[argparse.Namespace], Engine] | None = None) -> int:
    """`require_https=False` exists only so tests can talk to the plain-http local fake; nothing on the command line sets it."""
    env = os.environ if env is None else env
    clock = clock or SystemClock()
    parser = argparse.ArgumentParser(prog="hearing-transcripts")
    sub = parser.add_subparsers(dest="command", required=True)
    dl = sub.add_parser("download", help="fetch each event's MP3 once into the working folder")
    dl.add_argument("--workdir", type=Path, required=True)
    dl.add_argument("--approved-run", action="store_true", help="the owner approved this run; without it nothing is requested")
    dl.add_argument("--clear-halt", action="store_true", help="owner act: print the halt marker, remove it, and exit; requests nothing")
    dl.add_argument("event_ids", nargs="*")
    tr = sub.add_parser("transcribe", help="transcribe each fetched MP3 to <id>.transcript.json, then delete the MP3")
    tr.add_argument("--workdir", type=Path, required=True)
    tr.add_argument("--model", required=True, help="a faster-whisper model name (tiny.en, small.en, ...) or a local model folder")
    tr.add_argument("--device", choices=("cpu", "cuda"), required=True)
    tr.add_argument("event_ids", nargs="*", help="default: every fetched event that still has its MP3")
    args = parser.parse_args(argv)

    if args.command == "transcribe":
        return _transcribe(args, engine_factory, clock)

    if args.clear_halt:
        text = read_halt_marker(args.workdir)
        if text is None:
            print(f"no halt marker in {args.workdir}")
        else:
            print(text.strip())
            (args.workdir / HALT_MARKER).unlink()
            print(f"halt marker removed from {args.workdir}")
        return 0
    if not args.event_ids:
        print("no event IDs given", file=sys.stderr)
        return 1
    if not args.approved_run:
        print("refusing to run: every downloading run needs --approved-run, the owner's approval; nothing was requested", file=sys.stderr)
        return 4

    key, base_url = env.get("HEARING_EMBEDDER_KEY"), env.get("HEARING_API_BASE_URL")
    for name, value in (("HEARING_EMBEDDER_KEY", key), ("HEARING_API_BASE_URL", base_url)):
        if not value:
            print(f"{name} is not set; the operator supplies it in the environment", file=sys.stderr)
            return 1
    config = Config(base_url=base_url, api_key=key, client_id=env.get("HEARING_CLIENT_ID", "4879615486"),
        download_host=env.get("HEARING_DOWNLOAD_HOST") or DEFAULT_DOWNLOAD_HOST,
        require_https=require_https,
    )
    try:
        fetched = run_download(args.event_ids, config, args.workdir, clock)
    except InvalidEventId as err:
        print(str(err), file=sys.stderr)
        return 1
    except OutsideWindow as err:
        print(str(err), file=sys.stderr)
        return 3
    except HaltMarkerPresent as err:
        print(f"REFUSED: {err}", file=sys.stderr)
        return 5
    except Halt as err:
        print(f"HALTED: {err}\nNothing was retried. Waiting for the owner's decision.", file=sys.stderr)
        return 2
    print(f"fetched {len(fetched)}: {' '.join(fetched)}")
    return 0


def _transcribe(args: argparse.Namespace, engine_factory: Callable[[argparse.Namespace], Engine] | None, clock: Clock) -> int:
    """Exit 0 done, 1 bad usage or unusable input, 6 a transcript failed validation (nothing written, MP3 kept), 7 CUDA unusable."""
    try:
        engine = engine_factory(args) if engine_factory else WhisperEngine(args.model, args.device)
        done = run_transcribe(args.event_ids, args.workdir, engine, clock=clock)
    except TranscriptInvalid as err:
        print(f"INVALID: {err}", file=sys.stderr)
        return 6
    except CudaUnavailable as err:
        print(f"CUDA UNAVAILABLE: {err}", file=sys.stderr)
        return 7
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 1
    print(f"transcribed {len(done)}: {' '.join(done)}")
    return 0
