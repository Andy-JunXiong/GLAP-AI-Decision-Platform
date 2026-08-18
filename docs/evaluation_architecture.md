# GLAP Evaluation Architecture

**Contract version:** `evaluation-experiment.v1`
**Business timezone:** `Australia/Sydney`
**Current implementation:** local, deterministic, read-only A303 ablation only

## Purpose

GLAP must be able to show which capability changed a decision, whether the
changed decision was better, and whether it ultimately improved a business
outcome. The Evaluation Harness is therefore a cross-cutting evidence boundary,
not a stage in the operational decision flow and not an integration with one
agent framework.

```mermaid
flowchart LR
    REALITY[Reality or governed replay] --> DATA[Operational data]
    DATA --> DETECT[Detect]
    DETECT --> INVESTIGATE[External investigation]
    INVESTIGATE --> EVIDENCE[Evidence]
    EVIDENCE --> MEMORY[Decision memory]
    MEMORY --> DECIDE[Reason and recommend]
    DECIDE --> GOV[Authority gate]
    GOV --> ACTION[Action]
    ACTION --> OUTCOME[Outcome]
    OUTCOME --> LEARN[Learning]

    HARNESS[Evaluation Harness] -. freezes inputs and varies capabilities .-> DATA
    HARNESS -. compares decisions and evidence .-> DECIDE
    HARNESS -. never bypasses authority .-> GOV
    HARNESS -. classifies outcome evidence .-> OUTCOME
```

The operational trust boundaries in
[`architecture_current.md`](architecture_current.md), the immutable Action and
Outcome rules in [`governed_closed_loop.md`](governed_closed_loop.md), and the
calendar rules in [`temporal_truthfulness.md`](temporal_truthfulness.md) remain
authoritative.

## Four evaluation layers

| Layer | Question | Initial evidence |
| --- | --- | --- |
| System Correctness | Did the system follow its contract? | Pass/fail contract checks, deterministic rerun, mutation isolation |
| Capability Attribution | Did the selected capability change the decision? | Paired ablation with all non-target inputs fixed |
| Decision Quality | Was one decision more reasonable using only then-available information? | Policy compliance, evidence coverage, risk detection, estimate error, latency, blinded expert agreement |
| Business Outcome Effect | Did the decision improve cost, delay, stock availability, or service? | Explicitly classified factual or counterfactual outcome evidence |

A decision difference is not a quality result. A quality result is not a
measured business effect. Reports must keep the four claims separate. The
preferred name for layer two is **Capability Attribution**, because “decision
effect” can be mistaken for a causal outcome claim.

## Experiment boundary

Every experiment is a paired comparison described by
[`evaluation_experiment_v1.schema.json`](evaluation_experiment_v1.schema.json).
The baseline and challenger receive the same scenario, cutoff, evidence
snapshot, operational state, authority profile, random seed, and policy/tool
versions. Only declared capability flags may differ.

The local harness must:

- make no AWS or network call;
- write no operational Decision, Action, audit, Outcome, or Learning row;
- never approve, reject, complete, or execute an Action;
- produce deterministic output for an identical manifest;
- retain the decision and rule trace for each variant;
- report unsupported evaluation layers as `NOT_EVALUATED`, never as zero or
  failure;
- make the exact changed capability explicit in the comparison result.

An evaluation report is repository engineering evidence. It is not an
operational decision, approval, shipment instruction, production result, or
authority grant.

## Point-in-time evidence

A scenario cutoff freezes what GLAP could have known, rather than merely when
an event occurred. Evidence records distinguish:

- `event_time`: when the represented event occurred;
- `published_at`: when the source published it;
- `available_at`: when GLAP could first have obtained it;
- `ingested_at`: when the evidence snapshot captured it;
- `revision_version`: which published revision is represented.

Only evidence with `available_at <= cutoff_at` is visible to a variant. Later
evidence may be retained in the scenario corpus to test the no-leakage gate,
but it cannot enter a decision. Historical source revisions must not be
silently replaced by their latest form.

The v0.1 A303 fixture is `CONTROLLED_SYNTHETIC_REPLAY` and
`SYNTHETIC_ENGINEERING_ONLY`. It validates evaluation mechanics only. It is not
a historical public-event corpus and does not establish real decision quality
or logistics performance.

