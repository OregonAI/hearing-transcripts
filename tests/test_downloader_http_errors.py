"""Every http.client error is a halt, printed as a halt, exit code 2 (ADR-0051: any unexpected reply halts)."""

from __future__ import annotations

import pytest

from conftest import DUMMY_KEY, fake_config
from fake_invintus import http_response
from hearing_transcripts.cli import main
from hearing_transcripts.download import Config, Halt, run_download

EVENT = "2026010001"
ID3_MP3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 32

REPLIES = {
    "a short body (IncompleteRead)": http_response(b'{"data": {', ctype="application/json", length=200),
    "a garbage status line (BadStatusLine)": b"this is not http\r\n\r\n",
    "an empty reply (RemoteDisconnected)": b"",
}


@pytest.mark.parametrize("raw", REPLIES.values(), ids=REPLIES.keys())
def test_getdetailed_http_client_errors_halt(raw, fake, clock, tmp_path):
    fake.detail_raw[EVENT] = raw

    with pytest.raises(Halt, match=EVENT):
        run_download([EVENT, "2026010002"], fake_config(fake), tmp_path, clock)

    assert fake.paths() == ["/Event/getDetailed"]


@pytest.mark.parametrize("raw", REPLIES.values(), ids=REPLIES.keys())
def test_mp3_http_client_errors_halt(raw, fake, clock, tmp_path):
    fake.media_raw[EVENT] = raw

    with pytest.raises(Halt, match=EVENT):
        run_download([EVENT, "2026010002"], fake_config(fake), tmp_path, clock)

    assert fake.paths() == ["/Event/getDetailed", f"/media/{EVENT}_audio.mp3"]


@pytest.mark.parametrize("raw", REPLIES.values(), ids=REPLIES.keys())
def test_the_command_line_prints_a_halt_and_exits_2(raw, fake, clock, tmp_path, capsys):
    fake.detail_raw[EVENT] = raw
    env = {"HEARING_API_BASE_URL": fake.base_url, "HEARING_EMBEDDER_KEY": DUMMY_KEY}

    code = main(["download", "--approved-run", "--workdir", str(tmp_path), EVENT], env=env, clock=clock, require_https=False)

    err = capsys.readouterr().err
    assert code == 2
    assert "HALTED" in err and "Waiting for the owner" in err
    assert DUMMY_KEY not in err
