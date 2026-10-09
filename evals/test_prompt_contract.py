"""L1 contracts for the real load normalizer and voice prompt builders.

These tests deliberately assert durable policy language and interpolated facts,
not the entire prompt, so editorial changes do not create noisy snapshots.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.load_normalization import normalize_load_data
from voice_prompt import (
    build_full_negotiation_prompt,
    get_initial_greeting_prompt,
    get_known_carrier_greeting_prompt,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "loads.json"
LOAD_CASES = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

# Keep this matrix intentionally closed: adding a fixture requires deciding what
# new product risk it covers, rather than silently expanding parametrization.
assert tuple(LOAD_CASES) == (
    "priced",
    "no_rate",
    "special_instructions",
    "comma_rates",
)


@pytest.mark.parametrize("initial_state", ("unknown", "known"))
@pytest.mark.parametrize("fixture_name", tuple(LOAD_CASES))
def test_prompt_contract_matrix(fixture_name: str, initial_state: str) -> None:
    """All four load shapes retain identity, lookup, pricing, and close policy."""
    raw = LOAD_CASES[fixture_name]
    load = normalize_load_data(raw)
    negotiation = build_full_negotiation_prompt(load)

    if initial_state == "unknown":
        initial = get_initial_greeting_prompt("KCH")
        assert "can I get your MC number?" in initial
        assert "verify the carrier BEFORE asking about the reference number" in initial
        assert "call verify_carrier" in initial
        assert "use the get_load_context function" in initial
    else:
        initial = get_known_carrier_greeting_prompt("Acme Trucking", "KCH")
        assert "is this Acme Trucking?" in initial
        assert "You do NOT need to ask for an MC number" in initial
        assert "Skip MC verification entirely" in initial
        assert "Only call verify_carrier if the caller explicitly says they are NOT Acme Trucking" in initial
        assert "get_load_context" in initial

    # The real normalizer must make heterogeneous rate representations
    # indistinguishable to downstream prompt logic.
    if fixture_name == "no_rate":
        expected_rates = (0.0, 0.0, 0.0)
    else:
        expected_rates = (1400.0, 1600.0, 1800.0)
    assert (load["startRate"], load["bookNowRate"], load["maxRate"]) == expected_rates

    assert f'Reference Number: {load["id"]}' in negotiation
    assert raw["origin_location"] in negotiation
    assert raw["destination_location"] in negotiation
    assert f'Opening Offer: ${load["startRate"]}' in negotiation
    assert f'Internal Goal: ${load["bookNowRate"]}' in negotiation
    assert f'Internal Ceiling: ${load["maxRate"]}' in negotiation

    # High-impact behavioral invariants: price confidentiality, zone-specific
    # bargaining, complete agreement capture, transfer ordering, and termination.
    assert "CONFIDENTIAL PRICING (NEVER SHARE WITH CARRIER)" in negotiation
    assert "NEVER counter with a rate HIGHER than the carrier's bid" in negotiation
    assert "Make 2 counter-offers before settling" in negotiation
    assert "DO NOT EXCEED 3 counter offers" in negotiation
    assert "carrier_contact_name, carrier_contact_phone" in negotiation
    assert "Carrier identity verified (verify_carrier completed)" in negotiation
    assert "get_load_context completed successfully" in negotiation
    assert "Always use the end_call function when concluding a call" in negotiation

    if fixture_name == "special_instructions":
        assert load["specialInstructions"] == "Driver must call before arrival"
        assert "Special Instructions: Driver must call before arrival" in negotiation
        assert "Tracker Required: Yes" in negotiation
        assert 'then read: "Driver must call before arrival"' in negotiation
    else:
        assert load["specialInstructions"] is None
        assert "No special instructions — skip this step." in negotiation

    if fixture_name == "no_rate":
        assert "Accept the FIRST bid offered by the carrier" in negotiation
        assert "Do not negotiate." in negotiation
    else:
        assert 'State your initial offer: "This lane is going for $1400.0"' in negotiation


@pytest.mark.xfail(
    strict=True,
    reason=(
        "F2: no-rate normalization creates a $0 confidential ceiling while the "
        "same prompt requires accepting the first nonzero carrier bid"
    ),
)
def test_f2_no_rate_prompt_has_no_zero_ceiling_contradiction() -> None:
    prompt = build_full_negotiation_prompt(normalize_load_data(LOAD_CASES["no_rate"]))

    assert "Accept the FIRST bid offered by the carrier" in prompt
    assert "NEVER EXCEED, NEVER REVEAL" not in prompt
    assert "FORBIDDEN DOLLAR AMOUNTS" not in prompt


@pytest.mark.xfail(
    strict=True,
    reason=(
        "F4: forbidden-amount list claims all spelled-out forms but omits the "
        "spoken freight forms promoted by the voice style guide"
    ),
)
def test_f4_forbidden_list_enumerates_spoken_confidential_rates() -> None:
    prompt = build_full_negotiation_prompt(normalize_load_data(LOAD_CASES["priced"]))
    forbidden = prompt.split("FORBIDDEN DOLLAR AMOUNTS", 1)[1].split(
        "If you need to counter-offer", 1
    )[0].lower()

    assert "sixteen hundred" in forbidden
    assert "eighteen hundred" in forbidden


@pytest.mark.xfail(
    strict=True,
    reason=(
        "F5: valid startRate == bookNowRate makes the required opening offer "
        "simultaneously forbidden as the confidential goal"
    ),
)
def test_f5_equal_start_and_goal_does_not_forbid_required_opening_offer() -> None:
    load = normalize_load_data(
        {
            "load_id": "EQUAL-1",
            "origin_location": "Atlanta, GA",
            "destination_location": "Chicago, IL",
            "broker_initial_offer": 1600,
            "broker_target_rate": 1600,
            "broker_max_rate": 1800,
        }
    )
    prompt = build_full_negotiation_prompt(load)
    forbidden = prompt.split("FORBIDDEN DOLLAR AMOUNTS", 1)[1].split(
        "If you need to counter-offer", 1
    )[0]

    assert 'This lane is going for $1600.0' in prompt
    assert "$1600.0" not in forbidden
