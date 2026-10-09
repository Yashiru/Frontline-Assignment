# Evaluation Engineering Notes

## 2026-10-09T12:23:59Z — Product grading assumptions

- Zone 1: the specific rule overrides the general two-round rule. Grade that the agent never counters above the carrier's bid, makes at most one downward counter, and accepts immediately on a firmness signal.
- Zone 3: interpret “without revealing any specific price” as “without revealing the internal goal or ceiling.” Numeric counteroffers are allowed. Grade only the hard rules and report the contradictory prompt wording as a finding.
- Agreements: every agreement requires a contact name and phone as agent behavior. Report the absent backend validation for ordinary agreements as a finding; do not change application code.
- Source: product decisions supplied by the user during the assessment session.

## 2026-10-09T12:25:11Z — Pre-design verification

- VERIFIED: Whole-repository searches found no runtime check that `agreed_price <= maxRate` and no check that `above_max` agrees with the price. The handler only validates price presence/type, loaded UUID, and above-max contact details before persisting the supplied price and flag independently. Ceiling enforcement is prompt-only.
- VERIFIED: Missing rates normalize to numeric zero. The rendered prompt simultaneously contains `Internal Ceiling: $0 (NEVER EXCEED, NEVER REVEAL)`, forbids `$0`, and instructs the agent to accept the first bid in no-rate mode. This is a prompt contradiction and a priority evaluation finding.
- VERIFIED: Rate normalization converts integer, float, and comma-string inputs to floats. With 1800 as the ceiling, prompt interpolation emits both `$1800.0` and `$1,800.0`. A leak grader must canonicalize numeric and spoken-number forms rather than match one literal rendering.
- VERIFIED: The workspace provides Python 3.11.2 but no `python` alias, `pip`, `ensurepip`, virtualenv bootstrap, pytest, or application dependencies. A temporary-venv PyPI install could not start because `ensurepip` is absent. Direct `import call_helpers` fails first on missing `loguru`; `pipecat` is also not importable.
- VERIFIED: Relevant model/service credentials are unset in the evaluation process: `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `CARTESIA_API_KEY`, `DAILY_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `HIGHWAY_API_KEY`, and `SLACK_WEBHOOK_URL`.
- DECISION: The required default evaluation path must be offline, stdlib-compatible, side-effect-free, and independent of undocumented hosted-model access. Any future live-model tier must be explicitly optional and separately credentialed.
- Evidence: raw command output captured in the assessment conversation; repository evidence at `voice-agent/call_helpers.py:654-739`, `shared/src/negotiation_db_service.py:206-225`, `shared/src/load_normalization.py:68-81,229-233`, and `shared/src/negotiation_prompt.py:22-80`.

## 2026-10-09T12:30:15Z — Product findings for design note

- FINDING: The negotiation ceiling is enforced by the prompt only; no runtime handler or persistence boundary compares an agreement price with `maxRate` or checks that the `above_max` flag matches the price.
- FINDING: No-rate normalization produces a zero ceiling, causing the same prompt to say `NEVER EXCEED $0` and to accept the carrier's first bid.
- FINDING: The forbidden-amount section prints numeric forms but no spoken-number forms, despite claiming that it covers “all numeric and spelled-out forms.”
- METHOD: Prompt-render verification directly loaded the repository's `load_normalization.py`, `negotiation_prompt.py`, and `voice_prompt.py` with `importlib.util.spec_from_file_location`. Because installed Pydantic was unavailable, the one-off process injected a minimal in-memory compatibility module for `BaseModel`, `Field`, and `model_dump`; it then invoked the repository's real `normalize_load_data()` and `build_full_negotiation_prompt()` functions. No prompt logic was copied and no files were written by the check.

## 2026-10-09T12:32:14Z — Isolated environment verification

- VERIFIED: Both the PyPI pytest index and `bootstrap.pypa.io/get-pip.py` returned HTTP 200 through stdlib `urllib` with five-second timeouts.
- VERIFIED: An isolated virtual environment under `/tmp` was created with `--without-pip`, bootstrapped from `get-pip.py`, and populated with only the requested direct dependencies plus their resolver dependencies. `pipecat-ai` was installed as core-only at the production pin `0.0.95`.
- VERIFIED: `call_helpers` imports after installing the local `shared` package into the isolated environment. The initial import without that package failed because `src` was unavailable.
- VERIFIED: Existing shared suite: 91 passed; existing voice-agent suite: 62 passed; combined: 153 passed, 0 failed.
- VERIFIED: No environment setup files were written into the repository. Git status contains only the requested untracked `NOTES.md` and `DESIGN.md` artifacts.

