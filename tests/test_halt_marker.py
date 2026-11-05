"""Q2 (owner, 2026-11-05): a halt writes a marker; while it exists every run refuses and sends no request; clearing it
is an explicit owner act (`--clear-halt`)."""

from __future__ import annotations

import json

import pytest

from conftest import DUMMY_KEY, fake_config
from fake_invintus import http_response
from hearing_transcripts.cli import main
from hearing_transcripts.download import HALT_MARKER, Halt, HaltMarkerPresent, run_download

EVENT = "2026010001"


def env_for(fake):
    return {"HEARING_API_BASE_URL": fake.base_url, "HEARING_EMBEDDER_KEY": DUMMY_KEY, "HEARING_DOWNLOAD_HOST": fake.download_host}


def cli(argv, fake, clock, capsys):
    code = main(argv, env=env_for(fake), clock=clock, require_https=False)
    return code, capsys.readouterr()


def test_a_refusal_writes_the_marker(fake, clock, tmp_path):
    fake.detail_override[EVENT] = (429, b"{}")

    with pytest.raises(Halt):
        run_download([EVENT], fake_config(fake), tmp_path, clock)

    marker = json.loads((tmp_path / HALT_MARKER).read_text())
    assert marker["event_id"] == EVENT
    assert "getDetailed" in marker["request"]
    assert "429" in marker["reason"]
    assert marker["time"] == clock.now().isoformat()


def test_a_bad_mp3_reply_names_the_mp3_request(fake, clock, tmp_path):
    fake.media_override[EVENT] = (403, b"no")

    with pytest.raises(Halt):
        run_download([EVENT], fake_config(fake), tmp_path, clock)

    marker = json.loads((tmp_path / HALT_MARKER).read_text())
    assert marker["event_id"] == EVENT and "MP3" in marker["request"] and "403" in marker["reason"]


def test_an_http_error_writes_the_marker(fake, clock, tmp_path):
    fake.detail_raw[EVENT] = b"this is not http\r\n\r\n"

    with pytest.raises(Halt):
        run_download([EVENT], fake_config(fake), tmp_path, clock)

    assert (tmp_path / HALT_MARKER).exists()


def test_a_damaged_record_writes_the_marker_and_requests_nothing(fake, clock, tmp_path):
    (tmp_path / "fetched.jsonl").write_text('{"event_id": "2026010009", "sha256": "ab')

    with pytest.raises(Halt):
        run_download([EVENT], fake_config(fake), tmp_path, clock)

    marker = json.loads((tmp_path / HALT_MARKER).read_text())
    assert "fetched.jsonl" in marker["request"] and "line 1" in marker["reason"]
    assert fake.seen == []


def test_the_next_run_refuses_and_sends_no_request(fake, clock, tmp_path):
    fake.detail_override[EVENT] = (429, b"{}")
    with pytest.raises(Halt):
        run_download([EVENT], fake_config(fake), tmp_path, clock)
    before = len(fake.seen)

    with pytest.raises(HaltMarkerPresent, match="429"):
        run_download(["2026010002"], fake_config(fake), tmp_path, clock)

    assert len(fake.seen) == before


def test_the_command_line_refuses_with_its_own_exit_code(fake, clock, tmp_path, capsys):
    fake.detail_override[EVENT] = (429, b"{}")
    assert cli(["download", "--approved-run", "--workdir", str(tmp_path), EVENT], fake, clock, capsys)[0] == 2
    before = len(fake.seen)

    code, out = cli(["download", "--approved-run", "--workdir", str(tmp_path), "2026010002"], fake, clock, capsys)

    assert code == 5
    assert "halt marker" in out.err and "--clear-halt" in out.err and "429" in out.err
    assert DUMMY_KEY not in out.err
    assert len(fake.seen) == before


def test_clear_halt_prints_and_removes_the_marker(fake, clock, tmp_path, capsys):
    fake.detail_override[EVENT] = (429, b"{}")
    cli(["download", "--approved-run", "--workdir", str(tmp_path), EVENT], fake, clock, capsys)
    before = len(fake.seen)

    code, out = cli(["download", "--clear-halt", "--workdir", str(tmp_path)], fake, clock, capsys)

    assert code == 0
    assert EVENT in out.out and "429" in out.out
    assert not (tmp_path / HALT_MARKER).exists()
    assert len(fake.seen) == before


def test_clear_halt_with_no_marker_says_so(fake, clock, tmp_path, capsys):
    code, out = cli(["download", "--clear-halt", "--workdir", str(tmp_path)], fake, clock, capsys)

    assert code == 0
    assert "no halt marker" in out.out.lower()


def test_a_run_after_clearing_proceeds(fake, clock, tmp_path, capsys):
    fake.detail_override[EVENT] = (429, b"{}")
    cli(["download", "--approved-run", "--workdir", str(tmp_path), EVENT], fake, clock, capsys)
    cli(["download", "--clear-halt", "--workdir", str(tmp_path)], fake, clock, capsys)
    del fake.detail_override[EVENT]

    code, out = cli(["download", "--approved-run", "--workdir", str(tmp_path), EVENT], fake, clock, capsys)

    assert code == 0
    assert (tmp_path / f"{EVENT}.mp3").exists()
    assert not (tmp_path / HALT_MARKER).exists()
