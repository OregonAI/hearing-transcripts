"""The transcriber: faster-whisper over each fetched MP3 to one `<id>.transcript.json`, valid against the vendored
copy of SessionGateway's schema (ADR-0054, format version 1).

A transcript is validated in memory before anything is written, written to a `.part` file, synced and renamed, read
back and validated again, and only then is the MP3 deleted. A transcript that fails validation is never written and the
MP3 is kept. The audio is hashed, transcribed, then deleted (ADR-0051)."""

from __future__ import annotations

import ctypes
import hashlib
import json
import math
import os
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import timezone
from importlib import resources
from pathlib import Path
from typing import Any, Protocol

import jsonschema

from .clock import Clock, SystemClock
from .download import RECORD_FILE

SCHEMA_NAME = "transcript-v1.schema.json"
FORMAT_VERSION = 1
BEAM_SIZE = 5
LANGUAGE = "en"
COMPUTE_TYPES = {"cpu": "int8", "cuda": "float16"}


class TranscriptInvalid(Exception):
    """The transcript does not satisfy the vendored schema (or the writer's version differs from it). Nothing was written."""


class CudaUnavailable(RuntimeError):
    """device cuda was asked for and the CUDA libraries or the GPU are not usable."""


def load_vendored_schema() -> dict[str, Any]:
    return json.loads((resources.files("hearing_transcripts") / "schemas" / SCHEMA_NAME).read_text())


def _non_finite(value: Any, path: tuple[Any, ...] = ()) -> list[str]:
    """Paths of every NaN and +-Infinity in the document. JSON Schema's minimum and maximum let NaN through, and
    SessionGateway's reader takes finite numbers only, so this is checked on its own."""
    if isinstance(value, float) and not math.isfinite(value):
        return [".".join(str(p) for p in path)]
    if isinstance(value, dict):
        return [bad for k, v in value.items() for bad in _non_finite(v, (*path, k))]
    if isinstance(value, list):
        return [bad for i, v in enumerate(value) for bad in _non_finite(v, (*path, i))]
    return []


def _refuse_constant(name: str) -> Any:
    raise TranscriptInvalid(f"the file holds {name}, which is not JSON and not a finite number")


def read_transcript_file(path: Path) -> Any:
    """Parse a transcript file as strict JSON. A file that does not parse (or holds NaN or Infinity) is a TranscriptInvalid."""
    try:
        return json.loads(path.read_text(), parse_constant=_refuse_constant)
    except ValueError as err:  # JSONDecodeError and UnicodeDecodeError; TranscriptInvalid is not a ValueError and passes through
        raise TranscriptInvalid(f"{path.name} does not parse as JSON: {err}") from None


def validate_transcript(doc: Any, schema: dict[str, Any]) -> None:
    """Raise TranscriptInvalid naming each path that fails. A `format_version` that is not the schema's is refused first,
    then any number that is not finite."""
    wanted = schema["properties"]["format_version"]["const"]
    if isinstance(doc, dict) and doc.get("format_version") != wanted:
        raise TranscriptInvalid(f"format_version is {doc.get('format_version')!r} but the vendored schema is version {wanted}")
    bad = _non_finite(doc)
    if bad:
        raise TranscriptInvalid(f"numbers must be finite (no NaN or Infinity), at: {', '.join(b or '<file>' for b in bad[:10])}")
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(doc), key=lambda e: list(e.absolute_path))
    if errors:
        lines = [f"{'.'.join(str(p) for p in e.absolute_path) or '<file>'}: {e.message[:200]}" for e in errors[:10]]
        raise TranscriptInvalid("; ".join(lines))


def map_segments(segments: Iterable[Any]) -> list[dict[str, Any]]:
    """faster-whisper Segment/Word onto version 1, per ADR-0054: id, seek and tokens are dropped, Word.word becomes text,
    a temperature of None leaves the key out, and words of None become []."""
    out = []
    for seg in segments:
        item: dict[str, Any] = {"start": seg.start, "end": seg.end, "text": seg.text}
        for name in ("avg_logprob", "compression_ratio", "no_speech_prob", "temperature"):
            value = getattr(seg, name)
            if value is not None:
                item[name] = value
        item["words"] = [
            {"start": w.start, "end": w.end, "text": w.word, "probability": w.probability} for w in (seg.words or [])
        ]
        out.append(item)
    return out