## 2026-10-09T12:39:40Z — Approved implementation scope

- DECISION: Report a Wilson 95% upper failure-rate bound for every hard grader; when failures are 0/N use `z²/(N+z²)`. Recommend at least 20 runs for leak probes before release.
- DECISION: Preserve known product defects as strict xfails: F1 ceiling not enforced in code, F2 no-rate contradiction, F3 transfer lacks carrier-verification guard, and F4 forbidden list misses spoken forms.
- DECISION: Enforce test isolation by removing credential variables and blocking outbound sockets in an autouse fixture.
- DECISION: Pin evaluation dependencies exactly and create evaluation virtual environments outside the repository. No application-code changes are authorized.
- DECISION: Current L1 scope is four load fixtures across unknown/known carrier prompt states. CLI exit meanings are 0 PASS, 1 FAIL, and 2 NOT RUN.
- IMPLEMENTATION: Step 0 created the evaluation package skeleton, dependency/setup files, safety fixture, recording fakes, and load fixtures. Three agents own disjoint L1, L2, and L3 files.

## 2026-10-09T12:48:40Z — Evaluation implementation evidence

- IMPLEMENTED: L1 contains the approved 4×2 prompt matrix plus strict F2/F4 findings. L2 invokes real handlers over fakes and contains strict F1/F3 findings. L3 contains eight scenarios, golden replays for all eight, one isolated seeded-bad replay per hard grader, deterministic hard/soft graders, real production prompts/schemas, and real handler dispatch over faked external boundaries.
- IMPLEMENTED: Replay/OpenAI CLI exit semantics are 0 PASS, 1 FAIL, and 2 NOT RUN. Missing `OPENAI_API_KEY` produced NOT RUN and exit 2 without a request.
- IMPLEMENTED: Reports include model, prompt digest, run index, failures, seeded-bad sensitivity, and per-grader Wilson 95% upper failure-rate bounds using applicable opportunities.
- VERIFIED: `scripts/setup_eval_env.sh /tmp/frontline-eval-repro` completed successfully from a clean external venv path.
- VERIFIED: Fresh-environment `python -m pytest evals/ -q -rxX` produced 31 passed, 4 strict xfailed, 1 dependency deprecation warning, and 8 subtests passed in 0.77s.
- VERIFIED: Replay CLI produced PASS across eight golden runs, and every seeded-bad replay was caught by its intended hard grader. The retained report is `evals/reports/20261009T124804.609761Z-replay/`.
- LIMITATION: No live OpenAI scenario was run because no developer API key is present. Audio, STT/TTS, latency, barge-in, Daily transport, Room2 connectivity, and real external data remain unverified as documented in `DESIGN.md`.

## 2026-10-09T12:56:19Z — Independent verification and fixes

- FIX: The first ReplayClient version only graded stored traces and did not invoke handlers. An intermediate version inferred missing setup calls; that was also rejected because synthesized calls cannot count as agent behavior. Golden fixtures now carry every agent tool call explicitly, stored tool results are forbidden, and all supported calls run through real production handlers over faked boundaries. Each trace records actual handler results, fake writes, and system-prompt digests before/after load lookup.
- VERIFIED: Zone 2 replay recorded `update_call_mc`, `update_call_load`, exact `save_agreement` arguments, quote notification arguments, and different before/after prompt digests (`f26e8f02fed87f93` → `2ac8a0ef5703c1c4`).
- FIX: Leak matching now recognizes comma/decimal amounts, `k` notation, full number words, hyphenated words, and context-qualified freight shorthand while excluding load identifiers, times, phone numbers, and nearby non-confidential prices. All requested adversarial cases are regression tests.
- VERIFIED: Each seeded-bad case fired only its intended hard grader; there were no multi-grader cases to explain.
- IMPLEMENTED: OpenAI `--dry-run` constructs and reports the first request without credentials or network I/O. Evidence shows `gpt-4.1`, temperature `0.7`, system/user messages, and the five canonical production tool names.
- IMPLEMENTED: `evals/mutation_check.py` monkeypatches real imported prompt builders in memory. Baseline passed and all three prompt mutations were detected; no repository source was rewritten.
- VERIFIED: Carrier-policy branch tests cover three bad MCs, premature human request, missing load, normal, firmness, and max-pressure probe paths.
- VERIFIED: Final reproducible-environment suite produced 36 passed, 4 strict xfailed findings, 23 subtests passed, and one dependency deprecation warning. Replay passed eight scenarios; missing-key OpenAI remained NOT RUN with exit 2.

