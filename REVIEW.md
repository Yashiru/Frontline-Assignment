# Summary

This PR replaces Daily with LiveKit/Telnyx and adds a two-room warm-transfer lifecycle while preserving the single-prompt agent.
**Recommendation: Request changes.** Four verified defects break inbound or warm-transfer behavior and expose human-only audio to the agent.
Several blockers were also raised by kzhdanov and tieincred; this review independently reproduces them against pinned SDKs and production code, despite all 218 existing unit tests passing.
Daily is removed without a feature flag, dual-run path, or exercised rollback, and no real provider call has validated the replacement.
After fixes, require a provisioned qualification run covering inbound, outbound, answer/early-media, transfer, disconnect, ambiguity, and rollback.

# Review comments

## Blockers

### 1. Accept the installed SDK's integer SIP participant kind

**Anchor:** `voice-agent/livekit_ingress.py:195-205`

**Problem — VERIFIED:** Real protobuf participants expose SIP kind as integer `3`. The integer branch imports `livekit.protocol.models_pb2.ParticipantInfo`, but pinned `livekit-protocol 1.1.27` ships `livekit/protocol/models.py` and `models.pyi`, not `models_pb2.py`; the caught import failure returns false. `livekit-api 1.0.7` `WebhookReceiver.receive()` returns `Parse(body, WebhookEvent(), ignore_unknown_fields=True)`, so the parsed field retains its protobuf integer representation. This issue was previously raised by **kzhdanov** and included in **tieincred**'s blocker summary; this review independently verified the installed-package path.

**Live impact:** Every legitimate inbound SIP webhook using the installed decoded representation is rejected as non-SIP with 422 before the agent starts. Inbound carriers cannot reach the product.

**Evidence:** Direct execution and installed module/source inspection:

```text
livekit-protocol 1.1.27
models.py_present True
models_pb2.py_present False
model_files ['models.py', 'models.pyi']
participant_kind_int3= False
models_pb2_import= ModuleNotFoundError No module named 'livekit.protocol.models_pb2'
livekit/api/webhook.py:23 return Parse(body, WebhookEvent(), ignore_unknown_fields=True)
```

The installed protobuf descriptor and LiveKit protocol define `ParticipantInfo.Kind.SIP = 3`. Existing ingress tests use string `"SIP"`, so they do not exercise the real decoded representation.

**Suggested fix:** Import the enum from the package actually pinned, or compare against the generated descriptor/official enum without a version-specific private module. Add a test that sends a signed webhook through the real `WebhookReceiver` and asserts the decoded integer kind `3` is accepted.

### 2. Resolve Room2 participants by identity instead of indexing the identity map with a SID

**Anchor:** `voice-agent/room2_pipeline_service.py:246-268`

**Problem — VERIFIED:** Pipecat invokes these handlers with the participant SID, but `track_human()` passes that SID to `get_participant_metadata()` and then to `room.remote_participants.get()`. LiveKit 1.0.25 documents that map as identity-keyed. The production test double instead uses `{"PA_broker": participant}`, which hides the mismatch. **kzhdanov** and **tieincred** previously raised this mismatch; this review independently reproduces it with production handlers and real SDK map semantics.

**Live impact:** The provider reports that the broker answered, but Room2 rejects the broker identity. The broker hears no briefing, while the carrier remains on hold until the remainder of the 45-second broker deadline. The attempt records `broker_media_timeout`, cleans Room2, restores Room1, and announces transfer failure.

**Evidence:** `review_tests/test_room2_identity.py` drives the real handlers with LiveKit's identity-keyed shape:

```text
remote_participant_keys=['broker-expected']
callback_participant_id=PA_broker
broker_connected=False
broker_media_ready=False
opening_started=False
wait_for_broker=TimeoutError
```

Installed sources: LiveKit `rtc/room.py:213-221`; Pipecat LiveKit `transport.py:400-417,508-511,530-538`. Orchestration outcome: `voice-agent/orchestrator.py:217-242,257-259,566-570`.

**Suggested fix:** Resolve the participant from an identity-keyed map by the already-known expected identity, or maintain an explicit SID→identity mapping from the SDK participant object. Add an integration-shaped test using the real map semantics and both event orders before accepting readiness.

### 3. Stop Room1 input and tools during hold and after handoff

**Anchor:** `voice-agent/livekit_transfer_media.py:57-69`

