"""Q3 (owner, 2026-11-05): every downloading run needs --approved-run; without it the tool refuses and sends no request."""

from __future__ import annotations

from conftest import DUMMY_KEY


def test_without_the_flag_it_refuses_with_its_own_exit_code_and_sends_nothing(fake, clock, tmp_path, capsys):
    from hearing_transcripts.cli import main

    env = {"HEARING_API_BASE_URL": fake.base_url, "HEARING_EMBEDDER_KEY": DUMMY_KEY, "HEARING_DOWNLOAD_HOST": fake.download_host}
    code = main(["download", "--workdir", str(tmp_path), "2026010001"], env=env, clock=clock, require_https=False)

    err = capsys.readouterr().err
    assert code == 4
    assert "--approved-run" in err
    assert fake.seen == []
    assert not (tmp_path / "2026010001.mp3").exists()


def test_with_the_flag_it_runs(fake, clock, tmp_path, capsys):
    from hearing_transcripts.cli import main

    env = {"HEARING_API_BASE_URL": fake.base_url, "HEARING_EMBEDDER_KEY": DUMMY_KEY, "HEARING_DOWNLOAD_HOST": fake.download_host}
    code = main(["download", "--approved-run", "--workdir", str(tmp_path), "2026010001"], env=env, clock=clock, require_https=False)

    assert code == 0
    assert (tmp_path / "2026010001.mp3").exists()
