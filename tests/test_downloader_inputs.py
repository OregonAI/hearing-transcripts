"""Inputs that must fail closed: event IDs, the record file, and what repr() shows."""

from __future__ import annotations

import json

import pytest

from conftest import DUMMY_KEY, fake_config
from hearing_transcripts.cli import main
from hearing_transcripts.download import Config, Halt, InvalidEventId, RecordCorrupt, run_download


def config(fake):
    return fake_config(fake)


def test_repr_of_config_hides_the_key():
    text = repr(Config(base_url="https://api.example.test", api_key=DUMMY_KEY))

    assert DUMMY_KEY not in text
    assert "api_key" not in text
    assert "https://api.example.test" in text


@pytest.mark.parametrize(
    "bad",
    ["", "../etc/passwd", "2026/01", "2026010001.mp3", "12a", "-5", " 2026010001", "2026010001\n", "２０２６０１０００１", "20260100\x00"],
)
def test_event_ids_must_be_digits_only(bad, fake, clock, tmp_path):
    with pytest.raises(InvalidEventId):
        run_download(["2026010001", bad], config(fake), tmp_path, clock)

    assert fake.seen == []  # checked before the first request, so nothing is fetched for the good one either
    assert list(tmp_path.iterdir()) == []


def test_the_command_line_refuses_a_bad_event_id_with_exit_1(fake, clock, tmp_path, capsys):
    env = {"HEARING_API_BASE_URL": fake.base_url, "HEARING_EMBEDDER_KEY": DUMMY_KEY}

    code = main(["download", "--approved-run", "--workdir", str(tmp_path), "../x"], env=env, clock=clock)

    assert code == 1
    assert "../x" in capsys.readouterr().err
    assert fake.seen == []


def write_record(tmp_path, text):
    (tmp_path / "fetched.jsonl").write_text(text)


GOOD = json.dumps({"event_id": "2026010001", "sha256": "0" * 64, "bytes": 5}) + "\n"


@pytest.mark.parametrize(
    "text, line",
    [
        (GOOD + '{"event_id": "2026010002", "sha2', 2),  # torn last line
        (GOOD + "not json\n", 2),
        (GOOD + "[1, 2]\n", 2),  # valid JSON, not a record
        (GOOD + '{"sha256": "x"}\n', 2),  # no event_id
        ('{"event_id": ', 1),
    ],
)
def test_a_damaged_record_file_refuses_to_run_and_names_the_line(text, line, fake, clock, tmp_path):
    write_record(tmp_path, text)

    with pytest.raises(RecordCorrupt, match=rf"fetched\.jsonl.*line {line}\b"):
        run_download(["2026010003"], config(fake), tmp_path, clock)

    assert fake.seen == []
    assert (tmp_path / "fetched.jsonl").read_text() == text  # left exactly as found, for the owner


def test_a_damaged_record_file_is_a_halt_with_exit_2(fake, clock, tmp_path, capsys):
    write_record(tmp_path, GOOD + '{"event_id": "20')
    env = {"HEARING_API_BASE_URL": fake.base_url, "HEARING_EMBEDDER_KEY": DUMMY_KEY}

    code = main(["download", "--approved-run", "--workdir", str(tmp_path), "2026010003"], env=env, clock=clock, require_https=False)

    err = capsys.readouterr().err
    assert code == 2
    assert "line 2" in err and "HALTED" in err
    assert issubclass(RecordCorrupt, Halt)


def test_an_intact_record_file_still_skips_what_it_lists(fake, clock, tmp_path):
    write_record(tmp_path, GOOD + "\n")  # a blank line is harmless

    assert run_download(["2026010001"], config(fake), tmp_path, clock) == []
    assert fake.seen == []