**Problem — VERIFIED:** `pause_processing_frames()` does not pause LiveKit input audio. `InputAudioRawFrame` is a Pipecat `SystemFrame`, so it bypasses the non-system processing gate, while BaseInputTransport `_paused` remains false. Room1 continues feeding STT, context, and the LLM during hold and after handoff. The successful handoff path leaves `call_mode="TRANSFER_HOLD"`; `end_call` blocks only `HUMAN_ONLY`, and `record_agreement` has no phase guard. **kzhdanov** identified the ineffective input gate; **Kishorerh1993** pointed at the same API boundary but attributed it to nonexistent methods. This review refutes that mechanism and independently reproduces the actual semantics defect.

**Live impact:** The negotiation agent continues hearing the private carrier–broker conversation. Its speech is suppressed, but its real handlers remain able to persist an agreement, send a KCH carrier-quote notification, or queue `EndFrame` and terminate the call. **The open audio path and handler permissions are verified; the LLM actually choosing those tools from human conversation is a plausible consequence, not directly reproduced.**

**Evidence:** `review_tests/test_pause_gate.py` uses a real BaseInputTransport pipeline:

```text
frame_class=InputAudioRawFrame ... SystemFrame ...
transport_paused_flag=False
captured_while_process_frames_paused=1
```

`review_tests/test_post_handoff_tools.py` calls the real handlers:

```text
call_mode=TRANSFER_HOLD
end_call_result={'status': 'success', 'message': 'Call ending with reason: agreement'}
queued_frame=EndFrame
record_agreement_result={'status': 'success', 'message': 'Agreement recorded at $2500.0', ...}
save_agreement_calls=1
notify_carrier_quote_calls=1
```

Handler paths: `voice-agent/call_helpers.py:655-762,765-849`; pipeline order: `voice-agent/bot.py:343-354`; handoff media path: `voice-agent/orchestrator.py:369-405`.

**Suggested fix:** Use the input transport's actual pause/stop contract or an explicit audio-drop processor before STT, and cancel or detach the Room1 inference pipeline after successful handoff. Independently guard every mutating/terminal tool by transfer phase; allow them only while the bot is the active negotiator. Add tests proving no audio reaches STT and no tool can mutate state in hold/human-only phases.

### 4. Fence the transfer owner coroutine when the carrier leaves

**Anchor:** `voice-agent/orchestrator.py:197-213`

**Problem — VERIFIED:** If the carrier disconnect callback runs inside awaited `start_hold()`, `on_carrier_left_primary()` marks the attempt terminal and cleans Room2. When `start_hold()` returns, the original coroutine has no attempt-liveness check: it creates a new Room2 pipeline, dials the broker, and transitions the terminal state to `CONSULTING`. **kzhdanov** and **tieincred** previously raised unfenced terminal/late-completion races; this review independently reproduces the carrier-during-hold form.

**Live impact:** A broker is called after the carrier has already left. The newly created Room2 pipeline is never stopped and remains attached to an attempt that is no longer in progress.

**Evidence:** `review_tests/test_carrier_hangup_during_hold.py` uses the real orchestrator and fires the real terminal callback synchronously from `start_hold()`:

```text
observed: dial_count=1 deleted_rooms=['room-2'] phase=consulting
reason=carrier_disconnected room2_started=True room2_stopped=False
room2_attached=True media_cleanup_count=1
```

Terminal path: `voice-agent/orchestrator.py:316-324,471-530`; unfenced continuation: `:198-229`.

**Suggested fix:** Give each attempt an immutable generation/cancellation token. After every re-entrant/provider await—room creation, hold connection, Room2 startup, notification, dial, and move—verify the same attempt is still active before mutating state or starting another operation. Ensure terminal cleanup cancels and joins the owner task and any in-flight dial.

## Major

### 5. Give ambiguous moves a bounded recovery that ends or restores the call

**Anchor:** `voice-agent/orchestrator.py:286-301`

**Problem — VERIFIED:** When movement is submitted but the broker is found in neither room, the code records `handoff_outcome_unknown`, deletes Room2, and calls `quarantine_ambiguous_handoff()`. Quarantine retains and unpublishes the hold observer and detaches primary bot audio, but schedules no later reconciliation, deadline, or Room1 deletion.

**Live impact:** If the carrier remains in Room1, they hear silence with no bounded recovery. The retained observer and Room1 remain allocated; external provider billing duration is plausible but not measured here.

