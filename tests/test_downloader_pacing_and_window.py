"""Seam P1, slice 2: pacing and the 00:00-06:00 Pacific window, with an injected clock."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from conftest import DUMMY_KEY, PACIFIC, FakeClock
from hearing_transcripts.download import Config, Halt, OutsideWindow, run_download


def config(fake):
    return Config(base_url=fake.base_url, api_key=DUMMY_KEY)


def test_requests_are_three_seconds_apart(fake, clock, tmp_path):
    run_download(["2026010001", "2026010002"], config(fake), tmp_path, clock)

    assert len(fake.seen) == 4  # two requests for each event
    assert clock.sleeps == [3.0, 3.0, 3.0]  # before every request but the first


def test_the_first_request_of_a_run_does_not_wait(fake, clock, tmp_path):
    run_download(["2026010001"], config(fake), tmp_path, clock)

    assert clock.sleeps == [3.0]  # only between getDetailed and the MP3


def test_nothing_fetched_already_means_no_request_and_no_wait(fake, clock, tmp_path):
    run_download(["2026010001"], config(fake), tmp_path, clock)
    fake.seen.clear()
    clock.sleeps.clear()

    run_download(["2026010001"], config(fake), tmp_path, clock)

    assert fake.seen == []
    assert clock.sleeps == []


@pytest.mark.parametrize(
    "when",
    [
        datetime(2026, 11, 10, 6, 0, tzinfo=PACIFIC),  # 06:00 is the first moment outside
        datetime(2026, 11, 10, 12, 0, tzinfo=PACIFIC),
        datetime(2026, 11, 10, 23, 59, tzinfo=PACIFIC),
        datetime(2026, 11, 10, 14, 0, tzinfo=UTC),  # 06:00 PST, given in UTC
    ],
)
def test_outside_the_window_it_refuses_to_start(when, fake, tmp_path):
    with pytest.raises(OutsideWindow):
        run_download(["2026010001"], config(fake), tmp_path, FakeClock(when))

    assert fake.seen == []


@pytest.mark.parametrize(
    "when",
    [
        datetime(2026, 11, 10, 0, 0, tzinfo=PACIFIC),
        datetime(2026, 11, 10, 5, 59, tzinfo=PACIFIC),
        datetime(2026, 11, 10, 9, 59, tzinfo=UTC),  # 01:59 PST, given in UTC
    ],
)
def test_the_window_edges_are_inclusive_of_midnight_and_exclusive_of_six(when, fake, tmp_path):
    assert run_download(["2026010001"], config(fake), tmp_path, FakeClock(when)) == ["2026010001"]


def test_the_window_is_pacific_time_across_the_daylight_saving_change(fake, tmp_path):
    # 2026-03-09 is after the spring change: 08:30 UTC is 01:30 PDT, inside the window.
    inside = FakeClock(datetime(2026, 3, 9, 8, 30, tzinfo=UTC))
    assert run_download(["2026010001"], config(fake), tmp_path, inside) == ["2026010001"]
    outside = FakeClock(datetime(2026, 3, 9, 13, 30, tzinfo=UTC))  # 06:30 PDT
    with pytest.raises(OutsideWindow):
        run_download(["2026010002"], config(fake), tmp_path, outside)


def test_a_run_that_passes_six_stops_before_the_next_request(fake, tmp_path):
    # Starts at 05:59:50; the 3 s pauses carry it past 06:00 during the first event.
    clock = FakeClock(datetime(2026, 11, 10, 5, 59, 56, tzinfo=PACIFIC))

    with pytest.raises(OutsideWindow):
        run_download(["2026010001", "2026010002"], config(fake), tmp_path, clock)

    assert all(b"2026010002" not in s.body and "2026010002" not in s.path for s in fake.seen)
    assert (tmp_path / "2026010001.mp3").exists()
