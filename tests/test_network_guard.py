"""CI enforces no network: the whole test session can connect only to 127.0.0.1 and ::1 (ADR-0051, CLAUDE.md)."""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from conftest import NetworkBlocked


@pytest.mark.parametrize(
    "family, address",
    [
        (socket.AF_INET, ("192.0.2.1", 80)),  # TEST-NET-1, reserved for documentation
        (socket.AF_INET, ("203.0.113.9", 443)),
        (socket.AF_INET6, ("2001:db8::1", 80, 0, 0)),
        (socket.AF_INET, ("example.invalid", 80)),
    ],
)
def test_a_connect_to_a_non_loopback_address_raises_loudly(family, address):
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        with pytest.raises(NetworkBlocked, match="blocked"):
            sock.connect(address)
        with pytest.raises(NetworkBlocked):
            sock.connect_ex(address)
    finally:
        sock.close()


def test_create_connection_to_a_non_loopback_address_raises_too():
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("198.51.100.7", 80), timeout=0.5)


def test_loopback_still_connects(fake):
    port = int(fake.base_url.rsplit(":", 1)[1])
    with socket.create_connection(("127.0.0.1", port), timeout=2):
        pass


def test_proxy_environment_variables_are_cleared_for_the_session():
    import os

    leftovers = [k for k in os.environ if k.lower() in {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}]
    assert leftovers == []


def test_ci_clears_the_proxy_variables():
    workflow = (Path(__file__).parent.parent / ".github" / "workflows" / "ci.yml").read_text()
    for var in ("http_proxy", "https_proxy", "all_proxy"):
        assert f'{var}: ""' in workflow
