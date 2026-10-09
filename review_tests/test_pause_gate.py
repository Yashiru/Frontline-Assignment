import asyncio

import pytest

from pipecat.frames.frames import EndFrame, InputAudioRawFrame, StartFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.transports.base_input import BaseInputTransport
from pipecat.transports.base_transport import TransportParams


class RealInputTransport(BaseInputTransport):
    """Use BaseInputTransport's real queue/task and pause implementation."""

    async def start(self, frame):
        await super().start(frame)
        await self.set_transport_ready(frame)


class CaptureProcessor(FrameProcessor):
    def __init__(self):
        super().__init__()
        self.audio_frames = []
        self.audio_received = asyncio.Event()
        self.started = asyncio.Event()

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, StartFrame):
            self.started.set()
        if isinstance(frame, InputAudioRawFrame):
            self.audio_frames.append(frame)
            self.audio_received.set()
        await self.push_frame(frame, direction)


@pytest.mark.asyncio
async def test_pause_processing_frames_does_not_gate_system_audio():
    transport = RealInputTransport(
        params=TransportParams(
            audio_in_enabled=True,
            audio_in_passthrough=True,
            audio_in_sample_rate=8000,
            audio_in_channels=1,
        )
    )
    capture = CaptureProcessor()
    task = PipelineTask(Pipeline([transport, capture]))
    run_task = asyncio.create_task(PipelineRunner().run(task))
    try:
        await asyncio.wait_for(capture.started.wait(), timeout=1)
        await transport.pause_processing_frames()
        frame = InputAudioRawFrame(
            audio=b"\x01\x00" * 80,
            sample_rate=8000,
            num_channels=1,
        )
        print(f"frame_class={type(frame).__name__} mro={frame.__class__.__mro__}")
        print(f"transport_paused_flag={transport._paused}")
        await transport.push_audio_frame(frame)

        await asyncio.wait_for(capture.audio_received.wait(), timeout=1)
        print(f"captured_while_process_frames_paused={len(capture.audio_frames)}")
        assert capture.audio_frames == [frame]
    finally:
        if not run_task.done():
            await transport.resume_processing_frames()
            await task.queue_frame(EndFrame())
        await asyncio.wait_for(run_task, timeout=2)
