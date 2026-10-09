import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


VOICE_AGENT = Path("/tmp/frontline-review/voice-agent")
sys.path.insert(0, str(VOICE_AGENT))

from livekit_telephony_service import (  # noqa: E402
    LiveKitTelephonyService,
    ParticipantMoveOutcomeUnknown,
)
from livekit_transfer_media import (  # noqa: E402
    LiveKitTransferMedia,
    PrimaryMediaBinding,
)
from orchestrator import TransferOrchestrator  # noqa: E402
from telephony_config import LiveKitTelephonyConfig  # noqa: E402
from transfer_state import TransferPhase  # noqa: E402


class NeitherRoomGateway:
    """Provider boundary where a submitted move leaves no observable participant."""

    def __init__(self):
        self.calls = []

    async def move_participant(self, **kwargs):
        self.calls.append(("move", kwargs))

    async def participant_exists(self, **kwargs):
        self.calls.append(("exists", kwargs))
        return False

    async def delete_room(self, room_name):
        self.calls.append(("delete", room_name))

    async def remove_participant(self, **kwargs):
        self.calls.append(("remove", kwargs))


class RecordingTask:
    def __init__(self):
        self.frames = []
        self.cancelled = False

    async def queue_frame(self, frame):
        self.frames.append(frame)

    async def cancel(self):
        self.cancelled = True


class LocalParticipant:
    def __init__(self):
        self.unpublished = []

    async def unpublish_track(self, sid):
        self.unpublished.append(sid)


def config():
    return LiveKitTelephonyConfig(
        livekit_url="wss://test.livekit.cloud",
        livekit_api_key="test-key",
        livekit_api_secret="test-secret",
        livekit_inbound_trunk_id="inbound",
        livekit_dispatch_rule_id="dispatch",
        livekit_outbound_trunk_id="outbound",
        livekit_outbound_number="+14155550199",
    )


@pytest.mark.asyncio
async def test_neither_room_is_quarantined_without_bounded_call_cleanup(monkeypatch):
    monkeypatch.setenv("LIVEKIT_TRANSFER_ARRIVAL_TIMEOUT_SECONDS", "0.01")
    gateway = NeitherRoomGateway()
    telephony = LiveKitTelephonyService(config=config(), gateway=gateway)

    primary_task = RecordingTask()
    primary_local = LocalParticipant()
    primary_input = SimpleNamespace(
        pause_processing_frames=AsyncMock(), resume_processing_frames=AsyncMock()
    )
    primary_transport = SimpleNamespace(
        input=lambda: primary_input,
        _client=SimpleNamespace(
            _audio_track=SimpleNamespace(sid="TR_primary"),
            room=SimpleNamespace(local_participant=primary_local),
        ),
    )
    primary_context = SimpleNamespace(skip_tts=True, call_mode="TRANSFER_HOLD")
    media = LiveKitTransferMedia(
        primary=PrimaryMediaBinding(
            room_name="Room1",
            room_url="wss://test.livekit.cloud",
            task=primary_task,
            context=primary_context,
            transport=primary_transport,
        ),
        hold_token="hold-token",
    )

    # Model an already-running hold publisher without connecting to LiveKit.
    hold_task = RecordingTask()
    hold_local = LocalParticipant()
    media._hold_task = hold_task
    media._hold_transport = SimpleNamespace(
        _client=SimpleNamespace(
            _audio_track=SimpleNamespace(sid="TR_hold"),
            room=SimpleNamespace(local_participant=hold_local),
        )
    )
    media._primary_media_gated = True

    orchestrator = TransferOrchestrator(telephony=telephony)
    orchestrator._media = media
    orchestrator._room2_pipeline = SimpleNamespace(stop=AsyncMock())
    orchestrator._mark_transfer_started()
    orchestrator.state.room1_name = "Room1"
    orchestrator.state.room2_name = "Room2"
    orchestrator.state.human_participant_identity = "broker-1"
    orchestrator.state.transition(TransferPhase.CONSULTING)

    print(f"phase_before={orchestrator.state.phase.value}")
    await asyncio.wait_for(
        orchestrator.execute_transfer_human_to_room1(None), timeout=0.25
    )
    print(f"phase_after={orchestrator.state.phase.value}")
    print(f"terminal_reason={orchestrator.state.terminal_reason}")
    print(f"gateway_calls={gateway.calls}")
    print(f"primary_input_resumed={primary_input.resume_processing_frames.await_count}")
    print(f"primary_pipeline_cancelled={primary_task.cancelled}")
    print(f"hold_observer_retained={media._handoff_observer}")
    print(f"hold_task_still_owned={media._hold_task is hold_task}")

    assert orchestrator.state.phase is TransferPhase.FAILED
    assert orchestrator.state.terminal_reason == "handoff_outcome_unknown"
    assert primary_input.resume_processing_frames.await_count == 0
    assert primary_task.cancelled is False
    assert media._handoff_observer is True
    assert media._hold_task is hold_task
    assert ("delete", "Room2") in gateway.calls

    # No deadline or follow-up reconciliation owns the retained observer/Room1.
    await asyncio.sleep(0.02)
    room1_deleted = ("delete", "Room1") in gateway.calls
    print(f"room1_deleted_after_bounded_wait={room1_deleted}")
    assert room1_deleted is False

    # Explicit teardown keeps this review test from leaving synthetic resources.
    await media.stop_hold(retain_observer=False)
    assert hold_task.cancelled is True
