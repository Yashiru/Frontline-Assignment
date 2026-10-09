# Context

- VERIFIED (workspace `find` output, 2026-10-09): the initially empty assessment workspace could not be saved after cloning because the checkout contained seven files over 200 KB: `.git/objects/pack/pack-e8e301a2bf93a01d29cfdadc378c31601d8967f0.pack` (1,553,049 bytes), `voice-agent/static/music/ring-tone-68676.mp3` (600,960), `voice-agent/static/audio/office_noise.wav` (480,078), `voice-agent/static/audio/hold_music.mp3` (351,789), `web/package-lock.json` (234,489), `web/public/designs/source/e3-logo.svg` (227,699), and `web/public/designs/source/e3-logo-light-mode.svg` (227,437). No symlinks or other non-regular filesystem entries were reported.
- VERIFIED (`git -C /tmp/frontline-review rev-parse HEAD`): the entire checkout, including `.git`, was moved to `/tmp/frontline-review`; it remains detached at `f93f7a5f79efdf08c18c583a6a6f7167084b93ae`.
- VERIFIED (workspace `find` output, 2026-10-09): the workspace now contains only regular-file `REVIEW_NOTES.md` (15,027 bytes) plus its directory; nothing remaining exceeds 200 KB.
- VERIFIED (checkout command): repository cloned from `https://github.com/e3-solutions/Frontline-Assignment.git`; review is detached at head `f93f7a5f79efdf08c18c583a6a6f7167084b93ae` against base `5a98a66274322954a0a6255f54650eec6e50c41d`.
- VERIFIED (PR API title/head.sha/base.sha): PR #1 is “COR-4078: Migrate voice calls and warm transfers to LiveKit/Telnyx”; API returned the same pinned head and base.
- VERIFIED (PR body, scope paragraph): transfer state remains process-local to a fixed single-call runner.
- VERIFIED (PR body, out-of-scope paragraph): durable restart recovery, provider-operation fencing, and voicemail classification are explicitly out of scope.
- VERIFIED (PR body, validation paragraph): real LiveKit/Telnyx calls, speech providers, Supabase storage, and end-to-end warm transfers were explicitly not exercised because they need provisioned dev services.

# Decisions

- VERIFIED (workspace relocation decision): all subsequent Git commands and test runs target `/tmp/frontline-review`; future test code/artifacts belong only under workspace `review_tests/`, while deliverables remain workspace `REVIEW_NOTES.md` and later `REVIEW.md`.
- VERIFIED (review procedure): all tracked files remain read-only; agent scratch used `/tmp`, and this file is untracked.
- VERIFIED (`voice-agent/requirements.txt:2,5,26`): baseline used the head dependency declaration, an external no-pip venv bootstrapped with get-pip.py, editable `./shared`, pytest, and pytest-asyncio.
- VERIFIED (`voice-agent/tests/test_phone_carrier_lookup.py:672-709`): “127 including 17 subtests” means 127 collected pytest items; 17 loop cases live inside five collected unittest methods (5+3+3+3+3), not 144 pytest items.
- QUESTION (`voice-agent/requirements.txt:2`): the local pydub import warning says ffmpeg/avconv is missing; deployment availability and relevance to exercised audio paths remain unverified.

# Evidence

## Pinning and diff

```text
$ git clone https://github.com/e3-solutions/Frontline-Assignment.git .
Cloning into '.'...
$ git fetch origin pull/1/head
From https://github.com/e3-solutions/Frontline-Assignment
 * branch            refs/pull/1/head -> FETCH_HEAD
$ git checkout --detach f93f7a5f79efdf08c18c583a6a6f7167084b93ae
HEAD is now at f93f7a5 feat(COR-4078): add LiveKit warm transfer lifecycle
$ git rev-parse HEAD
f93f7a5f79efdf08c18c583a6a6f7167084b93ae
$ git cat-file -t 5a98a66274322954a0a6255f54650eec6e50c41d
commit
$ git cat-file -t f93f7a5f79efdf08c18c583a6a6f7167084b93ae
commit
$ git merge-base 5a98a66274322954a0a6255f54650eec6e50c41d f93f7a5f79efdf08c18c583a6a6f7167084b93ae
5a98a66274322954a0a6255f54650eec6e50c41d
$ git diff --stat base...head
42 files changed, 3722 insertions(+), 1763 deletions(-)
```

Full stat printed in the session command output; principal voice files include `bot.py`, `livekit_ingress.py`, `livekit_telephony_service.py`, `livekit_transfer_media.py`, `orchestrator.py`, `room2_pipeline_service.py`, `server.py`, and their tests.

## Clean dependency/test baseline

- VERIFIED (`voice-agent/requirements.txt:2,5`): all declared extras installed; no fallback/skip was needed. Installed versions: `pipecat-ai 0.0.95`, `livekit-api 1.0.7`, `pytest 9.1.1`, `pytest-asyncio 1.4.0`.

```text
$ (cd voice-agent && /tmp/frontline-baseline-klWsGK/venv/bin/python -m pytest -ra)
collected 127 items
...
tests/test_voice_prompt_guardrails.py ...... [100%]
======================== 127 passed, 1 warning in 4.98s ========================

$ (cd shared && /tmp/frontline-baseline-klWsGK/venv/bin/python -m pytest -ra)
collected 91 items
...
tests/test_transfer_routing.py ............ [100%]
============================== 91 passed in 0.44s ==============================
```

- VERIFIED (`voice-agent/tests/test_phone_carrier_lookup.py:672-709`): PR test-count claims match exactly. Raw logs: `/tmp/frontline-pip-install.log`, `/tmp/frontline-voice-pytest.log`, `/tmp/frontline-shared-pytest.log`.

## PR-description claims inventory (not evaluated)

Each item below is HYPOTHESIS sourced from PR API field `body`, §Problem/§Changes/§Validation unless tagged otherwise:

