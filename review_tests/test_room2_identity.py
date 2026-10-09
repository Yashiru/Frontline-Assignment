import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

VOICE_AGENT = Path("/tmp/frontline-review/voice-agent")
sys.path.insert(0, str(VOICE_AGENT))

from room2_pipeline_service import Room2PipelineService
from transfer_state import TransferState


class IdentityKeyedTransport:
    """Match livekit.rtc.Room.remote_participants: keys are identities."""

    def __init__(self):
        self.handlers = {}
        participant = SimpleNamespace(identity="broker-expected", sid="PA_broker")
        self._client = SimpleNamespace(
            room=SimpleNamespace(
                remote_participants={"broker-expected": participant}
            )
        )

    def event_handler(self, name):
        def register(handler):
            self.handlers[name] = handler
            return handler
        return register

    async def get_participant_metadata(self, participant_id):
        participant = self._client.room.remote_participants.get(participant_id)
        if participant is None:
            return {}
        return {"id": participant.sid, "name": participant.identity}


@pytest.mark.asyncio
async def test_real_identity_keying_rejects_expected_broker_sid():
    state = TransferState(human_participant_identity="broker-expected")
    orchestrator = SimpleNamespace(on_broker_left_consultation=AsyncMock())
    service = Room2PipelineService(state, orchestrator)
    service._transport = IdentityKeyedTransport()
    service._context = SimpleNamespace(session_id=None)
    service._task = SimpleNamespace(queue_frames=AsyncMock(), cancel=AsyncMock())
    service._audiobuffer = SimpleNamespace(
        start_recording=AsyncMock(), stop_recording=AsyncMock()
    )
    service._setup_room2_events()

    await service.mark_broker_answered()
    await service._transport.handlers["on_participant_connected"](
        service._transport, "PA_broker"
    )
    await service._transport.handlers["on_audio_track_subscribed"](
        service._transport, "PA_broker"
    )

    print(f"remote_participant_keys={list(service._transport._client.room.remote_participants)}")
    print(f"callback_participant_id=PA_broker")
    print(f"broker_connected={service._broker_connected.is_set()}")
    print(f"broker_media_ready={service._broker_media_ready.is_set()}")
    print(f"opening_started={service._opening_started}")
    assert service._broker_connected.is_set() is False
    assert service._broker_media_ready.is_set() is False
    assert service._opening_started is False

    with pytest.raises(asyncio.TimeoutError):
        await service.wait_for_broker(timeout=0.01)
    print("wait_for_broker=TimeoutError")
