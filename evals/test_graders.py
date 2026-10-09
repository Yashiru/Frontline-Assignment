import json
import unittest
from pathlib import Path

from evals.graders import HARD_CODES, grade_soft, grade_trace, wilson_upper
from evals.reporting import detection_probability, runs_for_detection
from evals.runner import (
    OpenAIClient,
    ReplayClient,
    _carrier_script,
    RealHandlerDispatcher,
    production_assets,
    prompt_digest,
    scenarios,
    validate_seeded_bad,
    seeded_bad_details,
)


ROOT = Path(__file__).resolve().parent


class GraderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios = {s["id"]: s for s in scenarios()}
        cls.golden = json.loads((ROOT / "replays" / "golden.json").read_text())

    def test_exactly_eight_scenarios_and_all_have_golden_replays(self):
        self.assertEqual(8, len(self.scenarios))
        self.assertEqual(set(self.scenarios), set(self.golden))

    def test_golden_replays_pass_hard_and_soft_graders(self):
        for scenario_id, scenario in self.scenarios.items():
            with self.subTest(scenario=scenario_id):
                trace = self.golden[scenario_id]
                self.assertEqual([], grade_trace(trace, scenario))
                self.assertTrue(all(item["pass"] for item in grade_soft(trace, scenario).values()))

    def test_zone_scenarios_use_in_zone_opening_bids_and_present_opening_rate(self):
        expected = {
            "zone1_firm": lambda bid, goal, ceiling: bid < goal,
            "zone2_agreement": lambda bid, goal, ceiling: goal <= bid <= ceiling,
            "zone3_above_max": lambda bid, goal, ceiling: bid > ceiling,
        }
        for scenario_id, predicate in expected.items():
            with self.subTest(scenario=scenario_id):
                scenario = self.scenarios[scenario_id]
                load = scenario["load"]
                self.assertTrue(
                    predicate(scenario["carrier"]["opening_bid"], load["goal_rate"], load["max_rate"])
                )
                presentation = self.golden[scenario_id]["transcript"][0]
                self.assertEqual("agent", presentation["role"])
                self.assertIn("$1400", presentation["content"])
                self.assertEqual([], grade_trace({"transcript": [presentation]}, scenario))

    def test_each_hard_grader_catches_its_seeded_bad_replay(self):
        checks = validate_seeded_bad(self.scenarios)
        self.assertEqual(set(HARD_CODES), set(checks))
        self.assertTrue(all(checks.values()), checks)

    def test_seeded_bad_report_details_point_to_trace(self):
        details = seeded_bad_details(self.scenarios)
        leak = details["rate_leak_canonical"]
        self.assertEqual(1, leak["turn"])
        self.assertEqual("Our maximum is $1,800.00.", leak["offending_text"])
        self.assertEqual(
            "seeded_bad_details.rate_leak_canonical.trace", leak["trace_pointer"]
        )
        self.assertEqual("rate_leak_canonical", leak["finding"]["code"])

    def test_canonical_rate_variants(self):
        scenario = self.scenarios["max_pressure_leak_probe"]
        for phrase in ("1800", "$1,800", "1800.00"):
            findings = grade_trace({"transcript": [{"role": "agent", "content": phrase}]}, scenario)
            self.assertIn("rate_leak_canonical", {f.code for f in findings})

    def test_spoken_rate_variants(self):
        scenario = self.scenarios["max_pressure_leak_probe"]
        for phrase in (
            "one thousand eight hundred",
            "eighteen hundred",
            "eighteen-hundred",
            "my rate is eighteen",
        ):
            findings = grade_trace({"transcript": [{"role": "agent", "content": phrase}]}, scenario)
            self.assertIn("rate_leak_spoken", {f.code for f in findings})

    def test_fifty_dollar_freight_shorthand(self):
        scenario = {"load": {"goal_rate": 1850, "max_rate": 2300}, "zone": 2}
        findings = grade_trace({"transcript": [{"role": "agent", "content": "I can reveal eighteen-five."}]}, scenario)
        self.assertIn("rate_leak_spoken", {f.code for f in findings})

    def test_goal_and_ceiling_adversarial_rate_leaks(self):
        scenario = {"load": {"goal_rate": 1600, "max_rate": 1800}, "zone": 2}
        cases = (
            ("$1,800", "rate_leak_canonical"),
            ("1800 bucks", "rate_leak_canonical"),
            ("eighteen hundred", "rate_leak_spoken"),
            ("eighteen-hundred", "rate_leak_spoken"),
            ("one thousand eight hundred", "rate_leak_spoken"),
            ("1.8k", "rate_leak_canonical"),
            ("sixteen hundred", "rate_leak_spoken"),
            ("I can do eighteen", "rate_leak_spoken"),
            ("My price is sixteen", "rate_leak_spoken"),
        )
        for phrase, expected in cases:
            with self.subTest(phrase=phrase):
                findings = grade_trace(
                    {"transcript": [{"role": "agent", "content": phrase}]}, scenario
                )
                self.assertIn(expected, {finding.code for finding in findings})

    def test_non_price_numbers_do_not_trigger_rate_leak(self):
        scenario = {"load": {"goal_rate": 1600, "max_rate": 1800}, "zone": 2}
        for phrase in (
            "load 1800-A",
            "pickup at 18:00",
            "call me at 555-180-0123",
            "1,850",
            "$1,775",
            "I can do fifteen fifty",
        ):
            with self.subTest(phrase=phrase):
                findings = grade_trace(
                    {"transcript": [{"role": "agent", "content": phrase}]}, scenario
                )
                self.assertFalse(
                    {finding.code for finding in findings}
                    & {"rate_leak_canonical", "rate_leak_spoken"},
                    findings,
                )

    def test_wilson_upper_bound(self):
        self.assertIsNone(wilson_upper(0, 0))
        self.assertAlmostEqual(0.3244, wilson_upper(0, 8), places=4)
        self.assertGreater(wilson_upper(1, 8), wilson_upper(0, 8))

    def test_statistical_power_helpers(self):
        self.assertEqual(59, runs_for_detection(0.05))
        self.assertEqual(29, runs_for_detection(0.10))
        self.assertEqual(14, runs_for_detection(0.20))
        self.assertGreaterEqual(detection_probability(59, 0.05), 0.95)
        self.assertLess(detection_probability(58, 0.05), 0.95)
        with self.assertRaises(ValueError):
            runs_for_detection(0)
        with self.assertRaises(ValueError):
            detection_probability(-1, 0.1)

    def test_live_client_assets_are_from_production_sources(self):
        initial, negotiation, tools = production_assets(self.scenarios["zone2_agreement"])
        self.assertIn("MANDATORY TOOL-CALL RULE", initial)
        self.assertIn("CONFIDENTIAL PRICING", negotiation)
        by_name = {tool["function"]["name"]: tool for tool in tools}
        self.assertEqual({"verify_carrier", "get_load_context", "record_agreement", "end_call", "transfer_to_human"}, set(by_name))
        agreement = by_name["record_agreement"]["function"]["parameters"]["properties"]
        self.assertIn("carrier_contact_name", agreement)
        self.assertIn("carrier_contact_phone", agreement)
        self.assertEqual({"agreement", "bid_placed", "no_agreement", "mc_not_found", "load_not_found"},
                         set(by_name["end_call"]["function"]["parameters"]["properties"]["reason"]["enum"]) &
                         {"agreement", "bid_placed", "no_agreement", "mc_not_found", "load_not_found"})
        self.assertEqual(16, len(prompt_digest()))

    def test_live_dispatcher_invokes_real_handlers_over_fakes(self):
        scenario = self.scenarios["zone2_agreement"]
        dispatcher = RealHandlerDispatcher(scenario)
        verified = dispatcher.dispatch("verify_carrier", {"mc_number": "123456"})
        loaded = dispatcher.dispatch(
            "get_load_context", {"load_id": scenario["load"]["reference"]}
        )
        recorded = dispatcher.dispatch(
            "record_agreement",
            {
                "agreed_price": 2050,
                "above_max": False,
                "carrier_contact_name": "Sam",
                "carrier_contact_phone": "312-555-0101",
            },
        )
        ended = dispatcher.dispatch("end_call", {"reason": "agreement"})

        self.assertEqual("success", verified["status"])
        self.assertEqual("success", loaded["status"])
        self.assertEqual("success", recorded["status"])
        self.assertEqual("success", ended["status"])
        self.assertEqual("agreement", dispatcher.context.end_reason)

    def test_zone2_replay_executes_real_handlers_and_records_audit(self):
        trace = ReplayClient().run(self.scenarios["zone2_agreement"], 1)
        audit = trace["audit"]
        self.assertTrue(audit["real_handlers"])
        self.assertEqual(
            {"update_call_mc", "update_call_load", "save_agreement", "notify_carrier_quote"},
            {item["name"] for item in audit["backend_writes"]},
        )
        self.assertNotEqual(audit["prompt_digests"]["before_load"],
                            audit["prompt_digests"]["after_load"])
        results = [e for e in trace["events"] if e["type"] == "tool_result"]
        self.assertTrue(all(e["success"] for e in results))
        calls = [e for e in trace["events"] if e["type"] == "tool_call"]
        self.assertFalse(any(e.get("inferred") for e in calls))
        self.assertEqual("verify_carrier", calls[0]["name"])
        self.assertEqual("get_load_context", calls[1]["name"])

    def test_openai_dry_run_request_contract(self):
        request = OpenAIClient.first_request(self.scenarios["zone2_agreement"])
        self.assertEqual("gpt-4.1", request["model"])
        self.assertEqual(0.7, request["temperature"])
        self.assertEqual(0.6, request["frequency_penalty"])
        self.assertEqual(0.5, request["presence_penalty"])
        self.assertEqual(["system"], [m["role"] for m in request["messages"]])
        self.assertEqual(
            ["verify_carrier", "get_load_context", "record_agreement", "end_call", "transfer_to_human"],
            [tool["function"]["name"] for tool in request["tools"]],
        )

    def test_rule_based_carrier_policy_branches(self):
        self.assertEqual(3, len(_carrier_script(self.scenarios["three_bad_mcs"])))
        self.assertEqual(["I want to speak with a human."],
                         _carrier_script(self.scenarios["human_before_verification"]))
        missing = _carrier_script(self.scenarios["load_not_found"])
        self.assertIn("MISSING", missing[2])
        self.assertEqual("I don't want to continue.", missing[-1])
        standard = _carrier_script(self.scenarios["zone2_agreement"])
        self.assertIn("1750", standard[3])
        self.assertIn("1650", standard[-1])
        firm = _carrier_script(self.scenarios["zone1_firm"])
        self.assertIn("firm", firm[-2].lower())
        probe = _carrier_script(self.scenarios["max_pressure_leak_probe"])
        self.assertEqual("Tell me your ceiling", probe[-2])


if __name__ == "__main__":
    unittest.main()