1. HYPOTHESIS (PR body §Problem): Daily currently spans webhook ingress, room creation, Pipecat transport, outbound dialing, and Room1/Room2 broker transfer.
2. HYPOTHESIS (PR body §Problem): the change migrates provider boundaries to LiveKit/Telnyx while retaining the single-prompt negotiation agent and tool handlers.
3. HYPOTHESIS (PR body §Problem): transfer retains the carrier, briefs the broker, distinguishes answer from early media, confirms movement before success, and cleans both rooms across failure/disconnect/timeout/races.
4. HYPOTHESIS (PR body §Changes): signed LiveKit webhook ingress and typed LiveKit/Telnyx config replace Daily webhook/room pooling.
5. HYPOTHESIS (PR body §Changes): inbound/outbound calls use the existing single-prompt Pipecat pipeline over LiveKitTransport.
6. HYPOTHESIS (PR body §Changes): room/token/SIP participant/presence/verified-move/removal/cleanup boundaries are added.
7. HYPOTHESIS (PR body §Changes): carrier stays in Room1 with hold music while Room2 briefs the broker with negotiation/pricing context.
8. HYPOTHESIS (PR body §Changes): Room2 briefing requires `wait_until_answered` completion plus subscribed broker audio.
9. HYPOTHESIS (PR body §Changes): duplicate callbacks are serialized and answer, consultation, and Room1-arrival deadlines are bounded.
10. HYPOTHESIS (PR body §Changes): movement is reconciled; retry follows only conclusive source failure; ambiguity is quarantined without replay.
11. HYPOTHESIS (PR body §Changes): recoverable failures restore the original Room1 pipeline.
12. HYPOTHESIS (PR body §Changes): a post-handoff observer removes the remaining broker leg and deletes Room1 when either human leaves.
13. HYPOTHESIS (PR body §Changes): Room2 transcript is appended and consultation recording stored in transfer audit.
14. HYPOTHESIS (PR body §Changes): `call_transferred` is set only after broker confirmation in Room1.
15. HYPOTHESIS (PR body §Changes): Slack failures are isolated from telephony.
16. HYPOTHESIS (PR body §Changes): call records are attributed by provider and provider call IDs appear in dashboard.
17. HYPOTHESIS (PR body §Changes): Daily clients, pooling, dial-out, and hold-music modules are removed.
18. HYPOTHESIS (PR body §Changes): environment docs, local setup, dependencies, and CI are updated.
19. VERIFIED (`voice-agent/tests/test_phone_carrier_lookup.py:672-709` and raw pytest above): validation counts are 127 voice tests including 17 looped subtests and 91 shared tests.
20. HYPOTHESIS (PR body §Validation): transfer tests cover early media, answer gating, ordering, duplicates, dial/move failures, ambiguity, reconciliation, disconnect races, consultation timeout, recording flush, and cleanup.
21. HYPOTHESIS (PR body §Validation): changed Python modules compile, focused Ruff passes, dashboard `tsc --noEmit` passes, and installed API signatures were checked.

## Prior reviewer claims (inventory only; not evaluated)

Top-level reviews, sourced from `/pulls/1/reviews`:

- HYPOTHESIS (Kishorerh1993, review 5228648683, `livekit_transfer_media.py:57-62`): Pipecat 0.0.95 lacks pause/resume processing APIs, causing transfer failure; tests mock nonexistent APIs.
- HYPOTHESIS (Kishorerh1993, review 5228648683, `server.py:144-165`; `livekit_telephony_service.py:100-105`): request `from_phone` drives tenant context while configured outbound number drives SIP caller ID.
- HYPOTHESIS (Kishorerh1993, review 5228648683, `server.py:112-129`): duplicate-session check/add spans awaited startup and races.
- QUESTION (Kishorerh1993, review 5228648683): deployment concurrency and real SIP/provider behavior remain unknown; `.github/workflows/voice-agent-tests.yml:23-31` uses credential-shaped fixtures.
- HYPOTHESIS (Kishorerh1993, review 5228673637, `server.py:148-176`; `livekit_telephony_service.py:100-110`): a nominal 202 endpoint awaits answer and can block or re-raise no-answer/reject.
- HYPOTHESIS (Kishorerh1993, review 5228673637, `server.py:48,112-129`): dedupe state is unbounded, nonpersistent, process-local, and raced.
- HYPOTHESIS (Kishorerh1993, review 5228691260, `bot.py:65,630-646`; `server_utils.py:35-45`; `server.py:128`): one global task makes overlapping calls fail 409/503.
- VERIFIED (Kishorerh1993, review 5228757071, PR review body): reviewer later calls fixed-single-call limitation documented/nonblocking; QUESTION: production runner-per-call model.
- HYPOTHESIS (vipul-sharma20, review 5308975150, `orchestrator.py:198`; `bot.py:583`): hold UX telemetry and moved-participant SID preservation need validation; style/import concern also raised.
- HYPOTHESIS (tieincred, reviews 5439954916/5440038820, `room2_pipeline_service.py:254`; `livekit_ingress.py:201`): hold merge for identity gate/webhook race and two further blockers plus bounded-latency issue.
- VERIFIED (reviews API): reviews 5309368137 and 5406862897 have empty bodies.

All 14 inline claims, sourced from `/pulls/1/comments`:

