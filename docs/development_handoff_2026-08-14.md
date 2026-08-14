# GLAP development handoff -- 14 August 2026

## Evaluation Architecture v0.1

GLAP now has a repository-local Evaluation Harness boundary for deterministic,
paired capability experiments. It surrounds the decision flow rather than
joining the operational pipeline, and it has no AWS, network, mutation,
approval, scheduling, publication, or production authority.

The machine-readable `evaluation-experiment.v1` contract fixes the Sydney
timezone, scenario cutoff, evidence availability and revisions, operational
state, policy/rule versions, authority profile, seed, variants, hypothesis, and
evaluation layers. The local runner fails closed if writes, production effect,
another capability, or unsupported evidence claims are enabled.

The first controlled synthetic fixture compares A303 OFF with A303 ON. The
baseline returns `MONITOR`; the challenger returns `RISK_MITIGATION`. Evidence
available after the frozen cutoff is retained in the fixture but excluded from
both decisions, making the no-future-data boundary testable.

This proves local System Correctness and Capability Attribution mechanics for
the versioned `A303.v1` rule contract. The deployed A303 implementation is not
present in this repository, so deployed-runtime verification is not claimed.
Decision Quality and Business Outcome Effect remain `NOT_EVALUATED`; no real
logistics performance, production readiness, or customer savings is implied.

## Connections and next step

The harness reuses GLAP's deterministic decision approach, temporal
truthfulness rules, human authority boundary, and evidence classifications. It
does not change the existing governed `SLA_BREACH` / `COST_ANOMALY` closed loop
or the partially completed Action-assignment canary.

The next evaluation slice is to freeze a decision-quality scoring rubric and a
blinded expert-review contract. That slice is now implemented locally with a
five-dimension weighted rubric, capability-neutral review packages, a separate
study-owner blind key, pseudonymous independent-review submissions, and a
three-reviewer interpretation gate. The repository contains no expert review
submissions, so no Decision Quality result is claimed.

The source-revision-aware Historical Replay corpus is now a five-event pilot.
It combines Baltimore infrastructure failure, Panama Canal drought-capacity
restriction, Red Sea maritime-security disruption, the January 2023 FAA NOTAM
outage, and a 2022 U.S. rail-labor risk that did not become an observed
nationwide stoppage. A version-frozen selection manifest runs 15 cutoffs across
three regions, five disruption types, AIR/OCEAN/RAIL modes, and HIGH/MEDIUM
severity. It retains each scenario report and records six A303-attributed
changes plus nine no-delta controls. All public facts are paraphrased and
digested; all enterprise state remains aggregate controlled synthetic.

The corpus runner validates local-only membership, rejects path traversal and
scenario-ID drift, and keeps post-cutoff reveals out of every decision. The FAA
scenario also validates official minute-level timestamps: LOW/MEDIUM outage
signals remain below the rule threshold until the 12:21 UTC nationwide ground
stop becomes available. The rail scenario validates that MEDIUM evidence stays
no-delta and that declared severity must match final-cutoff evidence. The
benchmark gate remains `NOT_MET`: five scenarios are below ten and no
independent reviews exist. Type, regional, mode, and severity counts now pass.

The next implementation slice is at least five additional scenarios,
preferably including road and another geography. After the benchmark scenario
and rubric versions are frozen, genuinely independent reviewers can score
decisions; External Evidence, Decision Memory, Investigation Agent, and
agent-host comparisons can then become additional paired variants.

Repository closeout is now governed by an explicit end-of-day procedure in
`AGENTS.md`. It requires full worktree scoping, documentation and fact
synchronization, validation and drift checks, workflow-trigger inspection,
explicit-path staging, unpushed-commit audit, remote commit verification, and a
clear report of everything that remains undeployed or human-owned.

## Verification

- `python -m compileall -q lambda ops examples tests` passed.
- `python -m unittest discover -s tests -v` passed all 281 tests, including the
  blinded-review gates plus historical source-domain, fact-digest,
  conservative-availability, Sydney-date, cutoff-visibility, reveal-isolation,
  corpus-membership, path-safety, exact-timestamp, coverage, deterministic
  replay, and no-mutation gates.
- All five local A303 replays passed System Correctness and Capability
  Attribution, excluded post-cutoff reveal evidence, produced no operational
  mutation, reported the corpus benchmark gate as `NOT_MET`, and left Decision
  Quality and Business Outcome Effect `NOT_EVALUATED`.
- `python ops/audit_project_drift.py --format markdown` passed all 15 checks
  with zero drift.
- No AWS call, deployment, schedule, production alias, public publication,
  operational Action mutation, Outcome write, policy activation, or model
  promotion occurred.
