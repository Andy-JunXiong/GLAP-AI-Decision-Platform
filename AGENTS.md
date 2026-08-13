# Repository Agent Guidance

Compact execution context. Routes you to authoritative knowledge; does not
duplicate it. Read this first, then follow the router for your task.

## Purpose

GLAP is an AWS-deployed logistics decision-intelligence platform. It detects
abnormal shipment or port conditions, explains business exposure, recommends
bounded actions, and keeps human approval, execution evidence, and outcomes
traceable through a governed closed loop. All logistics data is synthetic;
AWS runtime, deployment, and reliability evidence is based on inspected
deployed resources.

## Current System Map

```text
Shipment/port signals
  → Athena anomaly detection + Iceberg tables
  → Business exposure (fees + inventory risk)
  → Decision engine (deterministic rules)
  → Human review (APPROVE / REJECT / edit)
  → Governed Action (immutable proposal, append-only audit)
  → Delayed simulated Outcome (context-dependent, reproducible)
  → Learning evidence → PENDING_HUMAN_REVIEW policy proposal
```

Two parallel tracks:
- **Production:** daily success-gated pipeline → aggregate-only OPS snapshot
  to public GitHub Pages. Immutable Lambda versions, `staging`/`prod` aliases,
  GitHub OIDC delivery.
- **Staging:** isolated stateful lifecycle (Maersk/KN Ocean + DHL Air) with
  cross-date shipment identity, authenticated Operations API, and private
  cockpit. No production alias, schedule, or production-table write.

## Primary Sources of Truth

Domain-specific documents are reached through the Task → Context Router below.
These five are repository-wide canonical sources:

| Concern | Document |
|---|---|
| Current architecture & trust boundaries | `docs/architecture_current.md` |
| Infrastructure boundary & runtime flow | `INFRASTRUCTURE.md` |
| Current implementation priorities | `TODO.md` |
| Implementation roadmap & delivery sequence | `docs/implementation_roadmap.md` |
| Temporal truthfulness & evidence boundary | `docs/temporal_truthfulness.md` |

**Reference-implementation history (must not override current architecture):**
- `docs/GLAP_Technical_Implementation.md` — original full-stack engineering;
  uses legacy v1 anomaly/root-cause/decision tables. Its architecture
  descriptions must not override `docs/architecture_current.md`.
- `docs/GLAP_Day1_to_Day20_README.md` — 20-day incremental engineering
  journey; describes earlier architecture phases.
- `docs/decision_flywheel_evidence.md` — self-labelled placeholder using v1
  tables; current closed loop: `docs/governed_closed_loop.md`.
- `docs/development_handoff_2026-08-05.md` and `2026-08-06.md` — superseded
  by the 7 August 2026 handoff.

## Task → Context Router

Before making changes, read only what your task requires. Do not scan the
whole repository.

**If changing shipment lifecycle / generators / stateful data:**
→ `docs/shipment_lifecycle_design.md`, `docs/architecture_current.md` (isolated staging boundary section), `TODO.md`

**If changing Operations API / authenticated actor surfaces / RBAC:**
→ `docs/operations_api_v1.md`, `docs/governed_closed_loop.md`, `docs/architecture_current.md` (authenticated operations boundary section)

**If changing Decision / Action / Outcome / Learning / governed closed loop:**
→ `docs/governed_closed_loop.md`, `docs/operations_api_v1.md` (mutation endpoints), `TODO.md`

**If changing forecasting / model evidence / backtests / label readiness:**
→ `docs/multimodal_forecast_feature_contract.md`, `docs/temporal_truthfulness.md`, `TODO.md` (P3 section)

**If changing AWS infrastructure / CloudFormation / deployment / IAM:**
→ `INFRASTRUCTURE.md`, `docs/deployment_workflow.md`, `docs/architecture_current.md`

**If changing pipeline reliability / quality gates / scheduling:**
→ `docs/pipeline_reliability.md`, `docs/architecture_current.md` (reliability boundary section), `docs/ops_snapshot.md` (pipeline status section)

**If changing public OPS analytics / snapshot contract / Control Tower:**
→ `docs/ops_snapshot.md`, `docs/architecture_current.md` (key controls section)

**If changing data contracts / Iceberg schemas / SQL views:**
→ `docs/ops_snapshot.md` (published contract), `docs/multimodal_forecast_feature_contract.md` (feature views), `docs/shipment_lifecycle_design.md` (lifecycle tables), `sql/` directory for existing DDL

**If changing frontend / operator cockpit / public Pages:**
→ `docs/operations_api_v1.md`, `docs/ops_snapshot.md` (public boundary), `docs/development_handoff_2026-08-07.md` (cockpit status)

