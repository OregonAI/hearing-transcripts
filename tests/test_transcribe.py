"""The transcriber. The happy path runs the real tiny.en model on CPU over a synthetic-speech clip
(tests/fixtures/make_fixture.py); the model is downloaded in CI's setup step, never here, and the network guard in
conftest.py stays on. The failure paths use a stand-in engine that returns faster-whisper's own Segment and Word types."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

import jsonschema
import pytest
from faster_whisper.transcribe import Segment, Word

from hearing_transcripts.cli import main
from hearing_transcripts.transcribe import (
    EngineResult,
    TranscriptInvalid,
    load_vendored_schema,
    map_segments,
    run_transcribe,
    validate_transcript,
)

FIXTURE = Path(__file__).parent / "fixtures" / "tts-fixture.mp3"
MODEL = os.environ.get("HEARING_TEST_MODEL", "tiny.en")
SETTINGS = {"model_name": "tiny.en", "device": "cpu", "compute_type": "int8", "language": "en", "beam_size": 5}


def make_workdir(tmp_path: Path, event_id: str = "2026010001") -> Path:
    shutil.copy(FIXTURE, tmp_path / f"{event_id}.mp3")
    sha = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    (tmp_path / "fetched.jsonl").write_text(json.dumps({"event_id": event_id, "sha256": sha, "bytes": FIXTURE.stat().st_size}) + "\n")
    return tmp_path


class StubEngine:
    """Stands in for the model: returns the segments it is given."""

    model_id = "stub/model@0000000"
    settings = SETTINGS

    def __init__(self, segments, duration=7.5):
        self.result = EngineResult(segments=segments, duration=duration)
        self.calls = []

    def transcribe(self, path):
        self.calls.append(path)
        return self.result


def good_segment(**overrides):
    fields = dict(
        id=1, seek=0, start=0.0, end=2.0, text=" Hello there.", tokens=[1, 2, 3], avg_logprob=-0.2, compression_ratio=1.1,
        no_speech_prob=0.01, temperature=0.0,
        words=[Word(start=0.0, end=0.8, word=" Hello", probability=0.9), Word(start=0.9, end=2.0, word=" there.", probability=0.8)],
    )
    return Segment(**{**fields, **overrides})


# -- the real model, on CPU ---------------------------------------------------------------------------------------

def test_cli_writes_a_schema_valid_transcript_and_deletes_the_mp3(tmp_path, capsys):
    workdir = make_workdir(tmp_path)
    audio_sha = hashlib.sha256((workdir / "2026010001.mp3").read_bytes()).hexdigest()

    code = main(["transcribe", "--workdir", str(workdir), "--model", MODEL, "--device", "cpu", "2026010001"])

    assert code == 0, capsys.readouterr().err
    doc = json.loads((workdir / "2026010001.transcript.json").read_text())
    jsonschema.Draft202012Validator(load_vendored_schema()).validate(doc)
    assert doc["format_version"] == load_vendored_schema()["properties"]["format_version"]["const"]
    assert doc["event_id"] == "2026010001"
    assert doc["audio"]["sha256"] == audio_sha
    assert 3 < doc["audio"]["duration_seconds"] < 12
    assert doc["model"]["settings"] == {"model_name": MODEL, "device": "cpu", "compute_type": "int8", "language": "en", "beam_size": 5}
    assert doc["model"]["id"].endswith(tuple("0123456789abcdef")) and "@" in doc["model"]["id"]
    assert datetime.fromisoformat(doc["made_at"]).utcoffset() is not None
    words = [w for s in doc["segments"] for w in s["words"]]
    assert words, "word timestamps are on"
    spoken = "".join(w["text"] for w in words).lower()
    assert "committee" in spoken and "order" in spoken
    assert all(set(s) <= {"start", "end", "text", "words", "avg_logprob", "compression_ratio", "no_speech_prob", "temperature"} for s in doc["segments"])
    assert not (workdir / "2026010001.mp3").exists()
    assert sorted(p.name for p in workdir.iterdir()) == ["2026010001.transcript.json", "fetched.jsonl"]


# -- the mapping, per ADR-0054 -------------------------------------------------------------------------------------

def test_mapping_keeps_the_listed_fields_and_drops_id_seek_and_tokens():
    [segment] = map_segments([good_segment()])

    assert segment == {
        "start": 0.0, "end": 2.0, "text": " Hello there.", "avg_logprob": -0.2, "compression_ratio": 1.1,
        "no_speech_prob": 0.01, "temperature": 0.0,
        "words": [{"start": 0.0, "end": 0.8, "text": " Hello", "probability": 0.9}, {"start": 0.9, "end": 2.0, "text": " there.", "probability": 0.8}],
    }


def test_mapping_leaves_out_a_temperature_of_none_and_gives_empty_words_for_none():
    [segment] = map_segments([good_segment(temperature=None, words=None)])

    assert "temperature" not in segment
    assert segment["words"] == []


# -- validation gates the write ------------------------------------------------------------------------------------

def test_a_failed_validation_writes_nothing_and_keeps_the_mp3(tmp_path):
    workdir = make_workdir(tmp_path)
    engine = StubEngine([good_segment(no_speech_prob=2.0)])  # the schema allows 0 to 1

    with pytest.raises(TranscriptInvalid) as err:
        run_transcribe(["2026010001"], workdir, engine)

    assert "no_speech_prob" in str(err.value)
    assert not (workdir / "2026010001.transcript.json").exists()
    assert not list(workdir.glob("*.part"))
    assert (workdir / "2026010001.mp3").read_bytes() == FIXTURE.read_bytes()


def test_cli_exits_6_on_a_failed_validation(tmp_path, capsys):
    from hearing_transcripts import cli

    workdir = make_workdir(tmp_path)
    code = cli.main(["transcribe", "--workdir", str(workdir), "--model", "tiny.en", "--device", "cpu", "2026010001"],
                    engine_factory=lambda args: StubEngine([good_segment(end=-1.0)]))

    assert code == 6
    assert "end" in capsys.readouterr().err
    assert (workdir / "2026010001.mp3").exists()
    assert not (workdir / "2026010001.transcript.json").exists()


def test_a_file_whose_version_differs_from_the_vendored_schema_is_refused():
    schema = load_vendored_schema()
    doc = {"format_version": 2, "event_id": "1", "audio": {}, "model": {}, "made_at": "x", "segments": []}

    with pytest.raises(TranscriptInvalid) as err:
        validate_transcript(doc, schema)

    assert "format_version" in str(err.value) and "2" in str(err.value) and "1" in str(err.value)


def test_a_writer_whose_version_differs_from_the_schema_it_validates_against_writes_nothing(tmp_path):
    workdir = make_workdir(tmp_path)
    schema = load_vendored_schema()
    schema["properties"]["format_version"]["const"] = 2  # a later vendored schema than this writer knows

    with pytest.raises(TranscriptInvalid) as err:
        run_transcribe(["2026010001"], workdir, StubEngine([good_segment()]), schema=schema)

    assert "version" in str(err.value)
    assert not (workdir / "2026010001.transcript.json").exists()
    assert (workdir / "2026010001.mp3").exists()


def test_a_valid_stub_run_writes_the_file_and_deletes_the_mp3(tmp_path):
    workdir = make_workdir(tmp_path)

    done = run_transcribe(["2026010001"], workdir, StubEngine([good_segment()]))

    assert done == ["2026010001"]
    doc = json.loads((workdir / "2026010001.transcript.json").read_text())
    validate_transcript(doc, load_vendored_schema())
    assert doc["audio"]["duration_seconds"] == 7.5
    assert doc["model"]["id"] == "stub/model@0000000"
    assert not (workdir / "2026010001.mp3").exists()


# -- inputs --------------------------------------------------------------------------------------------------------

def test_an_event_that_was_not_fetched_is_refused(tmp_path):
    workdir = make_workdir(tmp_path)
    engine = StubEngine([good_segment()])

    with pytest.raises(ValueError, match="2026019999"):
        run_transcribe(["2026019999"], workdir, engine)

    assert engine.calls == []


def test_an_mp3_that_does_not_match_the_recorded_hash_is_refused_and_kept(tmp_path):
    workdir = make_workdir(tmp_path)
    (workdir / "2026010001.mp3").write_bytes(b"ID3 not what was fetched")
    engine = StubEngine([good_segment()])

    with pytest.raises(ValueError, match="sha256"):
        run_transcribe(["2026010001"], workdir, engine)

    assert engine.calls == [] and (workdir / "2026010001.mp3").exists()


def test_event_ids_must_be_digits(tmp_path):
    with pytest.raises(ValueError, match="digits"):
        run_transcribe(["../x"], make_workdir(tmp_path), StubEngine([]))


def test_with_no_ids_it_transcribes_every_fetched_event_that_still_has_its_mp3(tmp_path):
    workdir = make_workdir(tmp_path, "2026010001")
    shutil.copy(FIXTURE, workdir / "2026010002.mp3")
    sha = hashlib.sha256(FIXTURE.read_bytes()).hexdigest()
    with (workdir / "fetched.jsonl").open("a") as fh:
        fh.write(json.dumps({"event_id": "2026010002", "sha256": sha, "bytes": 1}) + "\n")
        fh.write(json.dumps({"event_id": "2026010003", "sha256": sha, "bytes": 1}) + "\n")  # its MP3 is already gone

    done = run_transcribe([], workdir, StubEngine([good_segment()]))

    assert done == ["2026010001", "2026010002"]


def test_a_crash_after_the_write_is_finished_by_deleting_the_mp3_without_transcribing_again(tmp_path):
    workdir = make_workdir(tmp_path)
    run_transcribe(["2026010001"], workdir, StubEngine([good_segment()]))
    shutil.copy(FIXTURE, workdir / "2026010001.mp3")  # as if the delete never happened
    engine = StubEngine([good_segment()])

    done = run_transcribe(["2026010001"], workdir, engine)

    assert done == [] and engine.calls == []
    assert not (workdir / "2026010001.mp3").exists()


# -- the GPU path without its wheels -------------------------------------------------------------------------------

def test_cuda_without_the_wheels_exits_7_naming_the_extra_and_keeps_the_mp3(tmp_path, capsys, monkeypatch):
    workdir = make_workdir(tmp_path)
    monkeypatch.setitem(__import__("sys").modules, "nvidia", None)  # as if `uv sync --extra gpu` was never run

    code = main(["transcribe", "--workdir", str(workdir), "--model", MODEL, "--device", "cuda", "2026010001"])

    assert code == 7
    assert "--extra gpu" in capsys.readouterr().err
    assert (workdir / "2026010001.mp3").exists()