**Evidence:** `review_tests/test_ambiguous_move.py` uses the real telephony service, orchestrator, state, and media classes:

```text
phase_before=consulting
phase_after=failed
terminal_reason=handoff_outcome_unknown
primary_input_resumed=0
primary_pipeline_cancelled=False
hold_observer_retained=True
hold_task_still_owned=True
room1_deleted_after_bounded_wait=False
```

Quarantine implementation: `voice-agent/livekit_transfer_media.py:111-139,167-171`; terminal cleanup: `voice-agent/orchestrator.py:471-513`.

**Suggested fix:** After ambiguity, start a bounded reconciliation loop keyed by participant identity. Resolve to exactly one terminal action: restore Room1 if the broker conclusively remains outside it, complete the handoff if arrival is observed, or end/delete both call resources at deadline. Always stop the observer in the terminal branch.

### 6. Make webhook deduplication atomic and shared for the deployment model

**Anchor:** `voice-agent/server.py:123-141`

**Problem — VERIFIED BY TRACE:** The process-local set is checked before several awaits and updated only after bot startup. Concurrent deliveries can both pass; replicas and restarts share nothing; the set is unbounded.

**Live impact:** Duplicate LiveKit deliveries can start duplicate agents/call records, while a long-lived worker accumulates event IDs. This is especially risky if the deployment is not strictly one disposable process per call.

**Suggested fix:** Claim the event atomically before work in a bounded TTL store shared by all consumers, and define retry behavior for failed starts. Clarify whether LiveKit delivery retries and runner isolation change the required lifetime.

### 7. Do not hold the outbound HTTP request through provider answer

**Anchor:** `voice-agent/server.py:162-183`

**Problem — VERIFIED BY TRACE:** `/outbound-call` awaits `dial_phone()`, whose provider request sets `wait_until_answered=True`, before returning its nominal 202. Provider reject/no-answer exceptions are re-raised after cleanup.

**Live impact:** The caller of this API waits through ringing; upstream request timeouts can retry the operation, and ordinary reject/no-answer can appear as server failure rather than an accepted asynchronous call lifecycle.

**Suggested fix:** Return an operation/call ID after durable acceptance, run dialing in the call runner, and expose status. At minimum apply a documented route timeout and translate provider outcomes into stable API responses with idempotency.

### 8. Align authorized tenant identity with actual outbound caller ID

**Anchor:** `voice-agent/server.py:157-176`

**Problem — VERIFIED BY TRACE:** Request `from_phone` is placed into `AgentRequest.bot_phone` and drives organization/prompt attribution, while the SIP request always uses configured `livekit_outbound_number` (`voice-agent/livekit_telephony_service.py:108-117`). No equality or authorization relationship is enforced.

**Live impact:** The callee sees one caller ID while records and agent context can be attributed to another tenant/number.

**Suggested fix:** Derive both values from the same authorized server-side configuration, or validate that the requested sender is an allowed number and pass that exact number through to the SIP request.

### 9. Add a controlled rollout and provider qualification gate

**Anchor:** `voice-agent/transport_factory.py:1-98`

**Problem — VERIFIED:** Daily clients, room pooling, dial-out, and hold bot are removed outright. There is no feature flag, per-call provider selection, shadow/dual-run path, or exercised rollback. The PR explicitly did not run real LiveKit/Telnyx, speech-provider, Supabase, or end-to-end warm-transfer calls.

**Live impact:** Any provider-contract error affects all deployed calls immediately, and rollback requires redeploying code rather than switching traffic.

**Suggested fix:** Add a provider flag with a tested Daily fallback or a deployment-level instant rollback, then require a provisioned qualification matrix: signed inbound webhook with decoded protobuf, outbound answer/reject/no-answer/voicemail, early media, Room2 briefing, verified move, both-human disconnects, carrier hangup at every await boundary, ambiguous move, recording/persistence, and rollback.

## Minor / follow-up

### 10. Add backoff and an owner for failed cleanup

**Anchor:** `voice-agent/orchestrator.py:532-540`

**Problem — VERIFIED BY TRACE:** Cleanup attempts twice with only `await asyncio.sleep(0)`. Provider propagation and rate-limit failures are likely to fail twice in the same event-loop turn, after which cleanup is only logged.

