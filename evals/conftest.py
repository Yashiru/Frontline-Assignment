"""Global safety controls for evaluations."""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
VOICE_AGENT = ROOT / "voice-agent"
if str(VOICE_AGENT) not in sys.path:
    sys.path.insert(0, str(VOICE_AGENT))

CREDENTIAL_ENV_VARS = (
    "OPENAI_API_KEY",
    "DEEPGRAM_API_KEY",
    "CARTESIA_API_KEY",
    "DAILY_API_KEY",
    "SUPABASE_URL",
    "SUPABASE_SERVICE_ROLE_KEY",
    "HIGHWAY_API_KEY",
    "SLACK_WEBHOOK_URL",
    "KCH_QUOTE_CLIENT_ID",
    "KCH_QUOTE_CLIENT_SECRET",
    "SALESFORCE_CLIENT_ID",
    "SALESFORCE_CLIENT_SECRET",
)


def _blocked_connection(*args, **kwargs):
    raise RuntimeError("outbound network is disabled during evaluations")


# Fail closed before test-module collection: importing application modules must
# not be able to observe credentials or open a connection either.
for _name in CREDENTIAL_ENV_VARS:
    os.environ.pop(_name, None)
socket.create_connection = _blocked_connection
socket.socket.connect = _blocked_connection
socket.socket.connect_ex = _blocked_connection


@pytest.fixture(autouse=True)
def isolate_evaluation(monkeypatch):
    """Remove credentials and fail closed on every outbound socket attempt."""
    for name in CREDENTIAL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(socket, "create_connection", _blocked_connection)
    monkeypatch.setattr(socket.socket, "connect", _blocked_connection)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked_connection)
    yield