@dataclass
class EngineResult:
    segments: Sequence[Any]  # faster-whisper Segment objects
    duration: float


class Engine(Protocol):
    model_id: str
    settings: dict[str, Any]

    def transcribe(self, path: Path) -> EngineResult: ...


def preload_cuda_libraries() -> None:
    """CTranslate2 loads libcublas and libcudnn by name. With the CUDA libraries installed as pip wheels (the `gpu`
    extra) they are not on the loader path, so load them from the wheels' folders first. No system CUDA is used."""
    import importlib.util

    for package, patterns in (("nvidia.cublas", ("libcublasLt.so.12", "libcublas.so.12")),
                              ("nvidia.cudnn", ("libcudnn_ops.so.9", "libcudnn_cnn.so.9", "libcudnn_adv.so.9", "libcudnn_graph.so.9",
                                                "libcudnn_engines_runtime_compiled.so.9", "libcudnn_engines_precompiled.so.9",
                                                "libcudnn_heuristic.so.9", "libcudnn.so.9"))):
        try:
            spec = importlib.util.find_spec(package)  # imports the parent package, so a missing `nvidia` raises here
        except ModuleNotFoundError:
            spec = None
        if spec is None or not spec.submodule_search_locations:
            raise CudaUnavailable(f"{package} is not installed; install the CUDA wheels with `uv sync --extra gpu`")
        lib_dir = Path(next(iter(spec.submodule_search_locations))) / "lib"
        for name in patterns:
            if (lib_dir / name).exists():
                ctypes.CDLL(str(lib_dir / name), mode=ctypes.RTLD_GLOBAL)


_SNAPSHOT = re.compile(r"models--(?P<org>[^/]+)--(?P<name>[^/]+)/snapshots/(?P<rev>[0-9a-f]{7,40})$")


def resolve_model(model_name: str) -> tuple[str, str]:
    """(path, id). Uses the local cache when the model is there, so a cached model needs no network; downloads only if
    it is not cached. The id names the weights and revision, such as Systran/faster-whisper-tiny.en@<commit>."""
    from faster_whisper.utils import download_model
    from huggingface_hub.errors import LocalEntryNotFoundError

    if Path(model_name).is_dir():
        path = model_name
    else:
        try:
            path = download_model(model_name, local_files_only=True)
        except (LocalEntryNotFoundError, FileNotFoundError):
            path = download_model(model_name)
    match = _SNAPSHOT.search(Path(path).as_posix())
    return path, (f"{match['org']}/{match['name']}@{match['rev']}" if match else model_name)