**Suggested fix:** Use bounded exponential backoff with jitter and persist/emit cleanup-pending work to an observable reconciler.

### 11. Bound best-effort notifications before dialing

**Anchor:** `voice-agent/orchestrator.py:203-220`

**Problem — VERIFIED BY TRACE:** The carrier is already held when Slack notification is awaited, before the broker deadline is created. Exception isolation does not bound latency; the notifier creates a default aiohttp session.

**Live impact:** A slow webhook can leave the carrier on hold while no broker dial has started.

**Suggested fix:** Give notification a short explicit timeout or detach it from the telephony critical path.

### 12. Connect hold audio before suppressing the primary bot

**Anchor:** `voice-agent/orchestrator.py:197-199`

**Problem — VERIFIED BY TRACE:** Primary media is gated before `start_hold()` has connected its publisher. **vipul-sharma20** previously raised this ordering issue. The code guarantees a non-atomic interval, although its real duration was not measured.

**Live impact:** The carrier hears silence between Room1 suppression and the first hold frame; under slow connection this can approach the configured hold-connect timeout.

**Evidence:** `gate_primary_media(True)` completes before `start_hold()` begins, while `voice-agent/livekit_transfer_media.py:71-109` creates the transport/task and waits for connection afterward. No first-frame readiness signal or timing telemetry closes the gap.

**Suggested fix:** Prepare and confirm the hold publisher and first playable frame before gating primary output, then switch atomically where possible. Record gate-to-first-frame latency and failure telemetry.

### 13. Clean up the inbound room when bot startup fails

**Anchor:** `voice-agent/server.py:126-145`

**Problem — VERIFIED BY TRACE:** A joined inbound SIP participant already has a LiveKit room when the webhook calls the bot starter. If startup fails, the route propagates the exception without deleting the room or removing the participant. **kzhdanov** previously raised this missing cleanup. The outbound route has explicit room deletion at `voice-agent/server.py:181-183`; inbound does not.

**Live impact:** On a runner/startup failure, the inbound carrier can remain connected to an unattended room until provider-side cleanup occurs.

**Suggested fix:** Wrap inbound startup in a terminal cleanup path that removes the SIP participant/deletes the room, while preserving an idempotent retry decision for the webhook event.

# Prior review comments

- **Kishorerh1993 — REFUTED and requalified:** Pipecat 0.0.95 does provide `pause_processing_frames()` and `resume_processing_frames()`, so the claimed every-transfer `AttributeError` is not present. The reviewer identified the correct boundary: executable testing shows that the API does not gate SystemFrame audio, which becomes Comment 3.
- **Kishorerh1993 — CONFIRMED:** caller-ID/tenant divergence (Comment 8), non-atomic process-local webhook dedupe (Comment 6), and blocking outbound answer behavior (Comment 7).
- **Kishorerh1993 — PARTIALLY RIGHT:** one global runner definitely returns 409 for overlap, but production severity depends on the unresolved one-runner-per-call deployment assumption. Credential-shaped CI fixtures do not themselves establish a defect.
- **vipul-sharma20 — CONFIRMED:** primary media is gated before hold readiness, creating an unmeasured silence interval (Comment 12).
- **vipul-sharma20 — QUESTION:** the PR retains Room2 SID for Room1 disconnect filtering; inspected primary LiveKit protocol/SDK material does not guarantee whether MoveParticipant preserves SID.
- **vipul-sharma20 — REFUTED:** local import placement alone does not show a runtime or design failure.
- **kzhdanov — CONFIRMED:** integer SIP-kind rejection (Comment 1), SID/identity readiness mismatch (Comment 2), ineffective audio isolation (Comment 3), unfenced terminal races (Comment 4), and missing inbound-start cleanup (Comment 13).
- **tieincred — CONFIRMED:** SID/identity mismatch (Comment 2), webhook race (Comment 6), late transfer continuation (Comment 4), tenant/caller-ID mismatch (Comment 8), and unbounded notification latency (Comment 11).
- **tieincred — PARTIALLY RIGHT:** the named blocker summaries are confirmed; an unspecified reference to “two further blockers” cannot be adjudicated beyond the linked inline comments.

The exhaustive handle/comment matrix and raw source checks are in `review_tests/prior_review_verdicts.md`.

# Verified defects