**If changing governance / evidence boundaries / temporal rules:**
→ `docs/temporal_truthfulness.md`, `docs/ops_snapshot.md` (evidence classes), `docs/governed_closed_loop.md` (calendar gate)

## Non-Negotiable System Invariants

These rules must survive every change. Derived from deployed system evidence,
not invented. For the full temporal boundary, see Temporal Truthfulness below.

1. **Evidence boundaries.** All logistics data (shipments, disruptions,
   financials) is synthetic. Only AWS runtime, version, CI/CD, and reliability
   claims are operational evidence. Public Pages is aggregate-only and
   read-only — no entity identifiers, ARNs, S3 paths, or write paths. Public
   analytics use only the governed v3/v2 flywheel tables; legacy v1 tables are
   historical evidence only.

2. **Staging ≠ production.** The staging stack has no Scheduler, no production
   alias, and no write access to production tables. The GitHub deployment role
   cannot update `prod`. Production aliases, schedules, and automatic policy
   activation require separate explicit human approval.

3. **Human-governed mutations.** Only a named human (from signed identity
   claims, never client-supplied) may approve, reject, or complete an Action.
   Every mutation creates an immutable, idempotent audit event. Proposed Action
   rows are immutable; only audit events change state.

4. **Deterministic before learned.** Current decision generation is
   deterministic and explainable. Autonomous learning and measured production
   impact are future capabilities. No model may replace deterministic safety
   rules. Supervised training is blocked until every provider meets the
   governed label thresholds using only `OPERATIONAL` / `ACTUAL_CALENDAR`
   closed outcomes.

## Development / Authority Boundaries

**Agent (you) may:**
- Inspect, search, and reason about any file in the repository
- Implement changes within the scope the user explicitly approved
- Run local tests, linting, and compilation checks
- Propose architecture, design, or implementation approaches

**Agent (you) may not, even if tests pass:**
- Deploy to AWS (any environment)
- Move or promote Lambda aliases (`staging` or `prod`)
- Modify CloudFormation stacks, IAM, Scheduler, or SQS configuration
- Change production data, Iceberg tables, or governed views
- Publish to public GitHub Pages or modify the OPS snapshot contract
- Approve, reject, or complete an operational Action
- Activate a policy proposal, promote a model, or enable a recurring schedule
- Grant or revoke AWS permissions
- Make semantic business decisions (e.g. "this model is ready for production")

These boundaries exist regardless of whether CI passes, tests are green, or
code compiles. Production authority is always human-owned.

## Commit and Push Method (AI Radar Pattern)

Commit and push are separate, human-authorized local Git actions. When the
user explicitly says `commit`, `push`, or `commit and push`, use the existing
repository Git authentication path (normally Windows Git Credential Manager)
and ordinary `git` commands. `gh auth status` and `gh auth login` are not
prerequisites for committing or pushing, and the agent must not ask the user
for GitHub credentials or tokens.

Before committing:

1. inspect `git status -sb` and the diff;
2. run the Documentation and Fact Synchronization Gate below;
3. confirm that all staged paths belong to the approved task;
4. run the applicable validation and drift gates;
5. stage only the approved paths and create a terse, scoped commit.

### Documentation and Fact Synchronization Gate

Every explicit `commit`, `push`, or `commit and push` request automatically
triggers a documentation-impact audit. Passing tests is not sufficient when
the repository's written or machine-readable state is stale.

Before committing:

1. Compare the approved diff and any external runtime evidence produced since
   the previous commit with the Task -> Context Router and repository sources
   of truth.
2. Treat these as documentation-impacting by default: API/schema/RBAC or user-
   journey changes; deployment, rollback, incident, security, or runtime
   findings; changed implementation status, blocker, authority, or next step;
   new workflow/run IDs or verification totals; and any temporal/evidence-
   classification change.
3. Update all affected human-readable sources and their machine-readable
   contracts in the same commit as the implementation when practical. Keep
   `TODO.md`, the current dated handoff, rollout/runbook/API documentation,
   architecture/roadmap statements, drift contracts, validators, and tests
   mutually consistent where they are affected. Do not touch unrelated docs.
4. Record facts at their exact maturity: implemented, committed, pushed,
   deployed, runtime-verified, or human-approved are distinct states. Preserve
   staging versus production, synthetic versus operational evidence, Sydney
   dates, remaining blockers, and explicit authority boundaries.
5. Never place credentials, tokens, raw identity claims, personal contact
   details, private origins, entity identifiers, ARNs, S3 paths, or other
   protected values into documentation or commit messages. Use bounded counts,
   safe timestamps, statuses, and commit/workflow identifiers only.
