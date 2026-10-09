"""Recording fakes shared by handler and conversation evaluations."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

class RecordingCallback:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, result: str, **kwargs: Any) -> None:
        self.calls.append({"result": json.loads(result), "kwargs": kwargs})

    @property
    def last(self) -> dict[str, Any]:
        return self.calls[-1]["result"]


class RecordingTask:
    def __init__(self) -> None:
        self.frames: list[Any] = []

    async def queue_frames(self, frames: list[Any]) -> None:
        self.frames.extend(frames)


class RecordingBackends:
    def __init__(self, loads: dict[str, dict[str, Any]] | None = None) -> None:
        self.loads = loads or {}
        self.events: list[tuple[str, Any]] = []
        self.next_negotiation_id = "00000000-0000-0000-0000-000000000001"

    def get_load_by_reference(self, reference: str, org_id: str | None = None):
        self.events.append(("get_load_by_reference", {"reference": reference, "org_id": org_id}))
        return self.loads.get(reference)

    def update_call_load(self, call_id: Any, load_id: Any) -> None:
        self.events.append(("update_call_load", {"call_id": call_id, "load_id": load_id}))

    def update_call_mc(self, call_id: Any, mc_number: str) -> None:
        self.events.append(("update_call_mc", {"call_id": call_id, "mc_number": mc_number}))

    def save_agreement(self, *args: Any, **kwargs: Any):
        self.events.append(("save_agreement", {"args": args, "kwargs": kwargs}))
        from uuid import UUID

        return UUID(self.next_negotiation_id)

    def notify_carrier_quote(self, **kwargs: Any) -> None:
        self.events.append(("notify_carrier_quote", kwargs))


def context(**overrides: Any) -> SimpleNamespace:
    defaults = {
        "messages": [{"role": "system", "content": "initial"}],
        "call_id": "00000000-0000-0000-0000-000000000010",
        "org_id": "org-test",
        "caller_phone": "+15555550100",
        "call_mode": "BOT_ACTIVE",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)
