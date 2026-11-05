"""Seam P1, slice 1: what the downloader asks for and what it does with the replies, against the local fake."""

from __future__ import annotations

import hashlib
import json

import pytest

from conftest import DUMMY_KEY, fake_config
from fake_invintus import audio_bytes
from hearing_transcripts.download import Config, Halt, run_download

UA = "SessionGateway-transcripts/1 (+https://github.com/OregonAI/SessionGateway)"


def config(fake):
    return fake_config(fake)


def test_writes_the_mp3_and_records_its_sha256(fake, clock, tmp_path):
    fetched = run_download(["2026010001"], config(fake), tmp_path, clock)

    assert fetched == ["2026010001"]
    assert (tmp_path / "2026010001.mp3").read_bytes() == audio_bytes("2026010001")
    records = [json.loads(line) for line in (tmp_path / "fetched.jsonl").read_text().splitlines()]
    assert [(r["event_id"], r["sha256"]) for r in records] == [
        ("2026010001", hashlib.sha256(b"ID3-fake-mp3-for-2026010001").hexdigest())
    ]


def test_every_request_carries_the_exact_user_agent(fake, clock, tmp_path):
    run_download(["2026010001"], config(fake), tmp_path, clock)

    assert len(fake.seen) == 2  # getDetailed, then the MP3
    assert [s.headers["user-agent"] for s in fake.seen] == [UA, UA]


def test_the_key_goes_in_the_request_headers_as_the_embedder_credential(fake, clock, tmp_path):
    run_download(["2026010001"], config(fake), tmp_path, clock)

    detail = fake.seen[0]
    assert detail.headers["authorization"] == "embedder"
    assert detail.headers["wsc-api-key"] == DUMMY_KEY
    assert json.loads(detail.body)["eventID"] == "2026010001"


def test_a_second_run_fetches_nothing_already_fetched(fake, clock, tmp_path):
    run_download(["2026010001", "2026010002"], config(fake), tmp_path, clock)
    fake.seen.clear()

    fetched = run_download(["2026010001", "2026010002", "2026010003"], config(fake), tmp_path, clock)

    assert fetched == ["2026010003"]
    assert all("2026010003" in (s.body.decode() + s.path) for s in fake.seen)
    assert len(fake.seen) == 2


def test_only_the_mp3_is_requested_never_the_mp4(fake, clock, tmp_path):
    run_download(["2026010001"], config(fake), tmp_path, clock)

    assert fake.paths() == ["/Event/getDetailed", "/media/2026010001_audio.mp3"]
    assert not any(p.endswith(".mp4") for p in fake.paths())


def test_an_audio_address_that_is_not_an_mp3_halts_and_is_never_requested(fake, clock, tmp_path):
    fake.audio_path_override["2026010001"] = "/media/2026010001.mp4"

    with pytest.raises(Halt, match="2026010001"):
        run_download(["2026010001"], config(fake), tmp_path, clock)

    assert fake.paths() == ["/Event/getDetailed"]


@pytest.mark.parametrize("status", [401, 403, 429])
def test_a_refusal_from_getdetailed_halts_with_no_retry(status, fake, clock, tmp_path):
    fake.detail_override["2026010001"] = (status, b"{}")

    with pytest.raises(Halt, match=str(status)):
        run_download(["2026010001", "2026010002"], config(fake), tmp_path, clock)

    assert fake.paths() == ["/Event/getDetailed"]  # one request: no retry, and the next event is never asked for


@pytest.mark.parametrize("status", [401, 403, 429])
def test_a_refusal_for_the_mp3_halts_with_no_retry(status, fake, clock, tmp_path):
    fake.media_override["2026010001"] = (status, b"no")

    with pytest.raises(Halt, match=str(status)):
        run_download(["2026010001", "2026010002"], config(fake), tmp_path, clock)

    assert fake.paths() == ["/Event/getDetailed", "/media/2026010001_audio.mp3"]
    assert not (tmp_path / "2026010001.mp3").exists()
    assert not (tmp_path / "fetched.jsonl").exists()


@pytest.mark.parametrize(
    "status, body",
    [
        (500, b"{}"),
        (404, b"{}"),
        (302, b""),
        (200, b"not json"),
        (200, b'{"data": {}}'),
        (200, b'{"data": {"downloadLinks": {"audioDownloadURI": ""}}}'),
    ],
)
def test_an_unexpected_reply_halts_with_no_retry(status, body, fake, clock, tmp_path):
    fake.detail_override["2026010001"] = (status, body)

    with pytest.raises(Halt, match="2026010001"):
        run_download(["2026010001", "2026010002"], config(fake), tmp_path, clock)

    assert fake.paths() == ["/Event/getDetailed"]


def test_a_halt_keeps_what_was_fetched_before_it(fake, clock, tmp_path):
    fake.detail_override["2026010002"] = (429, b"{}")

    with pytest.raises(Halt):
        run_download(["2026010001", "2026010002"], config(fake), tmp_path, clock)

    records = [json.loads(line) for line in (tmp_path / "fetched.jsonl").read_text().splitlines()]
    assert [r["event_id"] for r in records] == ["2026010001"]