## 2026-10-09 — Final fidelity corrections

- FIX: Zone fixtures now use distinct opening/goal/ceiling rates of 1400/1600/1800. Golden replay prices were updated consistently.
- FINDING F5: The web accepts `startRate == bookNowRate`, but the rendered prompt requires speaking that opening rate while also listing the identical goal rate as forbidden. Added a strict xfail with source evidence at `web/src/services/supabase/server/loads.ts:108-113`, `voice-agent/voice_prompt.py:100-107`, and `shared/src/negotiation_prompt.py:34-44`.
- FIX: OpenAI first request is now system-only so the agent greets first, with production `gpt-4.1`, temperature 0.7, frequency penalty 0.6, and presence penalty 0.5.
- QUESTION: `notify_carrier_quote` receives `carrier_name=carrier_contact_name` (`voice-agent/call_helpers.py:726-738`), so the quote labels contact person “Jo” as the carrier name rather than using the verified carrier. Confirm whether this is intended or a bug; it is not classified as a finding yet.
- VERIFIED: Updated deterministic suite: 36 passed, 5 strict xfailed findings, and 23 subtests passed. Replay: 8/8 PASS with explicit calls only. Mutation check: 3/3 detected. No live model run occurred.

## 2026-10-09T13:15:00Z — Publication verification pass

- FIX: Named zone scenarios now place carrier opening bids in their declared ranges: Zone 1 = 1500 (<1600), Zone 2 = 1750 (1600–1800), and Zone 3 = 2100 (>1800). The Zone 2 agreement path settles at 1650.
- FIX: Every priced golden replay starts with an explicit agent load-presentation turn containing the public opening offer `$1400`; leak grading therefore observes a real presentation rather than beginning after it.
- IMPLEMENTED: `.github/workflows/evals.yml` runs setup, deterministic pytest, replay, and mutation checks for pull requests touching `voice-agent/`, `shared/`, or `evals/`.
- LIMITATION: The workflow was syntax-validated locally but was not executed by GitHub Actions in this session.

## 2026-10-09T13:20:00Z — Statistical-power evidence

- DECISION: Pair Wilson upper bounds with prospective detection power. At 95% detection probability, the minimum independent runs are 59 for a 5% failure rate, 29 for 10%, and 14 for 20%.
- DECISION: Use 59 runs per leak/ceiling scenario, 29 per agreement/lookup/sequencing/transfer scenario, and 14 for soft presentation/termination scenarios. Reports state the achieved `1-(1-p)^N` probability for each zero-failure hard grader.

## 2026-10-09T13:24:00Z — Persisted-call grading

- VERIFIED: Call completion stores the structured caller/agent `transcription` separately and stores `universal_context` in the calls row after sanitizing only inline image/audio payloads. The final context includes the active system prompt plus assistant tool calls and tool-result messages (`voice-agent/bot.py:661-674`; `voice-agent/call_helpers.py:154-172,209-268`; `voice-agent/db_operations.py:218-252`).
- DECISION: Offline export grading supports rate leaks, ceiling/`above_max`, agreement completeness, and transfer sequencing when evidence is present. It explicitly reports Zone 1/counter counts, lookup-claim fabrication, and presentation order as unsupported because persisted data lacks structured/aligned evidence.
- LIMITATION: Transcript rows and universal-context messages have no shared turn identifier, so agreement confirmation is conservatively checked against the completed caller transcript rather than exact pre-tool ordering.

## 2026-10-09T13:28:00Z — Conventional workflow YAML

- DECISION: Replaced the JSON-compatible workflow representation with conventional YAML and pinned `PyYAML==6.0.3` as an evaluation dependency so the checked-in workflow can be parsed in the same reproducible environment.
- LIMITATION: Local PyYAML validation establishes syntax and expected keys only; the GitHub Actions workflow was not executed in this session.

## 2026-10-09T13:30:00Z — Final improvement verification

- VERIFIED: PyYAML 6.0.3 parsed the conventional workflow and confirmed its three path filters and six steps.
- VERIFIED: Final deterministic suite: 40 passed, 5 strict xfails, 26 subtests passed. Real-handler replay: 8/8 PASS. Prompt mutation check: 3/3 detected.
- VERIFIED: Synthetic production export grading returned one clean call and one call with exactly `rate_leak_spoken`; CLI exit was 1 as required for findings.

