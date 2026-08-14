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
| Long-term direction & capability gates | `DEVELOPMENT_PLAN.md` |
| Current reality, Active Slice & Next Up | `CURRENT_DEVELOPMENT_STATUS.md` |
| Temporal truthfulness & evidence boundary | `docs/temporal_truthfulness.md` |

## Documentation Operating Model

Keep direction, current truth, history, and rules separate:

| Layer | Source | Answers | Update trigger |
|---|---|---|---|
| Rules | `AGENTS.md` | Authority, invariants, workflow, validation, communication | A governing rule changes |
| Direction | `DEVELOPMENT_PLAN.md` | Where GLAP is going and which durable gates control progression | Strategy or priority changes |
| Current truth | `CURRENT_DEVELOPMENT_STATUS.md` | What is true now, pending validation, Active Slice, blockers, Next Up | Every formal closeout |
| History | `docs/archive/status/` | What completed, what was validated, and what remained on a date | Session closeout and weekly archive |

`DEVELOPMENT_PLAN.md` must not accumulate daily checkpoints, workflow IDs, or
completed-task logs. `CURRENT_DEVELOPMENT_STATUS.md` retains only the current
week, recent seven-day context, and active carry-over. Archived files are never
current authority and must not be read by default when planning a new slice.

At formal closeout:

1. update `CURRENT_DEVELOPMENT_STATUS.md` for current reality, validation state,
   blockers, and the next executable slice;
2. append session evidence to the current monthly file under
   `docs/archive/status/daily-logs/`;
3. add a feature-level `CHANGELOG.md` entry only for a genuinely completed
   capability;
4. update `DEVELOPMENT_PLAN.md` only when durable direction, ordering, or an
   entry gate changed.

The phrases `今天先到这里`, `收尾`, `update status`, and equivalent explicit
closeout requests authorize these repository-local status and archive updates.
They do not authorize deployment, publication, operational mutation, or a
strategic plan change. On the first active development session on or after
Monday, check whether the previous Monday–Sunday window should be archived;
this is a session-time check, not autonomous background work.

**Reference-implementation history (must not override current architecture):**
- `docs/GLAP_Technical_Implementation.md` — original full-stack engineering;
  uses legacy v1 anomaly/root-cause/decision tables. Its architecture
  descriptions must not override `docs/architecture_current.md`.
- `docs/GLAP_Day1_to_Day20_README.md` — 20-day incremental engineering
  journey; describes earlier architecture phases.
- `docs/decision_flywheel_evidence.md` — self-labelled placeholder using v1
  tables; current closed loop: `docs/governed_closed_loop.md`.
- `docs/archive/status/legacy/` — frozen snapshots of the former mixed-purpose
  TODO and implementation roadmap; these must not override active sources.
- `docs/archive/status/handoffs/` — preserved dated handoffs; use only for
  historical evidence explicitly routed from the current status or archive.

## Task → Context Router

Before making changes, read only what your task requires. Do not scan the
whole repository.

**If changing shipment lifecycle / generators / stateful data:**
→ `docs/shipment_lifecycle_design.md`, `docs/architecture_current.md` (isolated staging boundary section), `CURRENT_DEVELOPMENT_STATUS.md`

**If changing Operations API / authenticated actor surfaces / RBAC:**
→ `docs/operations_api_v1.md`, `docs/governed_closed_loop.md`, `docs/architecture_current.md` (authenticated operations boundary section)

**If changing Decision / Action / Outcome / Learning / governed closed loop:**
→ `docs/governed_closed_loop.md`, `docs/operations_api_v1.md` (mutation endpoints), `CURRENT_DEVELOPMENT_STATUS.md`

**If changing forecasting / model evidence / backtests / label readiness:**
→ `docs/multimodal_forecast_feature_contract.md`, `docs/temporal_truthfulness.md`, `DEVELOPMENT_PLAN.md` (P3), `CURRENT_DEVELOPMENT_STATUS.md`

**If changing Evaluation Architecture / Decision Quality / Historical Replay:**
→ `docs/evaluation_architecture.md`, `docs/historical_replay_lab.md`, `docs/temporal_truthfulness.md`, `DEVELOPMENT_PLAN.md` (P3), `CURRENT_DEVELOPMENT_STATUS.md`

**If changing AWS infrastructure / CloudFormation / deployment / IAM:**
→ `INFRASTRUCTURE.md`, `docs/deployment_workflow.md`, `docs/architecture_current.md`

**If changing pipeline reliability / quality gates / scheduling:**
→ `docs/pipeline_reliability.md`, `docs/architecture_current.md` (reliability boundary section), `docs/ops_snapshot.md` (pipeline status section)

**If changing public OPS analytics / snapshot contract / Control Tower:**
→ `docs/ops_snapshot.md`, `docs/architecture_current.md` (key controls section)