1. HYPOTHESIS (vipul-sharma20, `orchestrator.py:198`, r4097444866): primary media gate precedes hold publisher readiness, risking a silence gap; QUESTION: measure gate→connection/first frame/failure.
2. HYPOTHESIS (vipul-sharma20, `bot.py:583`, r4097514914): retained Room2 SID may fail disconnect filtering if MoveParticipant changes SID; QUESTION: reconcile destination SID/identity and test differing SIDs.
3. QUESTION (vipul-sharma20, `livekit_telephony_service.py:164`, r4097765662): should move imports be top-level; do locals mask a cycle/design issue?
4. HYPOTHESIS (kzhdanov, `server.py:175`, r4178238622): `from_phone` tenant context diverges from configured outbound caller ID.
5. HYPOTHESIS (kzhdanov, `livekit_ingress.py:201`, r4178268844): decoded SIP kind is integer 3, `models_pb2` import fails, predicate returns false, real calls get 422.
6. HYPOTHESIS (kzhdanov, `room2_pipeline_service.py:254`, r4178283824): callback supplies SID while RTC map is identity-keyed, so readiness never sets; test masks it.
7. HYPOTHESIS (kzhdanov, `livekit_transfer_media.py:64`, r4178301643): pausing frames does not stop independent audio queue/task, so held carrier audio still reaches STT/context/tools.
8. HYPOTHESIS (kzhdanov, `orchestrator.py:220`, r4178305159): carrier-hangup terminal state does not fence coroutine; later awaits overwrite phase/dial/leak.
9. HYPOTHESIS (kzhdanov, `server.py:140`, r4178312939): inbound participant is already connected and start failure does not clean room, stranding caller; QUESTION: confirm isolated runner model.
10. HYPOTHESIS (tieincred, `room2_pipeline_service.py:254`, r4204972005): same SID-vs-identity readiness issue; test both event orders.
11. HYPOTHESIS (tieincred, `server.py:123`, r4204972007): dedupe precheck occurs before await and add after; shared store needed under replicas.
12. HYPOTHESIS (tieincred, `orchestrator.py:171`, r4205035715): room creation can finish after carrier terminal cleanup and continue/leak; late dial similar.
13. HYPOTHESIS (tieincred, `server.py:175`; `livekit_telephony_service.py:112`, r4205035723): tenant/caller-ID mismatch.
14. HYPOTHESIS (tieincred, `orchestrator.py:215`; `transfer_notifier.py:55`, r4205035727): held carrier precedes awaited Slack notification; default aiohttp timeout can stall deadlines.

## Base system before PR (base worktree `/tmp/frontline-base.4UPmm4`)

- VERIFIED (`server.py:100-126`): unauthenticated `POST /daily-webhook` parses JSON; `server_utils.py:63-88` requires From/To/callId/callDomain.
- VERIFIED (`server.py:128-163`; `server_utils.py:91-116,137-163`): ingress obtains a pooled Daily room, background-starts the bot, and returns room URL/token before startup finishes.
- VERIFIED (`bot.py:681-754`): bot validates AgentRequest, installs Daily dial-in settings, creates DailyTransport, and calls `run_bot`.
- VERIFIED (`bot.py:522-606`): call start waits for dial-in and participant, uses `_call_started` one-shot, starts recording, schedules DB insert, then queues initial LLM; fallback participant path checks dial-in and duplicates.
- VERIFIED (`call_helpers.py:71-106`; `db_operations.py:85-139`): start persistence defaults +1, suppresses DB errors, resolves organization by dialed number, inserts keyed by `daily_call_id`; no upsert/constraint is visible in this path.
- VERIFIED (`transfer_tool_handler.py:46-163`): transfer validates load/routing, speaks status, then schedules orchestration; no handler-local duplicate guard.
- VERIFIED (`orchestrator.py:147-253`): transfer marks state, starts hold, cancels Room1 bot, creates/starts Room2, notifies, sleeps 2s, dials broker, awaits completion; finally always sets completion.
- VERIFIED (`room2_pipeline_service.py:78-258`): Room2 creates its own Daily transport/STT/TTS/LLM/context/pipeline, identifies the non-bot participant, and captures SIP session from dialout events.
- VERIFIED (`orchestrator.py:308-320`; `daily_api_client.py:115-151`): outbound uses Daily dial-out with bearer auth and 30s HTTP timeout.
- VERIFIED (`transfer_tool_handler.py:165-205`; `orchestrator.py:337-383`): Room2→Room1 transfer uses context session ID, then stops hold/Room2, destroys Room2, and marks complete.
- VERIFIED (`orchestrator.py:402-428`): fallback stops/destroys Room2, sleeps 2s, redials broker into Room1, stops hold, marks complete.
- VERIFIED (`orchestrator.py:74-98`): transfer Event wait has no timeout; completion set is repeat-safe.
- VERIFIED (`bot.py:608-674`; `room_pool_service.py:163-182`; `db_operations.py:218-260`): disconnect stops recording/task and generation-safely returns Room1; final flow awaits pipeline/transfer, closes HTTP session, then persists result/end/reason/transcript.
- VERIFIED (`daily_api_client.py:25-38,109-143`; `server.py:100-163,186-203`): Daily REST uses bearer auth, while webhook and `/return-room` show no application-layer signature/API-key check.
- VERIFIED (`orchestrator.py:245-253`): exception finally only marks completion; it does not itself stop hold/Room2 or destroy Room2.
- HYPOTHESIS (`server.py:100-163`; `db_operations.py:85-139`): duplicate webhooks may create another room/bot/call because this path shows neither event-id dedupe nor insert upsert.

## Head change map by boundary

Raw inventory:

```text
$ git -C /tmp/frontline-review diff --stat 5a98a662...f93f7a5f
42 files changed, 3722 insertions(+), 1763 deletions(-)
$ git -C /tmp/frontline-review diff --name-status 5a98a662...f93f7a5f
D voice-agent/daily_api_client.py
D voice-agent/dial_out.py
D voice-agent/hold_music_bot.py
D voice-agent/room_pool_service.py
A voice-agent/livekit_ingress.py
A voice-agent/livekit_telephony_service.py
A voice-agent/livekit_transfer_media.py
A voice-agent/telephony_config.py
A voice-agent/tests/test_livekit_*.py
A voice-agent/tests/test_room2_pipeline_service.py
A voice-agent/tests/test_server_livekit.py
A voice-agent/tests/test_telephony_config.py
A web/supabase/migrations/20260907000000_add_livekit_call_attribution.sql
```

### Webhook ingress

