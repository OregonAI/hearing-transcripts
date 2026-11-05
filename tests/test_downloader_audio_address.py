"""The audio address from getDetailed must be https and on the expected download host, or the run halts unrequested."""

from __future__ import annotations

import pytest

from conftest import DUMMY_KEY, fake_config
from hearing_transcripts.cli import main
from hearing_transcripts.download import DEFAULT_DOWNLOAD_HOST, Config, Halt, check_audio_url, run_download

EVENT = "2026010001"
# The shape the research note captured from the player's Download button (docs/research/hearing-video.md).
REAL_SHAPE = "https://m-download.invintus.com/4879615486/c1a6b888f62c6a9a843b8997c77f4e3195a391ed_audio.mp3"


def test_the_default_host_is_the_one_in_the_researched_mp3_url():
    assert DEFAULT_DOWNLOAD_HOST == "m-download.invintus.com"
    assert Config(base_url="https://api.example.test", api_key=DUMMY_KEY).download_host == DEFAULT_DOWNLOAD_HOST


def test_the_researched_url_shape_is_accepted_with_the_defaults():
    check_audio_url(REAL_SHAPE, Config(base_url="https://api.example.test", api_key=DUMMY_KEY), EVENT)  # no raise


@pytest.mark.parametrize(
    "url",
    [
        "http://m-download.invintus.com/4879615486/x_audio.mp3",  # right host, not https
        "https://other.example/4879615486/x_audio.mp3",  # https, wrong host
        "https://m-download.invintus.com.evil.example/x_audio.mp3",  # lookalike
        "https://m-download.invintus.com@evil.example/x_audio.mp3",  # userinfo trick
        "https://evil.example@m-download.invintus.com/x_audio.mp3",  # userinfo on the right host
        "https://m-download.invintus.com:8443/x_audio.mp3",  # other port
        "ftp://m-download.invintus.com/x_audio.mp3",
        "//m-download.invintus.com/x_audio.mp3",
        "/media/x_audio.mp3",
    ],
)
def test_other_addresses_halt(url):
    with pytest.raises(Halt, match=EVENT):
        check_audio_url(url, Config(base_url="https://api.example.test", api_key=DUMMY_KEY), EVENT)


def test_against_the_fake_the_default_config_halts_before_the_mp3_is_requested(fake, clock, tmp_path):
    config = Config(base_url=fake.base_url, api_key=DUMMY_KEY)  # defaults: https, m-download.invintus.com

    with pytest.raises(Halt, match="https|host"):
        run_download([EVENT], config, tmp_path, clock)

    assert fake.paths() == ["/Event/getDetailed"]


@pytest.mark.parametrize(
    "uri",
    [
        "https://evil.example/media/2026010001_audio.mp3",
        "http://127.0.0.1:1/media/2026010001_audio.mp3",  # loopback, but not the configured host:port
    ],
)
def test_a_wrong_host_halts_even_when_the_fake_allows_plain_http(uri, fake, clock, tmp_path):
    fake.audio_uri_override[EVENT] = uri

    with pytest.raises(Halt, match="host"):
        run_download([EVENT], fake_config(fake), tmp_path, clock)

    assert fake.paths() == ["/Event/getDetailed"]


def test_the_host_can_be_set_in_the_environment_and_the_halt_names_it(fake, clock, tmp_path, capsys):
    env = {
        "HEARING_API_BASE_URL": fake.base_url,
        "HEARING_EMBEDDER_KEY": DUMMY_KEY,
        "HEARING_DOWNLOAD_HOST": "downloads.example.test",
    }

    code = main(["download", "--workdir", str(tmp_path), EVENT], env=env, clock=clock, require_https=False)

    err = capsys.readouterr().err
    assert code == 2
    assert "downloads.example.test" in err
    assert fake.paths() == ["/Event/getDetailed"]