**If changing data contracts / Iceberg schemas / SQL views:**
→ `docs/ops_snapshot.md` (published contract), `docs/multimodal_forecast_feature_contract.md` (feature views), `docs/shipment_lifecycle_design.md` (lifecycle tables), `sql/` directory for existing DDL

**If changing frontend / operator cockpit / public Pages:**
→ `docs/operations_api_v1.md`, `docs/ops_snapshot.md` (public boundary), `CURRENT_DEVELOPMENT_STATUS.md`

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
   `CURRENT_DEVELOPMENT_STATUS.md`, `DEVELOPMENT_PLAN.md` when strategy changed,
   the current archive ledger, rollout/runbook/API documentation, architecture
   statements, drift contracts, validators, and tests mutually consistent
   where they are affected. Do not touch unrelated docs.
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

### End-of-Day Documentation, Commit, and Push Procedure

When the user explicitly asks to finish for the day, update related documents,
and `commit and push`, use this closeout sequence:

1. Inventory the complete worktree with `git status -sb`, tracked diffs, and
   untracked paths. Separate approved deliverables from unrelated user files;
   never include unrelated paths merely because they are present.
2. Run the Documentation and Fact Synchronization Gate across the whole
   approved change. At minimum, check the routed sources of truth,
   `CURRENT_DEVELOPMENT_STATUS.md`, the current monthly daily log,
   `CHANGELOG.md` for completed features, `DEVELOPMENT_PLAN.md` only when
   direction changed, architecture claims, temporal and evidence boundaries,
   schemas, machine-readable drift contracts, validators, and affected test
   totals.
3. Preserve maturity precisely. Documents may state implemented and locally
   verified facts before the commit; the final user handoff must separately
   identify the commit, remote push result, CI state, and anything still
   undeployed, runtime-unverified, or human-owned.
4. Run the applicable validation suite, project drift audit, focused scenario
   or contract runners, stale-claim searches, and `git diff --check`. Resolve
   every failure or document a user-authorized exception before staging.
5. Compare the exact paths to `.github/workflows/` push triggers. A direct
   `main` push is allowed only when the user explicitly requested it and the
   changed paths do not start an unauthorized deployment or Pages publication;
   otherwise use a non-deploying feature branch and report why.
6. Stage approved paths explicitly, inspect `git diff --cached` and
   `git status -sb`, and scan the staged change for credentials, private
   identifiers, or unsupported operational claims. Then create one terse,
   scoped commit unless a documentation-sync follow-up is genuinely required.
7. Before pushing, audit every unpushed commit with `origin/<branch>..HEAD`,
   re-check workflow triggers, and verify the local branch and intended remote.
   Push with ordinary `git push` through the repository's existing credential
   path; do not create a pull request unless requested.
8. After pushing, verify that `HEAD` equals `origin/<branch>`, inspect the
   triggered workflow state when available, and report the exact commit plus
   all remaining uncommitted, undeployed, unverified, or human-authorized work.

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

For every completed feature, the final handoff must answer all six questions.
This applies after each feature-sized development slice, not only at the end of
a release or multi-feature session:

1. **What is it?** Describe what was built or changed and what a user or operator
   can now do. Start with everyday language; add technical terms only when they
   improve clarity.
2. **What previous capability does it connect to?** Name the upstream feature,
   data, workflow, or decision that supplies its inputs or made this work
   possible. Explain the connection, not just the component name.
3. **What is the short-term benefit?** State the immediate user, operator, or
   engineering improvement that is available now, using a concrete effect
   rather than a generic value claim.
4. **What is the long-term benefit?** Explain the durable platform, product,
   evidence, governance, cost, or risk advantage this feature creates if the
   roadmap continues.
5. **What feature should be developed next?** Name one concrete next feature and
   its purpose. Distinguish a recommendation from approved or implemented work;
   if the next feature requires a human choice or new authority, state that
   boundary explicitly.
6. **How do the two features connect?** Explain exactly how the completed
   feature's outputs, contracts, evidence, or workflow become inputs or
   prerequisites for the next feature. Do not merely say that one follows the
   other.

Use the user's language and this compact structure unless the user asks for
another format:

```text
Completed: <plain-language explanation of what it is>
Upstream connection: <the previous capability and how this uses it>
Short-term benefit: <the concrete value available now>
Long-term benefit: <the durable project or platform advantage>
Next feature: <one concrete feature to develop next and its purpose>
Feature connection: <how this feature enables or supplies the next one>
Verification: <tests, quality gates, deployment, or runtime evidence>
```

When several deliverables are completed together, give each meaningful
deliverable its own six-part explanation or use a table with the same six
relationships. Clearly distinguish what is already implemented and verified
from what is only enabled, recommended, or planned next. Do not collapse
short-term and long-term benefits into one generic project-value statement.

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