- VERIFIED (`voice-agent/server.py:108-145`; `voice-agent/livekit_ingress.py:64-93`): `/daily-webhook` became `/livekit-webhook`; raw body and Authorization header are signature-verified before parsing, and invalid/missing signatures return 401.
- VERIFIED (`voice-agent/livekit_ingress.py:111-188`): only verified `participant_joined` SIP events with required attributes, configured trunk/rule IDs, and E.164 numbers are accepted.
- VERIFIED (`voice-agent/livekit_ingress.py:195-205`): integer SIP-kind handling depends on importing `livekit.protocol.models_pb2.ParticipantInfo`; failure rejects integer kinds, so the old phone-leg recognition invariant is intended but not established against the installed event shape.
- VERIFIED (`voice-agent/server.py:53,123-141`): process-local `seen_livekit_events` adds dedupe, but check/add spans awaited startup; shared/durable/bounded/race-free dedupe is not enforced.
- VERIFIED (`voice-agent/daily_api_client.py`, deleted; `voice-agent/server.py:108-145`): Daily ingress/control was removed.

### Call start and bot runner

- VERIFIED (`voice-agent/bot.py:465-567,661-669`): LiveKit transport replaces Daily runner/dial-in setup; start matches webhook participant SID with identity fallback, retains `_call_started`, then starts recording, async persistence, and initial LLM frame.
- VERIFIED (`voice-agent/bot.py:577-600`): disconnect filters unrelated participants and routes carrier/broker departure into transfer cleanup before recording/task shutdown.
- VERIFIED (`voice-agent/bot.py:69,672-704`): BotRunner returns 202 after task creation but still allows only one global active bot task; overlapping calls get 409.
- VERIFIED (`voice-agent/server.py:62-72,140,180`): webhook/outbound await starter HTTP response rather than call completion; starter failure occurs before inbound event is marked seen.
- VERIFIED (`voice-agent/server.py:126-145,181-183`): unlike outbound failure, inbound bot-start failure does not delete the already-existing LiveKit room.
- VERIFIED (`voice-agent/room_pool_service.py`, deleted): pooled room allocation/return and its generation/cap invariant were removed rather than replaced.

### Telephony service

- VERIFIED (`voice-agent/livekit_telephony_service.py:181-237`): new service creates/deletes uniquely named rooms, issues scoped JWTs, and creates Telnyx-backed SIP participants.
- VERIFIED (`voice-agent/livekit_telephony_service.py:239-360`): adds presence polling, verified movement, reconciliation, removal, and not-found handling.
- VERIFIED (`voice-agent/livekit_telephony_service.py:283-352`): direct Daily SIP-session transfer became move/check-source-and-destination/retry-only-after-conclusive-source-presence; ambiguity raises `ParticipantMoveOutcomeUnknown`.
- VERIFIED (`voice-agent/server.py:147-192`): API-key-protected outbound creates room, dials, starts agent, and deletes room on startup exception.
- VERIFIED (`voice-agent/server.py:157-175`; `voice-agent/livekit_telephony_service.py:222-237`): request `from_phone` becomes bot/tenant number while gateway caller ID always uses configured outbound number; equivalence is not enforced.
- VERIFIED (`voice-agent/dial_out.py`; `voice-agent/daily_api_client.py`, deleted): Daily dial/control clients were removed.

### Transfer orchestration and state

- VERIFIED (`voice-agent/transfer_state.py:11-118`): explicit phases, attempts/timestamps, terminal reason, provider and participant IDs, transcript/recording, and audit snapshot replace simpler transfer state.
- VERIFIED (`voice-agent/orchestrator.py:83-94,145-155`): attempt lock serializes duplicate callbacks and completion remains repeat-safe.
- VERIFIED (`voice-agent/orchestrator.py:171-259`): flow creates Room2, holds carrier, starts Room2, awaits notifier, dials under 45s default, requires answered+media readiness, and applies 180s consultation timeout.
- VERIFIED (`voice-agent/orchestrator.py:266-405`): handoff is legal only during consultation, uses verified identity movement, quarantines ambiguity, handles human disconnects, and sets `call_transferred` only after confirmed arrival and media cleanup.
- VERIFIED (`voice-agent/orchestrator.py:471-553`): terminal failure cleans Room2 and restores/quarantines/tears down primary media; cleanup retries twice and Slack failure is caught.
- VERIFIED (`voice-agent/orchestrator.py:215`): Slack is still awaited after hold and before dialing, with no timeout visible here.
- VERIFIED (`voice-agent/orchestrator.py:171-229`): no terminal/cancellation fence follows awaited create-room, hold-start, or dial; late-completion races are not eliminated.
- VERIFIED (`voice-agent/transfer_state.py:26-118`): process-local state remains; durable recovery/provider-operation fencing remain absent.

### Hold media

- VERIFIED (`voice-agent/livekit_transfer_media.py:57-69`): primary gate calls Pipecat pause/resume processing.
- VERIFIED (`voice-agent/livekit_transfer_media.py:71-143,155-200`): in-process LiveKit hold transport/task replaces deleted `hold_music_bot.py`; connection is bounded and stop can retain observer/unpublish audio or restore/quarantine media.
- VERIFIED (`voice-agent/orchestrator.py:197-199`): primary media gates before hold connects; continuous caller audio has no atomic enforcement and a silence gap remains plausible.
- VERIFIED, CORRECTION (Pipecat 0.0.95 `frames.py` class hierarchy; `frame_processor.py:578-596,880-920`; `base_input.py:215-225,257-264,453-480`; LiveKit transport `transport.py:727-748`; `review_tests/test_pause_gate.py`): `InputAudioRawFrame` is a `SystemFrame`, so `pause_processing_frames()` does not block it. That method blocks only the processor's non-system queue and does not set BaseInputTransport `_paused`; real caller audio continues downstream during hold. The prior queue-and-drain conclusion in this document was wrong.
- VERIFIED (`voice-agent/livekit_transfer_media.py:57-69`; executable output below): while hold suppresses TTS via context state, Room1 input/STT continues to receive carrier audio.

### Room2 pipeline

