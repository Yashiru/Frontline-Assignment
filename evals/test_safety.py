"""Proof that evaluation safety controls fail closed."""

import os
import socket

import pytest

from evals.conftest import CREDENTIAL_ENV_VARS


def test_credentials_are_absent() -> None:
    assert all(name not in os.environ for name in CREDENTIAL_ENV_VARS)


def test_outbound_socket_is_blocked() -> None:
    with pytest.raises(RuntimeError, match="outbound network is disabled"):
        socket.create_connection(("example.invalid", 443))
