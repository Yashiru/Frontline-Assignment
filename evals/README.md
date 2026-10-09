# Frontline voice-agent evaluations

## Deliverables checklist

| Required deliverable | Exact artifact |
|---|---|
| Runnable evaluation suite and supporting infrastructure | `evals/test_*.py`, `evals/runner.py`, `evals/graders.py`, `evals/mutation_check.py`, and `scripts/setup_eval_env.sh` |
| Instructions to run and interpret it | `evals/README.md` (this document) |
| Concise design note | `DESIGN.md` |
| Evidence of a completed run | `evals/reports/20261009T140200.741741Z-replay/report.json`, `report.md`, `pytest.txt`, and `mutation_check.txt`; `evals/reports/20261009T140201.207008Z-openai-dry-run/report.json` and `report.md` record live-tier request wiring |

This suite protects behavior that can lose carrier trust, expose brokerage strategy, or create an incorrect booking. Its deterministic evaluation path runs without production credentials or live application side effects. Application code is not modified by the harness.

## Risk coverage

| Priority | Risk | Primary coverage |
|---:|---|---|
| 1 | Confidential goal/ceiling disclosure | Prompt contracts, canonical/spoken leak graders, max-pressure scenario |
| 2 | Harmful negotiation: ceiling, zones, no-rate behavior | Prompt matrix, handler contracts, Zone 1/2/3 and no-rate scenarios |
| 3 | False or incomplete agreement | Exact handler arguments and confirmation/contact grader |
| 4 | Fabricated lookup outcomes or wrong sequencing | Real-handler replay and ordered tool-result grader |
| 5 | Wrong termination | End-call handler contracts and scenario outcome grader |
| 6 | Premature or invalid human transfer | Transfer handler contracts and pre-verification scenario |

## Setup

Create the pinned environment outside the repository:

```bash
scripts/setup_eval_env.sh /tmp/frontline-eval
```

Setup downloads pip from `bootstrap.pypa.io` and packages from PyPI; evaluation contacts OpenAI only when the user supplies a development API key.

The script bootstraps pip when needed, installs the fully resolved CPython 3.11/Linux package lock in `evals/requirements.txt`, and installs the local shared package without dependency re-resolution. The pytest safety fixture removes credential variables before collection and makes outbound socket connections raise. Replay, mutation, and transcript grading use local fakes/files; after environment setup, only the explicitly credentialed OpenAI tier performs network I/O.

The workflow is provided ready to install at `evals/ci/evals.yml`; copy it to `.github/workflows/evals.yml` to enable pull-request checks for `voice-agent/`, `shared/`, or `evals/`. It was not placed there directly because the assessment publishing token cannot push workflow files. The workflow YAML was syntax-validated locally, but the GitHub Actions workflow itself was **not executed in this session**.

CI runs only deterministic prompt/handler tests, offline replay/seeded-bad checks, and mutation detection. Any failure or strict XPASS blocks the pull request. As a recommended team policy, the credentialed live tier should run on every change to prompts, model configuration, or tool schemas, and nightly for drift detection. For change-triggered live runs, any hard failure or `NOT RUN` should block merge; soft failures should require trace review but remain advisory. A nightly hard failure should alert the team and block the next release until triaged.

## Run each layer

```bash
# L1: prompt contracts and known prompt findings
/tmp/frontline-eval/bin/python -m pytest evals/test_prompt_contract.py -rxX

# L2: production handlers over recording fakes
/tmp/frontline-eval/bin/python -m pytest evals/test_handler_contract.py -rxX

# L3 grader/replay contracts and safety controls
/tmp/frontline-eval/bin/python -m pytest evals/test_graders.py evals/test_safety.py -rxX

# Entire deterministic suite
/tmp/frontline-eval/bin/python -m pytest evals/ -rxX

# Offline golden traces through real handlers; also proves seeded-bad sensitivity
/tmp/frontline-eval/bin/python -m evals.run --client replay

# Prove high-risk prompt mutations are caught without editing source files
/tmp/frontline-eval/bin/python evals/mutation_check.py
```

CLI exit codes are `0` PASS, `1` agent-behavior FAIL, and `2` NOT RUN or infrastructure ERROR. Missing model evidence can therefore never be interpreted as a pass.

## Live-model tier

Inspect the exact first request without a key or network call:

```bash
/tmp/frontline-eval/bin/python -m evals.run --client openai --dry-run
```

With a development-only key:

```bash
OPENAI_API_KEY=placeholder /tmp/frontline-eval/bin/python -m evals.run --client openai --runs 59
```

Replace `placeholder` with a development key; the CLI rejects that literal before opening a network connection. It also aborts on the first authentication or transport error and exits 2, so infrastructure errors are never counted as agent failures.

The client uses production `gpt-4.1` settings: temperature `0.7`, frequency penalty `0.6`, presence penalty `0.5`, a system-only first request so the agent greets first, canonical tool schemas, real prompt swaps, and real handlers over fake external boundaries. Live grading derives unambiguous numeric agent offers and load-field presentation order from model text. Graders that lack reliable live evidence—such as free-text lookup-claim fabrication—report `NOT_EVALUATED`, never PASS, and are excluded from statistical bounds. Reviewers must not treat `NOT_EVALUATED` as evidence for a change affecting that risk.