## Evidence classes

Scenario inputs and outcome claims are classified independently.

Input scenarios:

- `CONTROLLED_SYNTHETIC_REPLAY`: all decision inputs are controlled fixtures;
- `HYBRID_HISTORICAL_REPLAY`: point-in-time historical external evidence plus
  controlled synthetic enterprise state;
- `OPERATIONAL_ACTUAL_CALENDAR`: governed operational inputs on or before the
  current Sydney date;
- `FUTURE_SIMULATION`: staging-only future scenario under the temporal
  truthfulness contract.

Outcome evidence:

- `NOT_EVALUATED`;
- `OBSERVED_FACTUAL`;
- `SIMULATED_COUNTERFACTUAL`;
- `MATCHED_OBSERVATIONAL`;
- `PROSPECTIVE_CONTROLLED`;
- `PRODUCTION_MEASURED`.

Advancing a historical replay reveals the factual historical outcome. It does
not reveal what would have happened under an unchosen GLAP action. Any such
estimate must identify its counterfactual method and cannot be relabelled as a
measured effect.

## Agent Runtime Interface

Agent hosts are replaceable adapters. A future host may use governed,
point-in-time tools such as:

```text
get_shipment(as_of)
get_evidence(as_of)
get_carrier_performance(as_of)
get_similar_decisions(as_of)
propose_action()
request_approval()
submit_outcome_evidence()
```

The interface fixes the evidence, tools, authority, redaction, and budget so
agent comparisons remain paired. `request_approval()` is simulated inside an
evaluation sandbox. An agent may submit outcome evidence, but it may not define
or validate the result of its own recommendation; an independent evaluator or
authorised human owns Outcome acceptance.

## v0.1 A303 experiment

The first fixture compares:

```text
baseline-a303-off: A303_HIGH_RISK_ROUTE = false -> MONITOR
glap-a303-on:      A303_HIGH_RISK_ROUTE = true  -> RISK_MITIGATION
```

The repository does not contain the deployed A303 implementation. The v0.1
runner therefore evaluates the versioned `A303.v1` rule contract represented
by the fixture; it does not claim runtime verification of the inspected AWS
rule path. Current governed staging code for `SLA_BREACH` and `COST_ANOMALY`
remains unchanged.

The experiment evaluates only System Correctness and Capability Attribution.
The Decision Quality rubric, v3 option-content contract, blinded package,
independent-review contract, and aggregation gate are implemented. The
ten-event corpus, rubric, and option contract are content-addressed, and
deterministic blinded packages cover all 30 cutoffs. V1 and v2 collection is
paused and preserved draft progress is ineligible. The corrected story-based,
progressive A/B/Tie workflow is publicly released as Sites v11. It applies the
full 30-package v3 bundle with attestations, server save/resume, per-story
ordering, immutable submission, and isolated reviewer scopes. Six hosted
accounts exist and two eligible story-v2 submissions are complete, each with
30 committed choices and all required attestations. The declared minimum is
three valid independent reviews, so collection remains open and Decision
Quality remains `NOT_EVALUATED`. Business Outcome Effect also remains
`NOT_EVALUATED` until an eligible outcome method is attached. See
[`decision_quality_evaluation.md`](decision_quality_evaluation.md).

Run it locally with:

```bash
python ops/evaluate_decision_capabilities.py \
  tests/fixtures/evaluation/a303_high_risk_route_v1.json
```

## Next increments

1. Collect no fewer than three genuinely independent blinded reviews per
   variant from the publicly released v3 frozen handoff; the
   10-scenario, 30-cutoff inputs remain unchanged; do not manufacture
   repository labels or count preserved v1/v2 progress.
2. Aggregate only integrity-valid submissions after the study owner confirms
   reviewer independence and blind-key separation. Structural coverage and a
   frozen handoff alone do not create an eligible benchmark.
3. Add External Evidence and Decision Memory ablations.
4. Add a governed Agent Runtime adapter and compare hosts using identical
   tools, evidence, budgets, and authority.
5. Introduce counterfactual outcome methods with explicit evidence classes.
6. Use prospective controlled or measured production evidence only after
   separate human approval and production-readiness gates.