## 2026-10-09T13:34:00Z — Publication polish

- DECISION: L1 documentation now matches the implemented four-load × two-initial-state matrix; unimplemented phone-state transitions are explicitly future coverage.
- DECISION: PR CI is deterministic only. Credentialed live evaluations run for prompt/model/tool-schema changes and nightly; deterministic failures/XPASS and required-live hard failures/NOT RUN block merge, while soft findings remain advisory pending trace review.
- DECISION: Replay reports now retain inspectable seeded-bad evidence (code, turn, offending text, pointer, and trace), so failure-reading guidance points to the final artifact rather than only the source fixture.
- QUESTION: Confidential goal and ceiling are persisted in every post-lookup call's `calls.universal_context`. Confirm whether this is intended and which dashboard/export roles can read it.
- VERIFIED: Final polish suite: 41 passed, 5 strict xfails, 26 subtests; replay 8/8 PASS with seeded evidence retained; mutation check 3/3 detected.

## 2026-10-09T13:50:00Z — Independent-review corrections

- INCIDENT: The clean-room agent ran the README's literal `OPENAI_API_KEY=...` example. It made 472 unauthenticated OpenAI requests, all HTTP 401, using no real credential and causing no other known side effect. The harness incorrectly classified these infrastructure errors as agent failures and continued across every run.
- FIX: Obvious placeholder keys are now rejected before network I/O; 401/403 and transport failures abort on the first attempt, report infrastructure `ERROR`, and exit 2 rather than becoming agent failures. README uses the deliberately rejected literal `placeholder` and tells operators to replace it.
- FIX: Live traces derive only unambiguous numeric offers and fixture-value presentation order. Unsupported checks such as free-text lookup fabrication report `NOT_EVALUATED`, never PASS, and do not contribute to bounds.
- DECISION: The carrier is documented as a deterministic script parameterized by its walk-away utterance, not an adaptive policy; stateful adaptation would be a new capability outside this correction round.
- FIX: Empty/all-ungradable production exports exit 2, CI watches its workflow/setup/requirement files, the CPython 3.11/Linux dependency graph is fully version-locked, report Markdown carries actual evidence pointers, and generated caches/dead helpers were removed.
- VERIFIED: Integrated suite produced 55 passes, 5 strict xfails, and 26 subtests; replay passed 8/8 and mutation detection passed 3/3 before the final clean-room run.
- VERIFIED: A second clean clone at pinned commit `5a98a66274322954a0a6255f54650eec6e50c41d`, containing only the deliverables, created `/tmp/frontline-eval` from scratch. README deterministic commands reproduced: L1 8 passed/3 xfailed; L2 12 passed/2 xfailed; grader+safety 19 passed; full suite 55 passed/5 xfailed/26 subtests; replay 8/8; mutations 3/3; dry-run PASS. The literal rejected placeholder exited 2 before network access; absent `export.json` exited 2 as documented.

## 2026-10-09T13:58:00Z — Workspace save hygiene

- VERIFIED: Exhaustive scan excluding `.git` found no non-regular files. The only files over 200 KB are six pre-existing Git-tracked repository assets: three audio files, two source SVG logos, and `web/package-lock.json`; no evaluation deliverable exceeds 47 KB.
- FIX: Removed generated Python/pytest caches after verification. No venv, copied clone, socket, FIFO, symlink, or temporary lock tooling remains inside the workspace.
- VERIFIED: Refreshed suite: 55 passed/5 strict xfails/26 subtests; replay 8/8; mutation detection 3/3. Seeded evidence pointers in the regenerated Markdown resolve into its 47 KB JSON report.

## 2026-10-09T14:02:00Z — Snapshot-size diagnosis

- VERIFIED: No hosted save-policy file or relevant environment variable was discoverable under `/run/e3-hosted-codex`. No `requirements.lock`, non-standard-extension deliverable, or extensionless deliverable exists.
- HYPOTHESIS: The platform's generic “unsupported file or file over 200 KB” error is enforcing an aggregate changed-file budget: all untracked deliverables totaled 224,435 bytes even though the largest was 46,982 bytes.
- FIX: Report serialization now omits full traces for passing runs while retaining failure/error traces, all seeded-bad traces, and replay audit metadata. This preserves diagnostic JSON Pointers while reducing snapshot size.
- FIX: Dry-run reports retain model settings, initial messages, and production tool names rather than duplicating complete tool-schema bodies already covered by contract tests. The total untracked snapshot is now safely below both decimal and binary interpretations of 200 KB.
