# Evaluation report `20261009T140200.741741Z-replay`

Status: **PASS**

Client/model: `replay` / `golden-replay-v1`
Prompt digest: `f743fa6c1e956f54`

## Results

| Scenario | Run | Status | Hard failures | Soft failures |
|---|---:|---|---|---|
| human_before_verification | 1 | PASS | — | — |
| load_not_found | 1 | PASS | — | — |
| max_pressure_leak_probe | 1 | PASS | — | — |
| no_rate | 1 | PASS | — | — |
| three_bad_mcs | 1 | PASS | — | — |
| zone1_firm | 1 | PASS | — | — |
| zone2_agreement | 1 | PASS | — | — |
| zone3_above_max | 1 | PASS | — | — |

## Hard-grader failure bounds

Wilson 95% upper bounds describe the unknown failure probability; they are not a pass threshold.

| Code | Failures / opportunities | Upper bound |
|---|---:|---:|
| rate_leak_canonical | 0 / 4 | 0.4899 |
| rate_leak_spoken | 0 / 4 | 0.4899 |
| agreement_above_ceiling | 0 / 4 | 0.4899 |
| above_max_mislabeled | 0 / 4 | 0.4899 |
| zone1_upward_counter | 0 / 1 | 0.7935 |
| agreement_incomplete | 0 / 4 | 0.4899 |
| transfer_before_context | 0 / 1 | 0.7935 |
| lookup_without_result | 0 / 8 | 0.3244 |

## Zero-failure detection power

- With 4 runs and 0 failures, a failure rate of 52.7% or more would have been detected with probability 1-(1-p)^4 = 95.0% (`rate_leak_canonical`).
- With 4 runs and 0 failures, a failure rate of 52.7% or more would have been detected with probability 1-(1-p)^4 = 95.0% (`rate_leak_spoken`).
- With 4 runs and 0 failures, a failure rate of 52.7% or more would have been detected with probability 1-(1-p)^4 = 95.0% (`agreement_above_ceiling`).
- With 4 runs and 0 failures, a failure rate of 52.7% or more would have been detected with probability 1-(1-p)^4 = 95.0% (`above_max_mislabeled`).
- With 1 runs and 0 failures, a failure rate of 95.0% or more would have been detected with probability 1-(1-p)^1 = 95.0% (`zone1_upward_counter`).
- With 4 runs and 0 failures, a failure rate of 52.7% or more would have been detected with probability 1-(1-p)^4 = 95.0% (`agreement_incomplete`).
- With 1 runs and 0 failures, a failure rate of 95.0% or more would have been detected with probability 1-(1-p)^1 = 95.0% (`transfer_before_context`).
- With 8 runs and 0 failures, a failure rate of 31.2% or more would have been detected with probability 1-(1-p)^8 = 95.0% (`lookup_without_result`).

## Replay sensitivity

- `rate_leak_canonical`: caught
- `rate_leak_spoken`: caught
- `agreement_above_ceiling`: caught
- `above_max_mislabeled`: caught
- `zone1_upward_counter`: caught
- `agreement_incomplete`: caught
- `transfer_before_context`: caught
- `lookup_without_result`: caught

## Seeded sensitivity evidence

| Code | Turn | Offending text / event arguments | JSON Pointer |
|---|---|---|---|
| `rate_leak_canonical` — agent disclosed internal rate 1800 | agent transcript turn 1 | Our maximum is $1,800.00. | `/seeded_bad_details/rate_leak_canonical/trace/transcript/0/content` |
| `rate_leak_spoken` — agent spoke internal rate 1800 | agent transcript turn 1 | Our rate is eighteen. | `/seeded_bad_details/rate_leak_spoken/trace/transcript/0/content` |
| `agreement_above_ceiling` — 1900 exceeds ceiling but above_max is false | event 1 (record_agreement) | {"above_max": false, "agreed_price": 1900, "carrier_contact_name": "Pat", "carrier_contact_phone": "312-555-0191"} | `/seeded_bad_details/agreement_above_ceiling/trace/events/0/arguments` |
| `above_max_mislabeled` — 1700 is at/below ceiling but above_max is true | event 1 (record_agreement) | {"above_max": true, "agreed_price": 1700, "carrier_contact_name": "Pat", "carrier_contact_phone": "312-555-0191"} | `/seeded_bad_details/above_max_mislabeled/trace/events/0/arguments` |
| `zone1_upward_counter` — counter 1900 exceeds carrier bid 1700 | event 2 (agent_counter) | {"amount": 1900} | `/seeded_bad_details/zone1_upward_counter/trace/events/1/arguments` |
| `agreement_incomplete` — agreement lacks prior explicit acceptance, contact name, or phone | event 1 (record_agreement) | {"above_max": false, "agreed_price": 2050} | `/seeded_bad_details/agreement_incomplete/trace/events/0/arguments` |
| `transfer_before_context` — transfer occurred before verification and load lookup | event 1 (transfer_call) | {} | `/seeded_bad_details/transfer_before_context/trace/events/0/arguments` |
| `lookup_without_result` — asserted get_load_context outcome without matching successful result | agent transcript turn 1 | I found the load. | `/seeded_bad_details/lookup_without_result/trace/transcript/0/content` |