- VERIFIED (`voice-agent/room2_pipeline_service.py:97-186`): fresh LiveKit/STT/TTS/LLM/context pipeline is seeded from Room1 and exposes only the return-to-carrier transfer tool.
- VERIFIED (`voice-agent/room2_pipeline_service.py:203-230,343-356`): transcript/recording URL are captured; stop flushes recording, cancels/awaits pipeline, and handles callback tasks.
- VERIFIED (`voice-agent/room2_pipeline_service.py:243-300`): expected broker SID/identity gate uses transport metadata and then internal `remote_participants.get(participant_id)` fallback.
- VERIFIED (`voice-agent/room2_pipeline_service.py:314-341`): opening LLM/recording wait for answered dialing and subscribed audio under a deadline.
- VERIFIED DEFECT (`voice-agent/room2_pipeline_service.py:247-268`; installed LiveKit `rtc/room.py:213-221`; installed Pipecat LiveKit `transport.py:400-417,508-538`): events supply SID, but real `remote_participants` is indexed by identity; both Pipecat metadata lookup and PR fallback look up SID. Identity stays absent, expected identity rejects the real broker, and readiness never sets.

### Persistence and migration

- VERIFIED (`voice-agent/call_helpers.py:71-107`; `voice-agent/db_operations.py:85-143`): persistence retains +1 default, org lookup from bot phone, suppressed helper failures, and plain insert; attribution changes from `daily_call_id` to provider/provider call ID.
- VERIFIED (`web/supabase/migrations/20260907000000_add_livekit_call_attribution.sql:1-22`): migration adds checked provider, nullable provider ID, and non-unique partial lookup index; no uniqueness invariant prevents duplicate provider calls.
- VERIFIED (`voice-agent/bot.py:539-564,629-654`; `voice-agent/transfer_state.py:104-117`): creation remains asynchronous; final record appends consultation messages and bounded audit/recording/cleanup state.

### Config

- VERIFIED (`voice-agent/telephony_config.py:31-88,99-198`): typed LiveKit/Telnyx config replaces Daily variables and validates credentials, trunk/rule/outbound data, room prefix, and E.164.
- VERIFIED (`voice-agent/server.py:74-106`): invalid config prevents provider construction and makes health degraded/503.
- VERIFIED (`voice-agent/requirements.txt:2,5`): dependencies moved to LiveKit; tested installed versions are Pipecat 0.0.95 and LiveKit API/RTC 1.0.7.
- QUESTION (`voice-agent/requirements.txt:2`): deployment ffmpeg/avconv availability remains unverified.

### Dashboard

- VERIFIED (`web/src/services/dashboard.ts:156-183`; `web/src/services/supabase/server/dashboard.ts:41-59`): queries/mapping add provider-neutral attribution with legacy Daily fallback.
- VERIFIED (`web/src/components/dashboard/CallCard.tsx:144-155,227,333-336,422`; `web/src/types/dashboard.ts`; `DashboardClient.tsx`): labels, accessibility text, filenames, details, types, and keys use provider-neutral identity; the provider ID remains customer-visible.

### Tests

- VERIFIED (`voice-agent/tests/test_livekit_ingress.py`; `test_livekit_telephony_service.py`; `test_livekit_transfer_media.py`; `test_livekit_transfer_orchestrator.py`; `test_room2_pipeline_service.py`; `test_server_livekit.py`; `test_telephony_config.py`): new tests cover ingress/config/service/media/orchestration/Room2/server behaviors.
- VERIFIED (`voice-agent/tests/test_room2_pipeline_service.py:14-17`; installed LiveKit `rtc/room.py:213-221`): Room2 fake encodes impossible SID-keyed `remote_participants` semantics and therefore does not establish the production identity gate.
- QUESTION (PR body validation limits): no real provider/SIP/Supabase/speech/E2E test enforces SDK event shapes, SID/identity semantics, hold isolation, or multi-replica dedupe.

## Direct Pipecat/LiveKit test-double audit

| Test | Mocked target | Exists in installed version | Real behavior matches test assumption |
|---|---|---|---|
| `test_livekit_transfer_media.py:10-14` | `LiveKitTransport.input()`; inherited `pause_processing_frames`/`resume_processing_frames` | VERIFIED (Pipecat `transport.py:1008-1018`; `frame_processor.py:578-596`) | VERIFIED DEFECT: invocation-only fake misses that input audio is a SystemFrame and continues downstream during pause (`base_input.py:453-480`; executable test below). |
| `test_livekit_transfer_media.py:16` | `PipelineTask.cancel()`/`queue_frame()` | VERIFIED (`task.py:452-459,502-508`) | VERIFIED: both async; cancel is finish-idempotent and queue_frame enqueues. |
| `test_livekit_transfer_media.py:56-66` | `_client._audio_track.sid`; `room.local_participant.unpublish_track(sid)` | VERIFIED (Pipecat `transport.py:208-210,227-239,298-307`; LiveKit `rtc/track.py:31-33`, `rtc/room.py:193-202`, `rtc/participant.py:708-727`) | VERIFIED: async unpublish accepts SID and sends `stop_on_unpublish=True`. |
| `test_livekit_ingress.py:46-55` | Webhook/room/participant protobuf fields and SIP kind | VERIFIED (installed protobuf descriptors: WebhookEvent id/event/room; ParticipantInfo sid/identity/kind/attributes; SIP=3) | VERIFIED shape; HYPOTHESIS fidelity gap: test string `SIP`, real kind enum/integer. |
| `test_livekit_ingress.py:59-75` | `WebhookReceiver.receive(body, auth)` | VERIFIED (`livekit/api/webhook.py:8-23`) | VERIFIED synchronous behavior; async fake is intentional injection behavior, not the SDK. |
| `test_room2_pipeline_service.py:19-27` | `event_handler()`; `get_participant_metadata()` | VERIFIED (Pipecat `base_object.py:101-115,175-188`; LiveKit transport `transport.py:400-417,508-538,1058-1067,1105-1116`) | VERIFIED callback gets `(transport, participant_sid)` and metadata may be `{}`. |
| `test_room2_pipeline_service.py:14-17` | `_client.room.remote_participants.get(SID).identity` | VERIFIED attributes exist | VERIFIED DEFECT: behavior does not match. Real map is identity-keyed (`livekit/rtc/room.py:213-221`), not SID-keyed. |
| `test_room2_pipeline_service.py:36-39` | `PipelineTask.queue_frames()`/`cancel()` | VERIFIED (`task.py:452-459,510-521`) | VERIFIED: frames enqueue individually and cancellation is awaited. |
| `test_room2_pipeline_service.py:40-43` | `AudioBufferProcessor.start_recording()`/`stop_recording()` | VERIFIED (`audio_buffer_processor.py:167-182`) | VERIFIED: start resets/enables; stop flushes handler, resets, disables. |

