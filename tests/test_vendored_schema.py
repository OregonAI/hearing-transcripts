"""The vendored copy of SessionGateway's transcript schema is byte for byte the file whose hash and source commit are
recorded. Editing either one without the other turns this red (SessionGateway ADR-0054: version 1 is never edited)."""

from __future__ import annotations

import hashlib
import json
from importlib import resources

SCHEMA_DIR = resources.files("hearing_transcripts") / "schemas"


def test_the_vendored_schema_matches_the_recorded_hash():
    source = json.loads((SCHEMA_DIR / "transcript-v1.source.json").read_text())
    actual = hashlib.sha256((SCHEMA_DIR / "transcript-v1.schema.json").read_bytes()).hexdigest()

    assert actual == source["sha256"]


def test_the_source_record_names_the_repository_path_and_commit():
    source = json.loads((SCHEMA_DIR / "transcript-v1.source.json").read_text())

    assert source["repository"] == "OregonAI/SessionGateway"
    assert source["path"] == "docs/schemas/transcript-v1.schema.json"
    assert len(source["commit"]) == 40 and set(source["commit"]) <= set("0123456789abcdef")
    assert len(source["sha256"]) == 64


def test_the_vendored_schema_is_format_version_1():
    schema = json.loads((SCHEMA_DIR / "transcript-v1.schema.json").read_text())

    assert schema["properties"]["format_version"]["const"] == 1
