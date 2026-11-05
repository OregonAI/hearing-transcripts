"""Command line. The embedder key and the real base URL come from the environment only; neither is in this repository."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from .clock import Clock, SystemClock
from .download import Config, Halt, OutsideWindow, run_download


def main(argv: Sequence[str] | None = None, *, env: Mapping[str, str] | None = None, clock: Clock | None = None) -> int:
    env = os.environ if env is None else env
    clock = clock or SystemClock()
    parser = argparse.ArgumentParser(prog="hearing-transcripts")
    sub = parser.add_subparsers(dest="command", required=True)
    dl = sub.add_parser("download", help="fetch each event's MP3 once into the working folder")
    dl.add_argument("--workdir", type=Path, required=True)
    dl.add_argument("event_ids", nargs="+")
    args = parser.parse_args(argv)

    key, base_url = env.get("HEARING_EMBEDDER_KEY"), env.get("HEARING_API_BASE_URL")
    for name, value in (("HEARING_EMBEDDER_KEY", key), ("HEARING_API_BASE_URL", base_url)):
        if not value:
            print(f"{name} is not set; the operator supplies it in the environment", file=sys.stderr)
            return 1
    config = Config(base_url=base_url, api_key=key, client_id=env.get("HEARING_CLIENT_ID", "4879615486"))
    try:
        fetched = run_download(args.event_ids, config, args.workdir, clock)
    except OutsideWindow as err:
        print(str(err), file=sys.stderr)
        return 3
    except Halt as err:
        print(f"HALTED: {err}\nNothing was retried. Waiting for the owner's decision.", file=sys.stderr)
        return 2
    print(f"fetched {len(fetched)}: {' '.join(fetched)}")
    return 0