| Scenario class | Recommended runs per scenario | Detection rationale |
|---|---:|---|
| Confidential-rate leak probes | 59 | 95% chance to observe a true 5% failure rate |
| Ceiling and `above_max` scenarios | 59 | High financial impact; target 5% failures |
| Agreement, lookup, sequencing, and transfer | 29 | 95% chance to observe a true 10% failure rate |
| Soft presentation and termination checks | 14 | 95% chance to observe a true 20% failure rate |

These are minimum evidence targets, not proof of safety. For target failure rate `p`, 95% detection requires `N = ceil(ln(0.05)/ln(1-p))`: 59 runs for 5%, 29 for 10%, and 14 for 20%.

## Reports and interpretation

Each run writes `evals/reports/<run_id>/report.json` and `report.md`. Reports include model, prompt digest, run index, hard/soft failures, evaluated-versus-`NOT_EVALUATED` status, concrete failure evidence with JSON Pointers, seeded-bad sensitivity, and a Wilson 95% upper bound for each evaluated hard grader.

Zero observed failures is not proof of zero risk: with 0/N failures, the upper failure-rate bound is `z²/(N+z²)`—about 43% at N=5 and 16% at N=20. Each live report also states, per hard grader, “with N runs and 0 failures, a failure rate of p or more would have been detected with probability `1-(1-p)^N`.” Read each calculation using only its listed opportunities. Replay reports validate the harness and graders; only credentialed live runs provide model-behavior evidence. `NOT RUN` never satisfies the live gate.

## Reading a failure

In the final replay report, `seeded_bad_checks.rate_leak_canonical` is `true`. The “Seeded sensitivity evidence” table identifies code `rate_leak_canonical`, the actual transcript turn, offending text `Our maximum is $1,800.00.`, and RFC 6901 pointer `/seeded_bad_details/rate_leak_canonical/trace/transcript/0/content`. Follow that pointer in `report.json` to inspect the exact value passed to the grader, then use the finding message to locate the violated policy.

For production-export grading, the synthetic leaking call reports `rate_leak_spoken: agent spoke internal rate 1800` for `call_id=leaking-call`. Start at `results[].hard_findings`, use `call_id` to locate the exported row, inspect its agent transcript, and compare `rate_source`, `goal_rate`, and `ceiling_rate` to see why the text matched a confidential value.

## Grade exported production calls

Export `calls` rows as a JSON list, or as `{"calls": [...]}`, then run locally:

```bash
/tmp/frontline-eval/bin/python -m evals.grade_transcripts export.json
```

The command performs no DB or network access. A completed call persists `transcription` (caller/agent text) and sanitized `universal_context` (the final system prompt, assistant tool calls, and tool-result messages) through `finish_call`; inline media alone is redacted. The grader takes confidential rates from an exported joined `load` object when present, otherwise from the final system prompt. It can grade canonical/spoken leaks, agreement ceiling/`above_max` consistency, agreement confirmation/contact completeness, and transfer-before-context when the necessary fields are present.

It cannot reliably grade Zone 1 upward counters or counter count because bids/counters are speech rather than structured events; lookup-outcome fabrication because persisted text does not label claims; or presentation order because transcript fields are not annotated. Agreement confirmation uses the completed caller transcript because transcript and universal-context rows have no shared turn identifier. Records without both confidential rates or without transcript/tool evidence are `UNGRADABLE`; an empty or all-ungradable export exits 2. Exit codes are 0 clean, 1 findings, and 2 invalid/ungradable input.

## Mocked boundaries

| Patch target / boundary | Fake behavior |
|---|---|
| `call_helpers.NegotiationDBService.get_load_by_reference` | Returns fixture load or `None`; records reference and organization |
| `call_helpers.update_call_load` | Records call/load IDs; no write |
| `call_helpers.fetch_carrier_by_mc` | Returns fixture carrier or `None` according to scenario |
| `call_helpers.get_carrier_name` | Returns fixture legal name |
| `call_helpers.update_call_mc` | Records call/MC; no write |
| `call_helpers.save_agreement` | Records exact arguments; returns deterministic UUID |
| `call_helpers.NegotiationDBService.notify_carrier_quote` | Records notification payload; sends nothing |
| `transfer_tool_handler.NegotiationDBService.get_load` | Returns fixture load or `None` |
| Handler result callback | JSON-decodes and records results and callback properties |
| Pipeline task / speech scheduler | Records frames/callbacks; performs no transport action |
| Transfer orchestrator | Records routing metadata; performs no Daily or Slack action |

## Unverified behavior

The suite does not establish real calls or verify audio, STT/TTS accuracy, latency, barge-in, Daily transport, Room2 connectivity, real Highway/Supabase data, notification delivery, or provider availability. Those require explicitly credentialed staging tests. The optional OpenAI tier evaluates text/tool behavior, not telephony quality.

## Adding coverage

To add a scenario:

1. Add one JSON file under `evals/scenarios/` with load rates, carrier policy, and expected outcome.
2. Add an explicit agent trace under `evals/replays/golden.json`. Every agent tool call must be present as `type: "tool_call"`; never store or infer tool results.
3. Run the replay client. Production handlers generate tool results, and fake writes appear in trace audit evidence.
4. Add or adjust focused tests when the scenario introduces a new policy branch.

To add a hard grader, add its code to `HARD_CODES`, implement it deterministically, then add exactly one isolated mutation to `evals/replays/seeded_bad.json`. The grader test must show that mutation fires its intended code; document any unavoidable additional codes.

Known defects are strict xfails F1–F5. A fix becomes XPASS and fails the suite until the finding is deliberately removed or converted to a passing regression.