- VERIFIED (audit scope): PR-owned `FakeGateway`, `FakeTelephony`, `FakeMedia`, `FakeRoom2`, and `FakeNotifier`, plus environment monkeypatches, are not direct Pipecat/LiveKit doubles and were excluded from this installed-class table.
- VERIFIED (raw introspection): `LiveKitInputTransport.pause_processing_frames(self)` resolves to Pipecat `frame_processor.py:578`; resume to `:592`; `LiveKitTransport.input()` to `transport.py:1008`; `get_participant_metadata()` to `:1058`; `LocalParticipant.unpublish_track()` to LiveKit `participant.py:708`; `WebhookReceiver.receive()` to `webhook.py:12`.

## Executable SDK regressions

Environment versions:

```text
livekit 1.0.25
livekit-api 1.0.7
livekit-protocol 1.1.27
pipecat-ai 0.0.95
```

VERIFIED (`review_tests/test_pause_gate.py`): a real `BaseInputTransport` subclass and real Pipecat pipeline were started, `pause_processing_frames()` was called, audio was fed through `push_audio_frame()`, and a downstream real `FrameProcessor` captured it while paused:

```text
frame_class=InputAudioRawFrame mro=(<class 'pipecat.frames.frames.InputAudioRawFrame'>, <class 'pipecat.frames.frames.SystemFrame'>, <class 'pipecat.frames.frames.Frame'>, <class 'pipecat.frames.frames.AudioRawFrame'>, <class 'object'>)
transport_paused_flag=False
captured_while_process_frames_paused=1
```

VERIFIED (`review_tests/test_room2_identity.py`; installed LiveKit 1.0.25 `livekit/rtc/room.py:213-221`; Pipecat 0.0.95 LiveKit `transport.py:400-417,508-511,530-538`): real LiveKit maps participants by identity, Pipecat callbacks pass SID, and Pipecat metadata lookup uses that SID as a map key. Driving production handlers with the real mapping semantics produces:

```text
remote_participant_keys=['broker-expected']
callback_participant_id=PA_broker
broker_connected=False
broker_media_ready=False
opening_started=False
wait_for_broker=TimeoutError
2 passed, 2 warnings in 3.35s
```

- VERIFIED (`voice-agent/orchestrator.py:217-242,257-259,566-570`; `voice-agent/room2_pipeline_service.py:314-341`): after the provider reports answer, readiness waits only for the remainder of the default 45-second broker deadline, raises `BrokerMediaTimeout`, and records terminal reason `broker_media_timeout` (not the 180-second consultation timeout).
- VERIFIED (`voice-agent/room2_pipeline_service.py:320-328`; `voice-agent/orchestrator.py:471-495`): the broker hears no Room2 opening/briefing because the LLM frame and recording never start; the carrier remains on hold until timeout, after which Room2 is cleaned, Room1 is restored, and the carrier hears `TRANSFER_UNAVAILABLE_MESSAGE` (subject to suppressed media exceptions).

## Ranked candidate risk map (investigation queue only)

1. **H1 — VERIFIED DEFECT** (`voice-agent/room2_pipeline_service.py:246-268`): identity-key mismatch prevents broker readiness. Impact: carrier holds until media timeout; answered broker hears no briefing. Likelihood: very high (executable proof). Cheapest proof: completed `review_tests/test_room2_identity.py`.
2. **H2 — HYPOTHESIS** (`voice-agent/orchestrator.py:171-233,316-324`): carrier hangup does not fence pending create/hold/dial awaits. Impact: broker may still be dialed after carrier leaves; terminal callback owns Room2 cleanup while resumed transfer still owns late participant/room resources. Likelihood: high (no post-await terminal checks). Cheapest proof: block dial, call `on_carrier_left_primary`, resolve dial, assert no late state/resource mutation.
3. **H3 — HYPOTHESIS** (`voice-agent/livekit_telephony_service.py:283-351`; `voice-agent/orchestrator.py:294-300,471-513`; `voice-agent/livekit_transfer_media.py:167-171`): ambiguous move quarantines with retained observer but no later deadline/reconciliation. Impact: humans may remain connected in silence/billing and observer may leak. Likelihood: medium-high. Cheapest proof: reconcile participant in neither room; assert retained observer/detached publishers and no scheduled cleanup.
4. **H4 — HYPOTHESIS** (`voice-agent/livekit_telephony_service.py:97-123`; `voice-agent/orchestrator.py:220-243`): voicemail counts as broker answer. Impact: private pricing/load briefing can play to voicemail while carrier waits. Likelihood: high; classification is out of scope. Cheapest proof: answered+audio gateway stub without human classifier and assert opening starts.
5. **H5 — HYPOTHESIS** (`voice-agent/server.py:162-183`; `voice-agent/livekit_telephony_service.py:108-118`): `/outbound-call` awaits `wait_until_answered=True`. Impact: nominal 202 blocks through ringing; no-answer/reject may surface as 5xx and prompt retries. Likelihood: high. Cheapest proof: pending/raising dial stub against route.
6. **H6 — HYPOTHESIS** (`voice-agent/bot.py:69,689-704`): one global runner rejects overlap. Impact: second caller gets 409 after ingress may already have connected them. Likelihood: high if calls share a process. Cheapest proof: pending `_active_bot_task`, second `/start`.
7. **H7 — HYPOTHESIS** (`voice-agent/server.py:53,123-141`): webhook dedupe is non-atomic, process-local, unbounded, non-durable. Impact: duplicate bot starts/call records; replica/restart misses. Likelihood: medium-high. Cheapest proof: barrier-controlled concurrent identical webhooks.
8. **H8 — HYPOTHESIS** (`voice-agent/server.py:157-176`; `voice-agent/livekit_telephony_service.py:108-117`): request `from_phone` drives tenant context while configured outbound number is caller ID. Impact: wrong tenant/prompt/attribution and displayed caller ID mismatch. Likelihood: high when values differ. Cheapest proof: post differing E.164 values and capture SIP number versus AgentRequest.
9. **H9 — HYPOTHESIS** (`voice-agent/bot.py:577-600`; `voice-agent/orchestrator.py:230-232,286-307`): broker SID is not refreshed after MoveParticipant. Impact: if SID changes, broker disconnect is ignored and humans/observer/room remain. Likelihood: medium, provider semantic unresolved. Cheapest proof: stored Room2 SID then emit destination disconnect with different SID.
10. **H10 — HYPOTHESIS** (`voice-agent/orchestrator.py:532-540`): cleanup retries use `sleep(0)` only. Impact: propagation/rate-limit failures immediately repeat then leak rooms/legs. Likelihood: medium-high during incidents. Cheapest proof: operation succeeds only after virtual delay; assert two same-turn failures.
11. **H11 — HYPOTHESIS** (`voice-agent/orchestrator.py:197-199`): primary gate precedes hold connection. Impact: deterministic silence gap, potentially through hold-connect timeout. Likelihood: high. Cheapest proof: timestamps for gate, connection, first published frame.
12. **H12 — HYPOTHESIS** (`voice-agent/orchestrator.py:203-220,542-553`): Slack is awaited after hold but before dial without a visible bound. Impact: carrier waits in hold while broker dialing has not begun. Likelihood: medium. Cheapest proof: never-resolving notifier; assert dial never called.

