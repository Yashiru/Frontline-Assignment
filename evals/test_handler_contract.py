"""L2 contracts for the production voice-agent tool handlers.

All external boundaries are recording fakes.  These tests deliberately invoke
the real async handlers and therefore exercise their validation, state changes,
prompt construction, and scheduling behavior without credentials or I/O.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID

import pytest
from pipecat.frames.frames import EndFrame

import call_helpers
import transfer_tool_handler
from call_helpers import end_call, get_load_context, record_agreement, verify_carrier
from evals.fakes import RecordingBackends, RecordingCallback, RecordingTask, context
from transfer_tool_handler import TransferToolHandler


LOAD_UUID = "00000000-0000-0000-0000-000000000101"
CALL_UUID = "00000000-0000-0000-0000-000000000010"
NEGOTIATION_UUID = "00000000-0000-0000-0000-000000000001"


def _priced_load(**overrides):
    load = {
        "id": LOAD_UUID,
        "load_id": "LOAD-1001",
        "origin_city": "Atlanta",
        "origin_state": "GA",
        "destination_city": "Chicago",
        "destination_state": "IL",
        "start_rate": 1400,
        "book_now_rate": 1600,
        "max_rate": 1800,
        "carrier_sales_rep_phone": "+12058752486",
    }
    load.update(overrides)
    return load


@pytest.mark.asyncio
async def test_verify_carrier_stages_identity_without_claiming_confirmation(monkeypatch):
    async def fake_fetch(mc_number):
        assert mc_number == "123456"
        return {"data": {"legalName": "Reliable Freight", "dotNumber": 98765}}

    updated = []
    monkeypatch.setattr(call_helpers, "fetch_carrier_by_mc", fake_fetch)
    monkeypatch.setattr(
        call_helpers, "get_carrier_name", lambda payload: payload["data"]["legalName"]
    )
    monkeypatch.setattr(
        call_helpers, "update_call_mc", lambda call_id, mc: updated.append((call_id, mc))
    )
    ctx = context(carrier_identity_confirmed=True)
    callback = RecordingCallback()

    await verify_carrier(
        "verify_carrier", "tool-1", {"mc_number": " 123456 "}, None, ctx, callback
    )

    assert callback.last == {
        "status": "success",
        "message": "Carrier found: Reliable Freight",
        "carrier_name": "Reliable Freight",
        "mc_number": "123456",
    }
    assert updated == [(CALL_UUID, "123456")]
    assert (ctx.caller_mc, ctx.carrier_name, ctx.caller_dot_number) == (
        "123456",
        "Reliable Freight",
        "98765",
    )
    assert ctx.identity_source == "verify_carrier"
    assert ctx.carrier_identity_confirmed is False
    assert ctx.awaiting_carrier_identity_confirmation is True


@pytest.mark.asyncio
async def test_get_load_context_replaces_prompt_and_stores_normalized_load(monkeypatch):
    backend = RecordingBackends({"LOAD-1001": _priced_load()})
    monkeypatch.setattr(
        call_helpers.NegotiationDBService,
        "get_load_by_reference",
        backend.get_load_by_reference,
    )
    monkeypatch.setattr(call_helpers, "update_call_load", backend.update_call_load)
    ctx = context()
    original_message = ctx.messages[0]
    callback = RecordingCallback()

    await get_load_context(
        "get_load_context",
        "tool-2",
        {"load_id": "LOAD-1001"},
        None,
        ctx,
        callback,
        caller_phone="+15555550199",
    )

    assert callback.last["status"] == "success"
    assert ctx.messages[0] is not original_message
    assert ctx.messages[0]["role"] == "system"
    assert ctx.messages[0]["content"] != "initial"
    assert "LOAD-1001" in ctx.messages[0]["content"]
    assert ctx.load_uuid == LOAD_UUID
    assert ctx.load_context["maxRate"] == 1800.0
    assert ctx.caller_phone == "+15555550199"
    assert backend.events == [
        ("get_load_by_reference", {"reference": "LOAD-1001", "org_id": "org-test"}),
        ("update_call_load", {"call_id": CALL_UUID, "load_id": LOAD_UUID}),
    ]


@pytest.mark.asyncio
async def test_record_agreement_persists_exact_arguments_and_notifies(monkeypatch):
    backend = RecordingBackends()
    monkeypatch.setattr(call_helpers, "save_agreement", backend.save_agreement)
    monkeypatch.setattr(
        call_helpers.NegotiationDBService,
        "notify_carrier_quote",
        backend.notify_carrier_quote,
    )
    ctx = context(
        load_uuid=LOAD_UUID,
        load_context={"load_id": "LOAD-1001", "maxRate": 1800.0},
        caller_mc="123456",
    )
    callback = RecordingCallback()

    await record_agreement(
        "record_agreement",
        "tool-3",
        {
            "agreed_price": "1750.50",
            "above_max": False,
            "carrier_contact_name": "Pat Driver",
            "carrier_contact_phone": "+15555550123",
        },
        None,
        ctx,
        callback,
    )

    assert callback.last == {
        "status": "success",
        "message": "Agreement recorded at $1750.5",
        "negotiation_id": NEGOTIATION_UUID,
    }
    assert backend.events == [
        (
            "save_agreement",
            {
                "args": (
                    LOAD_UUID,
                    1750.5,
                    CALL_UUID,
                    False,
                    "Pat Driver",
                    "+15555550123",
                ),
                "kwargs": {},
            },
        ),
        (
            "notify_carrier_quote",
            {
                "load_name": "LOAD-1001",
                "agreed_price": 1750.5,
                "mc_number": "123456",
                "source_type": "call",
                "carrier_name": "Pat Driver",
                "carrier_phone": "+15555550123",
            },
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("price", [None, "not-a-price"])
async def test_record_agreement_rejects_missing_or_invalid_price(monkeypatch, price):
    backend = RecordingBackends()
    monkeypatch.setattr(call_helpers, "save_agreement", backend.save_agreement)
    callback = RecordingCallback()

    await record_agreement(
        "record_agreement",
        "tool-invalid",
        {"agreed_price": price},
        None,
        context(load_uuid=LOAD_UUID),
        callback,
    )

    assert callback.last["status"] == "error"
    assert backend.events == []


@pytest.mark.asyncio
async def test_record_above_max_requires_contact_name_and_phone(monkeypatch):
    backend = RecordingBackends()
    monkeypatch.setattr(call_helpers, "save_agreement", backend.save_agreement)
    callback = RecordingCallback()

    await record_agreement(
        "record_agreement",
        "tool-invalid",
        {"agreed_price": 1900, "above_max": True},
        None,
        context(load_uuid=LOAD_UUID, caller_phone=None),
        callback,
    )

    assert callback.last["status"] == "error"
    assert "contact name and phone" in callback.last["message"]
    assert backend.events == []


@pytest.mark.asyncio
async def test_end_call_human_only_guard_has_no_state_or_frame_side_effects():
    ctx = context(call_mode="HUMAN_ONLY", end_reason="existing")
    callback, task = RecordingCallback(), RecordingTask()

    await end_call(
        "end_call", "tool-4", {"reason": "agreement"}, None, ctx, callback, task
    )

    assert callback.last["status"] == "ignored"
    assert ctx.end_reason == "existing"
    assert task.frames == []


@pytest.mark.asyncio
async def test_end_call_sets_state_and_queues_exactly_one_end_frame():
    ctx = context()
    callback, task = RecordingCallback(), RecordingTask()

    await end_call(
        "end_call", "tool-5", {"reason": "agreement"}, None, ctx, callback, task
    )

    assert callback.last == {
        "status": "success",
        "message": "Call ending with reason: agreement",
    }
    assert ctx.end_reason == "agreement"
    assert len(task.frames) == 1
    assert isinstance(task.frames[0], EndFrame)


class _SpeechSync:
    def __init__(self):
        self.callbacks = []

    async def schedule_after_speech(self, callback):
        self.callbacks.append(callback)


def _transfer_handler():
    orchestrator = MagicMock()
    speech_sync = _SpeechSync()
    handler = TransferToolHandler(
        orchestrator=orchestrator,
        http_session=object(),
        stt=object(),
        tts=object(),
        llm=object(),
        skip_tts_processor=object(),
        transcript=object(),
        speech_sync=speech_sync,
        audiobuffer=object(),
        context_aggregator=object(),
    )
    return handler, orchestrator, speech_sync


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("ctx", "raw_load", "message_fragment"),
    [
        (SimpleNamespace(), None, "load reference"),
        (SimpleNamespace(load_uuid=LOAD_UUID), None, "load could not be found"),
        (SimpleNamespace(load_uuid=LOAD_UUID), _priced_load(carrier_sales_rep_phone=None), "no broker transfer number"),
    ],
)
async def test_transfer_requires_loaded_load_and_configured_routing(
    monkeypatch, ctx, raw_load, message_fragment
):
    monkeypatch.setattr(
        transfer_tool_handler.NegotiationDBService, "get_load", lambda unused: raw_load
    )
    handler, orchestrator, speech_sync = _transfer_handler()
    callback = RecordingCallback()

    await handler.handle_transfer_to_human(
        "transfer_to_human",
        "tool-6",
        {"reason": "carrier requested", "load_number": "LOAD-1001"},
        None,
        ctx,
        callback,
    )

    assert callback.last["status"] == "error"
    assert message_fragment in callback.last["message"].lower()
    orchestrator.set_transfer_metadata.assert_not_called()
    assert speech_sync.callbacks == []


@pytest.mark.asyncio
async def test_transfer_sets_exact_routing_metadata_and_schedules(monkeypatch):
    monkeypatch.setattr(
        transfer_tool_handler.NegotiationDBService,
        "get_load",
        lambda load_uuid: _priced_load(),
    )
    handler, orchestrator, speech_sync = _transfer_handler()
    callback = RecordingCallback()
    args = {
        "reason": "carrier requested",
        "load_number": "LOAD-1001",
        "price_asked_by_carrier": 1900,
        "best_price_offered_by_bot": 1800,
    }

    await handler.handle_transfer_to_human(
        "transfer_to_human",
        "tool-7",
        args,
        None,
        SimpleNamespace(load_uuid=LOAD_UUID, carrier_identity_confirmed=True),
        callback,
    )

    assert callback.last["status"] == "transferring"
    orchestrator.set_transfer_metadata.assert_called_once_with(
        reason="carrier requested",
        load_number="LOAD-1001",
        price_asked_by_carrier=1900,
        best_price_offered_by_bot=1800,
        human_phone_number="+12058752486",
    )
    assert len(speech_sync.callbacks) == 1
    assert callable(speech_sync.callbacks[0])


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="F1: record_agreement has no runtime ceiling/above_max consistency enforcement",
)
async def test_f1_agreement_above_ceiling_is_rejected(monkeypatch):
    backend = RecordingBackends()
    monkeypatch.setattr(call_helpers, "save_agreement", backend.save_agreement)
    monkeypatch.setattr(
        call_helpers.NegotiationDBService, "notify_carrier_quote", lambda **kwargs: None
    )
    callback = RecordingCallback()

    await record_agreement(
        "record_agreement",
        "tool-f1",
        {"agreed_price": 1801, "above_max": False},
        None,
        context(load_uuid=LOAD_UUID, load_context={"maxRate": 1800}),
        callback,
    )

    assert callback.last["status"] == "error"
    assert backend.events == []


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="F3: transfer handler does not verify carrier identity before routing",
)
async def test_f3_transfer_requires_verified_carrier(monkeypatch):
    monkeypatch.setattr(
        transfer_tool_handler.NegotiationDBService,
        "get_load",
        lambda load_uuid: _priced_load(),
    )
    handler, orchestrator, speech_sync = _transfer_handler()
    callback = RecordingCallback()

    await handler.handle_transfer_to_human(
        "transfer_to_human",
        "tool-f3",
        {"reason": "carrier requested", "load_number": "LOAD-1001"},
        None,
        SimpleNamespace(load_uuid=LOAD_UUID, carrier_identity_confirmed=False),
        callback,
    )

    assert callback.last["status"] == "error"
    orchestrator.set_transfer_metadata.assert_not_called()
    assert speech_sync.callbacks == []
