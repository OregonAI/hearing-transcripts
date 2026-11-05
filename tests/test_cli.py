"""The command line reads the key and the base URL from the environment only."""

from __future__ import annotations

from conftest import DUMMY_KEY
from hearing_transcripts.cli import main


def run(argv, env, clock, capsys):
    code = main(argv, env=env, clock=clock, require_https=False)  # the fake speaks plain http
    return code, capsys.readouterr()


def test_without_the_key_it_refuses_and_asks_for_nothing(fake, clock, tmp_path, capsys):
    env = {"HEARING_API_BASE_URL": fake.base_url}
    code, out = run(["download", "--workdir", str(tmp_path), "2026010001"], env, clock, capsys)

    assert code != 0
    assert "HEARING_EMBEDDER_KEY" in out.err
    assert fake.seen == []


def test_without_the_base_url_it_refuses(fake, clock, tmp_path, capsys):
    code, out = run(["download", "--workdir", str(tmp_path), "2026010001"], {"HEARING_EMBEDDER_KEY": DUMMY_KEY}, clock, capsys)

    assert code != 0
    assert "HEARING_API_BASE_URL" in out.err
    assert fake.seen == []


def test_a_run_downloads_and_reports(fake, clock, tmp_path, capsys):
    env = {"HEARING_API_BASE_URL": fake.base_url, "HEARING_EMBEDDER_KEY": DUMMY_KEY}
    code, out = run(["download", "--workdir", str(tmp_path), "2026010001"], env, clock, capsys)

    assert code == 0
    assert "2026010001" in out.out
    assert (tmp_path / "2026010001.mp3").exists()


def test_a_halt_exits_nonzero_with_the_message_and_never_prints_the_key(fake, clock, tmp_path, capsys):
    fake.detail_override["2026010001"] = (429, b"{}")
    env = {"HEARING_API_BASE_URL": fake.base_url, "HEARING_EMBEDDER_KEY": DUMMY_KEY}
    code, out = run(["download", "--workdir", str(tmp_path), "2026010001"], env, clock, capsys)

    assert code == 2
    assert "429" in out.err
    assert DUMMY_KEY not in out.out + out.err


def test_the_window_refusal_exits_nonzero(fake, tmp_path, capsys):
    from datetime import datetime

    from conftest import PACIFIC, FakeClock

    env = {"HEARING_API_BASE_URL": fake.base_url, "HEARING_EMBEDDER_KEY": DUMMY_KEY}
    code, out = run(
        ["download", "--workdir", str(tmp_path), "2026010001"],
        env,
        FakeClock(datetime(2026, 11, 10, 15, 0, tzinfo=PACIFIC)),
        capsys,
    )

    assert code == 3
    assert "00:00" in out.err
    assert fake.seen == []