- `voice-agent/room2_pipeline_service.py:246-268`: real broker identity cannot be resolved from SID; Room2 readiness times out.
- `voice-agent/livekit_transfer_media.py:57-69`: caller audio reaches Room1 STT/LLM while “gated.”
- `voice-agent/call_helpers.py:655-762,765-849`: agreement and termination handlers are permitted in `TRANSFER_HOLD`.
- `voice-agent/orchestrator.py:197-229`: carrier departure during hold startup does not fence the transfer owner; broker dialing and a leaked Room2 pipeline follow cleanup.
- `voice-agent/livekit_ingress.py:195-205`: installed integer SIP kind is rejected through a nonexistent import path.
- `voice-agent/orchestrator.py:286-301,471-513`: ambiguous movement retains an observer and leaves Room1 without bounded cleanup.
- `voice-agent/server.py:123-141`: dedupe state is process-local/unbounded and its check/add is separated by awaits.
- `voice-agent/server.py:162-183`: outbound API response waits for provider answer.
- `voice-agent/server.py:157-176`: tenant attribution and actual caller ID can diverge.

# Plausible risks

- The active Room1 LLM may interpret carrier–broker speech as instructions and invoke the verified unguarded tools; handler ability is proven, actual model selection is not.
- Voicemail can satisfy provider answer/audio gates and receive load/pricing briefing; voicemail classification is explicitly out of scope and was not simulated end-to-end.
- A retained observer/room may continue provider billing after ambiguous movement; resource retention is verified, billing behavior is external.
- A changed SID after MoveParticipant could prevent disconnect cleanup; the code path is verified, SID preservation semantics remain unknown.
- The single global runner can reject overlapping calls; occurrence depends on the deployment's process-per-call invariant.
- Immediate cleanup retries and notification latency may amplify provider incidents; these were traced but not separately reproduced.

# Open questions for the author

1. What is the voicemail/answering-machine plan for the broker leg before confidential load and pricing context is spoken?
2. Is production guaranteed to run one isolated process per call? If so, where is that lifecycle, routing, and teardown contract enforced and tested?
3. What is the rollout and rollback plan now that Daily is removed outright? Can traffic be switched back without a code redeploy?
4. Does the deployed LiveKit server preserve participant SID across MoveParticipant? Please provide an authoritative version-specific guarantee or reconcile the destination participant by identity and refresh its SID.
5. Where is webhook replay/deduplication enforced across replicas and restarts?
6. What owner reconciles cleanup-pending rooms/participants after the in-process runner exits?

# Assumptions and verification scope

## Assumptions

- Review target is detached head `f93f7a5f79efdf08c18c583a6a6f7167084b93ae` against base `5a98a66274322954a0a6255f54650eec6e50c41d`.
- Installed test environment matches the PR pin/resolution: Pipecat 0.0.95, LiveKit API 1.0.7, LiveKit RTC 1.0.25, and livekit-protocol 1.1.27.
- The Git checkout lives at `/tmp/frontline-review` because the assessment workspace cannot save the full clone and its files over 200 KB; `review_tests/` imports the pinned checkout explicitly by that path.
- The configured default transfer deadlines are used unless deployment overrides them.
- No upstream component silently supplies dedupe, per-call process isolation, voicemail classification, or cleanup reconciliation unless the author documents it.

## Checked

- Existing voice-agent suite: 127 passed, including the stated 17 looped subtests.
- Existing shared suite: 91 passed.
- Installed Pipecat/LiveKit classes and relevant implementations, not only mocks.
- Executable regressions for audio gating, post-handoff handlers, identity-keyed Room2 events, carrier departure during hold startup, and ambiguous movement.
- Base and head call lifecycle, cleanup, persistence, configuration, migration, dashboard attribution, and all prior review comments.
- Webhook verification/parsing source and existing unit coverage.

## Not checked

- No real LiveKit/Telnyx calls, voicemail, early-media provider behavior, MoveParticipant server behavior, or end-to-end warm transfer.
- No real speech-provider calls or nondeterministic LLM tool-selection experiment.
- No Supabase migration execution or production-schema validation; migration SQL was inspected only.
- No browser/dashboard runtime; dashboard data flow was inspected, but TypeScript/browser checks were not rerun in this session.
- No multi-process/multi-replica deployment test, restart recovery, provider billing validation, load test, or chaos test.
- Webhook cryptographic verification was exercised through existing unit tests, not a captured real LiveKit delivery.
