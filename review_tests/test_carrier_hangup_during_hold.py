"""Regression probe for a carrier departure re-entering hold startup."""

from types import SimpleNamespace

import pytest

from livekit_telephony_service import RoomCredentials
from orchestrator import TransferOrchestrator
from transfer_state import TransferPhase


class Telephony:
    def __init__(self):
        self.config = SimpleNamespace(livekit_url="wss://example.invalid")
        self.dial_calls = []
        self.deleted_rooms = []

    async def create_room(self, **_kwargs):
        return RoomCredentials("room-2", "room-2-token")

    def issue_room_token(self, _room_name, _identity):
        return "hold-token"

    async def dial_phone(self, **kwargs):
        self.dial_calls.append(kwargs)
        return SimpleNamespace(
            identity=kwargs["participant_identity"],
            participant_id="broker-participant",
            provider_call_id="broker-call",
        )

    async def delete_room(self, room_name):
        self.deleted_rooms.append(room_name)


class CarrierLeavesInsideStartHold:
    def __init__(self, *, on_handoff_ended, **_kwargs):
        del on_handoff_ended
        self.orchestrator = None
        self.cleanup_calls = 0

    async def gate_primary_media(self, _gated):
        pass

    async def start_hold(self):
        # The production carrier callback can run before hold startup returns.
        await self.orchestrator.on_carrier_left_primary()

    async def cleanup(self):
        self.cleanup_calls += 1


class Room2Pipeline:
    def __init__(self, _state, _orchestrator):
        self.started = False
        self.stopped = False

    async def start(self, **_kwargs):
        self.started = True

    async def mark_broker_answered(self):
        pass

    async def wait_for_broker(self, _timeout):
        pass

    async def stop(self):
        self.stopped = True


class Notifier:
    async def notify(self, _message):
        pass


@pytest.mark.asyncio
async def test_carrier_hangup_during_start_hold_still_dials_and_leaks_pipeline():
    telephony = Telephony()
    media_instances = []
    pipeline_instances = []

    def media_factory(**kwargs):
        media = CarrierLeavesInsideStartHold(**kwargs)
        media_instances.append(media)
        return media

    def room2_factory(state, orchestrator):
        pipeline = Room2Pipeline(state, orchestrator)
        pipeline_instances.append(pipeline)
        return pipeline

    transfer = TransferOrchestrator(
        telephony=telephony,
        media_factory=media_factory,
        room2_factory=room2_factory,
        notifier=Notifier(),
    )
    media_or_context = SimpleNamespace(room_name="room-1")
    transfer.set_room1_references(
        room1_url="wss://example.invalid",
        room1_token="room-1-token",
        room1_name="room-1",
        task=SimpleNamespace(),
        context=media_or_context,
        context_aggregator=SimpleNamespace(
            _context=SimpleNamespace(messages=[])
        ),
        transport=SimpleNamespace(),
    )
    transfer.set_transfer_metadata(
        reason="needs broker",
        load_number="LOAD-1",
        human_phone_number="+14155550100",
    )

    # Complete the circular test wiring only after the real orchestrator exists.
    original_factory = transfer._media_factory

    def wired_media_factory(**kwargs):
        media = original_factory(**kwargs)
        media.orchestrator = transfer
        return media

    transfer._media_factory = wired_media_factory

    await transfer.execute_transfer_to_room2(
        None, None, None, None, None, None, None, None, None
    )

    pipeline = pipeline_instances[0]
    print(
        "observed:",
        f"dial_count={len(telephony.dial_calls)}",
        f"deleted_rooms={telephony.deleted_rooms}",
        f"phase={transfer.state.phase.value}",
        f"reason={transfer.state.terminal_reason}",
        f"room2_started={pipeline.started}",
        f"room2_stopped={pipeline.stopped}",
        f"room2_attached={transfer._room2_pipeline is pipeline}",
        f"media_cleanup_count={media_instances[0].cleanup_calls}",
    )

    # Current head resumes after start_hold despite terminal cancellation.
    assert len(telephony.dial_calls) == 1
    assert telephony.deleted_rooms == ["room-2"]
    assert transfer.is_transfer_in_progress() is False
    assert transfer.state.terminal_reason == "carrier_disconnected"
    assert transfer.state.phase is TransferPhase.CONSULTING

    # Cleanup ran before this pipeline was constructed, so it outlives the attempt.
    assert len(pipeline_instances) == 1
    assert pipeline_instances[0].started is True
    assert pipeline_instances[0].stopped is False
    assert transfer._room2_pipeline is pipeline_instances[0]
    assert media_instances[0].cleanup_calls == 1
