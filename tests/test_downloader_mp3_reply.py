"""The MP3 reply is checked before anything is kept or recorded; a bad reply halts the run (ADR-0051 stop rules)."""

from __future__ import annotations

import json

import pytest

from conftest import DUMMY_KEY, fake_config
from fake_invintus import http_response
from hearing_transcripts import download
from hearing_transcripts.cli import main
from hearing_transcripts.download import Config, Halt, run_download

EVENT = "2026010001"
ID3_MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 32
FRAME_SYNC_MP3 = b"\xff\xfb\x90\x00" + b"\x00" * 32


def config(fake):
    return fake_config(fake)


def assert_nothing_kept(workdir):
    assert sorted(p.name for p in workdir.iterdir()) == []  # no .mp3, no .part, no record


BAD_REPLIES = {
    "html page with status 200": http_response(b"<html>Sorry</html>", ctype="text/html; charset=utf-8"),
    "no content type": http_response(ID3_MP3, ctype=None),
    "audio type but not an mp3 body": http_response(b"<html>Sorry</html>", ctype="audio/mpeg"),
    "empty body": http_response(b"", ctype="audio/mpeg"),
    "no content length": http_response(ID3_MP3, length=None),
    "truncated body": http_response(ID3_MP3[:10], length=len(ID3_MP3)),
}


@pytest.mark.parametrize("reply", BAD_REPLIES.values(), ids=BAD_REPLIES.keys())
def test_a_bad_mp3_reply_halts_and_nothing_is_kept_or_recorded(reply, fake, clock, tmp_path):
    fake.media_raw[EVENT] = reply

    with pytest.raises(Halt, match=EVENT):
        run_download([EVENT, "2026010002"], config(fake), tmp_path, clock)

    assert fake.paths() == ["/Event/getDetailed", f"/media/{EVENT}_audio.mp3"]  # the next event is never asked for
    assert_nothing_kept(tmp_path)


def test_a_bad_mp3_reply_exits_2_with_the_halt_message(fake, clock, tmp_path, capsys):
    fake.media_raw[EVENT] = BAD_REPLIES["html page with status 200"]
    env = {"HEARING_API_BASE_URL": fake.base_url, "HEARING_EMBEDDER_KEY": DUMMY_KEY, "HEARING_DOWNLOAD_HOST": fake.download_host}

    code = main(["download", "--workdir", str(tmp_path), EVENT], env=env, clock=clock, require_https=False)

    err = capsys.readouterr().err
    assert code == 2
    assert "HALTED" in err and "Waiting for the owner" in err


@pytest.mark.parametrize("body", [ID3_MP3, FRAME_SYNC_MP3], ids=["id3 header", "mpeg frame sync"])
def test_a_valid_tiny_mp3_is_accepted(body, fake, clock, tmp_path):
    fake.media_raw[EVENT] = http_response(body, ctype="audio/mpeg")

    assert run_download([EVENT], config(fake), tmp_path, clock) == [EVENT]

    assert (tmp_path / f"{EVENT}.mp3").read_bytes() == body
    assert not (tmp_path / f"{EVENT}.mp3.part").exists()
    record = json.loads((tmp_path / "fetched.jsonl").read_text())
    assert (record["event_id"], record["bytes"]) == (EVENT, len(body))


def test_the_file_is_written_to_a_part_file_synced_then_renamed(fake, clock, tmp_path, monkeypatch):
    steps = []
    real_fsync, real_replace = download.os.fsync, download.os.replace

    def fsync(fd):
        steps.append(("fsync", sorted(p.name for p in tmp_path.iterdir() if p.suffix == ".part")))
        return real_fsync(fd)

    def replace(src, dst):
        steps.append(("replace", str(src).rsplit("/", 1)[-1], str(dst).rsplit("/", 1)[-1]))
        return real_replace(src, dst)

    monkeypatch.setattr(download.os, "fsync", fsync)
    monkeypatch.setattr(download.os, "replace", replace)

    run_download([EVENT], config(fake), tmp_path, clock)

    mp3_steps = [s for s in steps if s[0] == "replace" and s[2].endswith(".mp3")]
    assert mp3_steps == [("replace", f"{EVENT}.mp3.part", f"{EVENT}.mp3")]
    assert ("fsync", [f"{EVENT}.mp3.part"]) in steps  # synced while it was still the .part file
    assert steps.index(("fsync", [f"{EVENT}.mp3.part"])) < steps.index(mp3_steps[0])