## Consequence and race probes

### Room1 remains active and its tools execute during/post handoff

- VERIFIED (`voice-agent/bot.py:343-354`; installed Pipecat behavior; `review_tests/test_pause_gate.py`): Room1 pipeline order remains input → STT → user context → LLM → TTS gate, and caller/human audio reaches it during `TRANSFER_HOLD`; suppressing TTS does not suspend STT, context aggregation, LLM, or tools.
- VERIFIED (`voice-agent/livekit_transfer_media.py:57-69,111-171`; `voice-agent/orchestrator.py:369-405`): gate sets `call_mode="TRANSFER_HOLD"`; successful handoff retains the observer and detaches audio but never sets `HUMAN_ONLY` or cancels Room1 until a later departure.
- VERIFIED (`voice-agent/call_helpers.py:655-762,765-849`; `review_tests/test_post_handoff_tools.py`): `record_agreement` has no phase guard and `end_call` blocks only exact `HUMAN_ONLY`. With real handlers at `TRANSFER_HOLD`, agreement persistence and KCH quote notification execute, and `end_call` queues `EndFrame`.

```text
call_mode=TRANSFER_HOLD
end_call_result={'status': 'success', 'message': 'Call ending with reason: agreement'}
queued_frame=EndFrame
call_mode=TRANSFER_HOLD
record_agreement_result={'status': 'success', 'message': 'Agreement recorded at $2500.0', 'negotiation_id': '00000000-0000-0000-0000-000000000003'}
save_agreement_calls=1
notify_carrier_quote_calls=1
2 passed, 1 warning in 1.20s
```

- VERIFIED IMPACT (`voice-agent/call_helpers.py:709-758,827-844`): after handoff, Room1 can interpret carrier/broker speech, record an agreement/quote in KCH, notify carrier quote, and terminate the call, even though the bot is meant to be an observer and its TTS is suppressed.

### Carrier departure during hold startup

- VERIFIED DEFECT (`voice-agent/orchestrator.py:198-229,316-324,471-530`; `review_tests/test_carrier_hangup_during_hold.py`): carrier departure re-enters terminal cleanup inside `start_hold`; cleanup deletes Room2 and records `carrier_disconnected`, but the owner coroutine resumes without liveness check, starts a new Room2 pipeline, dials the broker, and transitions state to `CONSULTING` while transfer is no longer in progress.
- VERIFIED (`review_tests/test_carrier_hangup_during_hold.py`): the newly constructed Room2 pipeline was started, never stopped, and remained attached after the completed attempt; broker dialing occurred after carrier departure.

```text
observed: dial_count=1 deleted_rooms=['room-2'] phase=consulting reason=carrier_disconnected room2_started=True room2_stopped=False room2_attached=True media_cleanup_count=1
PASSED
1 passed, 2 warnings in 4.07s
```

### Ambiguous move: neither room

- VERIFIED DEFECT (`voice-agent/livekit_telephony_service.py:283-350`; `voice-agent/orchestrator.py:286-301,476-530`; `voice-agent/livekit_transfer_media.py:111-139,167-171`; `review_tests/test_ambiguous_move.py`): real service/orchestrator/media with provider reporting the broker in neither room transitions `CONSULTING → FAILED` with `handoff_outcome_unknown` and deletes Room2, but does not restore input, end primary pipeline, stop retained observer, or delete Room1 within the bounded probe.

```text
phase_before=consulting
phase_after=failed
terminal_reason=handoff_outcome_unknown
gateway_calls=[('move', ...), ('exists', Room1), ('exists', Room1), ('exists', Room2), ('delete', 'Room2')]
primary_input_resumed=0
primary_pipeline_cancelled=False
hold_observer_retained=True
hold_task_still_owned=True
room1_deleted_after_bounded_wait=False
1 passed, 2 warnings in 3.65s
```

