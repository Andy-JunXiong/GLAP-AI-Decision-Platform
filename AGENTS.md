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
