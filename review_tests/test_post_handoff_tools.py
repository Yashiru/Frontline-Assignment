import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest

sys.path.insert(0, str(Path("/tmp/frontline-review/voice-agent")))

import call_helpers
from call_helpers import end_call, record_agreement
from pipecat.frames.frames import EndFrame


def post_handoff_context():
    # _complete_handoff leaves the primary context in TRANSFER_HOLD.
    return SimpleNamespace(
        call_mode="TRANSFER_HOLD",
        call_id=UUID("00000000-0000-0000-0000-000000000001"),
        load_uuid="00000000-0000-0000-0000-000000000002",
        load_context={"load_id": "LOAD-42"},
        caller_mc="123456",
        caller_phone="+15551234567",
    )


@pytest.mark.asyncio
async def test_end_call_is_not_blocked_after_handoff():
    context = post_handoff_context()
    callback = AsyncMock()
    task = SimpleNamespace(queue_frames=AsyncMock())

    await end_call(
        "end_call",
        "tool-1",
        {"reason": "agreement"},
        None,
        context,
        callback,
        task=task,
    )

    result = json.loads(callback.await_args.args[0])
    queued = task.queue_frames.await_args.args[0]
    print(f"call_mode={context.call_mode}")
    print(f"end_call_result={result}")
    print(f"queued_frame={type(queued[0]).__name__}")
    assert result["status"] == "success"
    assert context.end_reason == "agreement"
    assert isinstance(queued[0], EndFrame)


@pytest.mark.asyncio
async def test_record_agreement_and_kch_quote_are_not_blocked_after_handoff(monkeypatch):
    context = post_handoff_context()
    callback = AsyncMock()
    saved = Mock(return_value=UUID("00000000-0000-0000-0000-000000000003"))
    notified = Mock()
    monkeypatch.setattr(call_helpers, "save_agreement", saved)
    monkeypatch.setattr(
        call_helpers.NegotiationDBService, "notify_carrier_quote", notified
    )

    await record_agreement(
        "record_agreement",
        "tool-2",
        {"agreed_price": 2500},
        None,
        context,
        callback,
    )

    result = json.loads(callback.await_args.args[0])
    print(f"call_mode={context.call_mode}")
    print(f"record_agreement_result={result}")
    print(f"save_agreement_calls={saved.call_count}")
    print(f"notify_carrier_quote_calls={notified.call_count}")
    assert result["status"] == "success"
    saved.assert_called_once()
    notified.assert_called_once()