6. If the change has no documentation impact, state that conclusion in the
   commit handoff. A code-only commit is allowed only when the audit finds no
   affected claim, or when the user explicitly authorizes an urgent exception;
   an urgent exception must record the temporary divergence and blocks release
   or deployment until documentation is reconciled.

Before pushing:

1. Re-run the documentation-impact audit across every unpushed commit using
   `origin/<branch>..HEAD`, not only the latest commit.
2. Reconcile external events that happened after the commits, including manual
   AWS actions, runtime canaries, failures, recovery, identity cleanup, and
   newly discovered blockers. If any tracked claim is stale, stop the push and
   create a documentation-sync commit first.
3. Inspect the pushed paths against `.github/workflows/` triggers and state
   whether the push starts CI, staging deployment, production work, or Pages.
   Obtain separate authority for any external write; otherwise use a non-
   deploying branch as required below.
4. After push, report the exact remote commit, documentation-sync result,
   triggered workflows, and what remains uncommitted, undeployed, unverified,
   or human-owned.

For push, use `git push` to the current repository only. Do not create a pull
request unless the user asks for one. If pushing the current branch would
trigger a deployment or public Pages publication that the user did not
authorize, create and push a non-deploying feature branch instead. Push never
grants AWS deployment, production mutation, Pages publication, alias movement,
schedule activation, or policy/model promotion authority.

If `git push` itself fails authentication, report that concrete failure and
stop. Do not switch to GitHub CLI authentication, request secrets, or treat an
unrelated `gh` session as the repository's Git credential source.

## Validation

Route your change to the right validation. All commands verified from CI/CD
workflows in `.github/workflows/`.

**Python / Lambda / orchestration change:**
```bash
python -m compileall -q lambda ops examples tests
python -m unittest discover -s tests -v
```

**Frontend / cockpit change (inside `decision-brief-demo/`):**
```bash
npm run lint
npm test
```

**SQL / CloudFormation / deployment contract change:**
- Verify SQL files exist and are non-empty
- Verify CloudFormation templates: `infrastructure/pipeline-reliability.yaml`,
  `infrastructure/stateful-lifecycle-staging.yaml`
- Run `python -m compileall -q lambda ops examples tests`

CI runs `python -m unittest discover -s tests -v` on Python 3.13 and 3.14 on
every PR and push to `main`.

## Completion Communication

After completing any meaningful development deliverable, explain it to the user
in plain, non-technical language. Do not finish with only a list of changed
files, implementation details, tests, or workflow results.

For each completed deliverable, the final handoff must answer all four questions:

1. **What is it?** Describe what was built or changed and what a user or operator
   can now do. Start with everyday language; add technical terms only when they
   improve clarity.
2. **What previous capability does it connect to?** Name the upstream feature,
   data, workflow, or decision that supplies its inputs or made this work
   possible. Explain the connection, not just the component name.
3. **What next capability does it connect to?** Name the downstream consumer or
   the next logical product capability this work enables. If nothing is
   connected yet, state that boundary and what must happen before it can be
   connected.
4. **How does it help the overall project?** Explain the concrete project-level
   benefit, such as improving the operator journey, data continuity,
   reliability, auditability, delivery speed, decision quality, cost control, or
   risk reduction.

Use the user's language and this compact structure unless the user asks for
another format:

```text
Completed: <plain-language explanation of what it is>
Upstream connection: <the previous capability and how this uses it>
Downstream connection: <the next capability or the explicit boundary>
Project value: <the concrete benefit to the overall project>
Verification: <tests, quality gates, deployment, or runtime evidence>
```

When several deliverables are completed together, give each meaningful
deliverable its own four-part explanation or use a table with the same four
relationships. Clearly distinguish what is already implemented and verified
from what is only enabled, recommended, or planned next.

## Temporal Truthfulness

Treat the current Australia/Sydney business date as the boundary between
operational evidence and scenarios. Before creating, querying, validating, or
describing date-based data:

1. Compare every logical or cutoff date with the current Sydney date.
2. A date on or before today may be handled as `OPERATIONAL` with
   `time_basis=ACTUAL_CALENDAR`. A later date must never be called current,
   historical, observed, actual, or real-world evidence.
3. Future-dated work is permitted only as an explicitly requested,
   staging-only `FUTURE_SIMULATION` with a scenario ID, system-derived
   `as_of_date`, isolated status/artifacts, and no production effect.
4. Operational OPS exports, default backtests, readiness decisions, and model
   promotion evidence must exclude future simulations. Scenario backtests may
   validate code and workflow behavior, but they do not establish real model
   performance, label maturity, or production readiness.
5. When reporting historical future-dated runs, preserve the execution record
   but clearly relabel it as synthetic scenario evidence relative to the date
   on which it ran.