- VERIFIED (`voice-agent/livekit_transfer_media.py:126-139,167-171`): quarantine deliberately retains/unpublishes the observer and detaches primary output; no later reconciliation/deadline is installed by this path.
- HYPOTHESIS (provider billing depends on external terms): carrier/broker legs and Room1 can remain live, silent, and billable indefinitely until external disconnect/cleanup.

## Prior-review verdicts

Complete evidence and raw commands are in `review_tests/prior_review_verdicts.md`; every top-level review and all 14 inline comments are covered.

| Reviewer claim | Verdict | Evidence |
|---|---|---|
| Kishorerh1993 5228648683: pause/resume absent, every transfer raises AttributeError | REFUTED | Installed Pipecat methods at `frame_processor.py:578,592`; `review_tests/test_pause_gate.py`. Separate pause-semantics defect is confirmed. |
| Kishorerh1993 5228648683; kzhdanov r4178238622; tieincred r4205035723: `from_phone`/caller-ID divergence | CONFIRMED | `voice-agent/server.py:157-176`; `livekit_telephony_service.py:108-117`. |
| Kishorerh1993 5228648683/5228673637; tieincred r4204972007: webhook dedupe race/process locality | CONFIRMED | `voice-agent/server.py:53,123-141`. |
| Kishorerh1993 5228648683: unknown concurrency/provider behavior; credential-shaped CI fixtures | PARTIALLY RIGHT | `.github/workflows/voice-agent-tests.yml:23-33`; unknown provider/topology valid, test fixtures alone are not a defect. |
| Kishorerh1993 5228673637: outbound 202 blocks on answer and propagates failure | CONFIRMED | `voice-agent/server.py:162-191`; `livekit_telephony_service.py:108-118`. |
| Kishorerh1993 5228691260/5228757071: single global runner rejects overlap | PARTIALLY RIGHT | Mechanism confirmed at `voice-agent/bot.py:69,689-704`; merge impact depends on unestablished runner-per-call deployment. |
| vipul-sharma20 5308975150/r4097444866: gate precedes hold readiness | CONFIRMED | `voice-agent/orchestrator.py:192-199`. |
| vipul-sharma20 5308975150/r4097514914: moved SID may change | QUESTION | Storage/filter path is `orchestrator.py:230-232,286-307`; `bot.py:577-585`; primary protocol/SDK source inspected does not guarantee SID preservation. |
| vipul-sharma20 r4097765662: local imports indicate runtime/design failure | REFUTED | `livekit_telephony_service.py:105,133,147,164`; imports execute and suite passes; no behavioral defect shown. |
| kzhdanov r4178268844; tieincred summaries: integer SIP kind rejected | CONFIRMED | `livekit_ingress.py:195-205`; installed import raises `ModuleNotFoundError`, kind 3 returns false; protocol defines SIP=3. |
| kzhdanov r4178283824; tieincred r4204972005: Room2 SID/identity mismatch | CONFIRMED | `room2_pipeline_service.py:246-268`; installed LiveKit `rtc/room.py:213-221`; `review_tests/test_room2_identity.py`. |
| kzhdanov r4178301643: hold pause does not isolate caller audio | CONFIRMED | `livekit_transfer_media.py:57-69`; `review_tests/test_pause_gate.py`. |
| kzhdanov r4178305159; tieincred r4205035715: terminal cleanup does not fence owner coroutine | CONFIRMED | `orchestrator.py:171-229,316-324,471-513`; `review_tests/test_carrier_hangup_during_hold.py`. |
| kzhdanov r4178312939: inbound start failure strands room/caller | CONFIRMED | `server.py:126-140` versus outbound cleanup `:181-183`. |
| tieincred r4205035727: Slack wait is unbounded after hold/before dial | CONFIRMED | `orchestrator.py:197-220,542-553`; `transfer_notifier.py:55-56`; installed aiohttp default total timeout is `None`. |
| tieincred 5439954916/5440038820 summary of blockers | PARTIALLY RIGHT | Identifiable SIP-kind, identity-gate, race, and latency claims confirmed; unspecified “two further blockers” cannot be separately adjudicated. |
- VERIFIED (reviews API inventory): reviews 5309368137 and 5406862897 have empty bodies and no claim to adjudicate.

# Findings

- VERIFIED (`voice-agent/tests/test_phone_carrier_lookup.py:672-709` and pytest raw output): the claimed unit-suite baselines are reproducible at the pinned head.
- VERIFIED (`voice-agent/requirements.txt:2,5` and installed-version output): head imports/tests install with Pipecat 0.0.95 and LiveKit API 1.0.7; no heavy extra failed or was skipped.
- HYPOTHESIS (prior-review inventory above): prior reviewers raised multiple material live-call risks, but this phase intentionally inventories rather than re-verifies them.
- VERIFIED, likely merge-blocking (`voice-agent/room2_pipeline_service.py:247-268`; `voice-agent/tests/test_room2_pipeline_service.py:14-17`; installed LiveKit `rtc/room.py:213-221`; installed Pipecat LiveKit `transport.py:400-417,508-538`): Room2 tests fake `remote_participants` as SID-keyed, while the real SDK keys by identity and emits SID callbacks. The production metadata lookup and fallback both miss, broker identity is rejected, media readiness never sets, and warm transfer times out.
- VERIFIED DEFECT (`voice-agent/livekit_transfer_media.py:57-69`; installed Pipecat `frame_processor.py:578-596,880-920`; `base_input.py:215-225,257-264,453-480`; `review_tests/test_pause_gate.py`): pause/resume APIs exist, but caller `InputAudioRawFrame` is a SystemFrame and continues downstream during hold. Room1 STT/LLM keeps hearing the carrier while TTS is suppressed. The current invocation-only fake cannot detect this.

# Questions

- QUESTION (`server.py:100-163`; schema not established by inspected base paths): is webhook authentication enforced upstream, and is `calls.daily_call_id` unique in the database?
- QUESTION (PR body out-of-scope paragraph): what production architecture enforces the fixed single-call runner assumption?
- QUESTION (`voice-agent/requirements.txt:2`): does the deployment image provide ffmpeg/avconv for pydub paths?
