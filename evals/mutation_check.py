"""Prove that the L1 prompt contract detects high-risk prompt mutations.

This check patches the real prompt builder's imported section functions in
memory.  It never rewrites application source and restores each patch before
trying the next mutation.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Callable
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
VOICE_AGENT = ROOT / "voice-agent"
for path in (ROOT, VOICE_AGENT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import voice_prompt
from evals.test_prompt_contract import LOAD_CASES, normalize_load_data, test_prompt_contract_matrix


Contract = Callable[[], None]


def _run_l1_contract() -> None:
    """Exercise the priced/unknown row containing all mutated invariants."""
    test_prompt_contract_matrix("priced", "unknown")
    prompt = voice_prompt.build_full_negotiation_prompt(
        normalize_load_data(LOAD_CASES["priced"])
    )
    assert "FORBIDDEN DOLLAR AMOUNTS" in prompt


def _drop_forbidden_amounts(rendered: str) -> str:
    return re.sub(
        r"\nFORBIDDEN DOLLAR AMOUNTS\b.*?(?=\nIf you need to counter-offer)",
        "\n",
        rendered,
        count=1,
        flags=re.DOTALL,
    )


def _drop_internal_ceiling(rendered: str) -> str:
    return re.sub(r"(?m)^- Internal Ceiling:.*\n?", "", rendered, count=1)


def _drop_zone1_never_counter_higher(rendered: str) -> str:
    return rendered.replace(
        "→ CRITICAL RULE: NEVER counter with a rate HIGHER than the carrier's bid. "
        "This overrides all other rules.\n",
        "",
        1,
    )


def _prove_mutation(
    name: str,
    target_name: str,
    mutate: Callable[[str], str],
    removed_marker: str,
) -> bool:
    original = getattr(voice_prompt, target_name)

    def mutated(*args, **kwargs):
        before = original(*args, **kwargs)
        after = mutate(before)
        if after == before or removed_marker in after:
            raise RuntimeError(f"mutation was not applied: {name}")
        return after

    try:
        with patch.object(voice_prompt, target_name, mutated):
            _run_l1_contract()
    except AssertionError:
        print(f"DETECTED: {name} -> L1 contract failed")
        return True
    except Exception as exc:
        print(f"ERROR: {name} -> {type(exc).__name__}: {exc}")
        return False

    print(f"MISSED: {name} -> L1 contract unexpectedly passed")
    return False


def main() -> int:
    try:
        _run_l1_contract()
    except Exception as exc:
        print(f"BASELINE FAIL: {type(exc).__name__}: {exc}")
        return 1

    print("BASELINE PASS: relevant L1 prompt contract")
    results = (
        _prove_mutation(
            "drop FORBIDDEN DOLLAR AMOUNTS block",
            "get_load_details",
            _drop_forbidden_amounts,
            "FORBIDDEN DOLLAR AMOUNTS",
        ),
        _prove_mutation(
            "drop Internal Ceiling line",
            "get_load_details",
            _drop_internal_ceiling,
            "Internal Ceiling:",
        ),
        _prove_mutation(
            "remove Zone 1 never-counter-higher rule",
            "get_negotiation_strategy",
            _drop_zone1_never_counter_higher,
            "NEVER counter with a rate HIGHER than the carrier's bid",
        ),
    )
    if all(results):
        print("MUTATION CHECK PASS: 3/3 mutations detected")
        return 0

    print(f"MUTATION CHECK FAIL: {sum(results)}/3 mutations detected")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