class WhisperEngine:
    def __init__(self, model_name: str, device: str) -> None:
        from faster_whisper import WhisperModel

        if device not in COMPUTE_TYPES:
            raise ValueError(f"device must be cpu or cuda, not {device!r}")
        if device == "cuda":
            preload_cuda_libraries()
        path, self.model_id = resolve_model(model_name)
        self.settings = {"model_name": model_name, "device": device, "compute_type": COMPUTE_TYPES[device],
                         "language": LANGUAGE, "beam_size": BEAM_SIZE}
        try:
            self._model = WhisperModel(path, device=device, compute_type=self.settings["compute_type"])
        except RuntimeError as err:
            if device == "cuda":
                raise CudaUnavailable(f"CUDA could not be used: {err}") from err
            raise

    def transcribe(self, path: Path) -> EngineResult:
        generator, info = self._model.transcribe(str(path), language=LANGUAGE, beam_size=BEAM_SIZE, word_timestamps=True)
        try:
            return EngineResult(segments=list(generator), duration=info.duration)  # the generator is lazy; run it here
        except RuntimeError as err:
            if self.settings["device"] == "cuda":
                raise CudaUnavailable(f"CUDA could not be used: {err}") from err
            raise


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _records(workdir: Path) -> dict[str, dict[str, Any]]:
    record = workdir / RECORD_FILE
    if not record.exists():
        raise ValueError(f"{record} does not exist; run the downloader first")
    out: dict[str, dict[str, Any]] = {}
    for number, line in enumerate(record.read_text().splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
            out[str(entry["event_id"])] = entry
        except (ValueError, KeyError, TypeError):
            raise ValueError(f"{record} line {number} is not a valid record; refusing to run") from None
    return out


def _fsync_dir(directory: Path) -> None:
    """Make a rename or a name's presence durable: until the directory is synced, a crash can lose the new name."""
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_checked(doc: dict[str, Any], final: Path, schema: dict[str, Any]) -> None:
    """Validate, write to a .part file, sync, rename, read back and validate the file itself."""
    validate_transcript(doc, schema)
    part = final.with_name(final.name + ".part")
    try:
        with part.open("w") as fh:
            json.dump(doc, fh, indent=1, allow_nan=False)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(part, final)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    try:
        validate_transcript(read_transcript_file(final), schema)
        _fsync_dir(final.parent)
    except BaseException:
        final.unlink(missing_ok=True)
        raise


def run_transcribe(event_ids: Sequence[str], workdir: Path, engine: Engine, *, schema: dict[str, Any] | None = None,
                   clock: Clock | None = None) -> list[str]:
    """Transcribe each event's MP3 (all fetched events that still have one when no ids are given). Returns the ids
    transcribed in this run. The first failure raises; events done before it stay done."""
    schema = schema or load_vendored_schema()
    clock = clock or SystemClock()
    for event_id in event_ids:
        if not event_id.isdigit():
            raise ValueError(f"event ID {event_id!r} is not digits only")
    records = _records(workdir)
    ids = list(event_ids) or [i for i in records if (workdir / f"{i}.mp3").exists()]
    for event_id in ids:
        if event_id not in records:
            raise ValueError(f"event {event_id} is not in {RECORD_FILE}; fetch it first")
    done: list[str] = []
    for event_id in ids:
        mp3, final = workdir / f"{event_id}.mp3", workdir / f"{event_id}.transcript.json"
        if final.exists():
            _finish_interrupted(event_id, mp3, final, schema)
            continue
        if not mp3.exists():
            raise ValueError(f"{mp3} does not exist and there is no transcript for event {event_id}")
        sha256 = _sha256(mp3)
        if sha256 != records[event_id]["sha256"]:
            raise ValueError(f"{mp3} has sha256 {sha256}, not the {records[event_id]['sha256']} recorded when it was fetched; kept, not transcribed")
        result = engine.transcribe(mp3)
        doc = {
            "format_version": FORMAT_VERSION,
            "event_id": event_id,
            "audio": {"sha256": sha256, "duration_seconds": result.duration},
            "model": {"id": engine.model_id, "settings": engine.settings},
            "made_at": clock.now().astimezone(timezone.utc).isoformat(timespec="seconds"),
            "segments": map_segments(result.segments),
        }
        try:
            _write_checked(doc, final, schema)
        except TranscriptInvalid as err:
            raise TranscriptInvalid(f"event {event_id}: {err}; nothing was written and the MP3 is kept") from None
        mp3.unlink()  # only after the file is written, validated and its directory entry synced
        done.append(event_id)
    return done


def _finish_interrupted(event_id: str, mp3: Path, final: Path, schema: dict[str, Any]) -> None:
    """A transcript already exists. If its MP3 is still here (the run stopped before the delete), delete it once the
    file validates and names this MP3's hash; never overwrite a transcript."""
    if not mp3.exists():
        return
    try:
        doc = read_transcript_file(final)
        validate_transcript(doc, schema)
        if doc["event_id"] != event_id:
            raise TranscriptInvalid(f"it is for event {doc['event_id']!r}, not {event_id!r}")
    except TranscriptInvalid as err:
        raise TranscriptInvalid(f"event {event_id}: the existing {final.name} is not valid ({err}); the MP3 is kept") from None
    if doc["audio"]["sha256"] != _sha256(mp3):
        raise ValueError(f"{final.name} was made from different audio than {mp3.name}; both kept")
    _fsync_dir(final.parent)  # the transcript's name is durable before its audio goes
    mp3.unlink()
