# Project drift audit

GLAP uses a deterministic, read-only repository audit to detect architecture,
capability, documentation, and evidence-boundary drift before semantic review.
The machine-readable baseline is
[`project_drift_contract.json`](project_drift_contract.json).

## Commit-time checks

Activate the repository-scoped hook once on a new clone:

```powershell
./ops/install_project_hooks.ps1 -Apply
```

The versioned `.githooks/pre-commit` hook materializes the exact Git index into
a temporary directory, then runs whitespace checks, Python compilation, the
drift audit, and the complete Python unit-test suite against that staged
snapshot.  Unstaged changes therefore cannot hide a drift that is about to be
committed.  Frontend lint, build, and rendered tests also run when a staged file
under `decision-brief-demo/` changes.  Any failure blocks the commit.

The installer changes only this repository's local `core.hooksPath` and records
the resolved Python executable under the local `glap.pythonPath` key.  That path
is machine-local Git configuration, not a repository file, credential, or
global setting.  A developer may bypass a local hook, so CI remains an
independent second gate.

## Automatic checks after push

Every pull request and push to `main` runs:

```bash
python ops/audit_project_drift.py --format markdown
```

The audit fails closed when a protected invariant changes.  It currently
checks that:

- declared canonical and capability evidence exists;
- the baseline date does not exceed the current Sydney business date;
- lifecycle and forecast staging workflows remain manual-only;
- the stateful staging stack has no Scheduler or Lambda alias;
- public Pages contains no private Operations API or Cognito configuration;
- implemented Action operations remain exactly `EDIT`, `APPROVE`, `REJECT`,
  and `COMPLETE`, while the assignment canary's response fix, stable retry, and
  separate approver decision retain their current maturity;
- authenticated Operations queries retain the operational actual-calendar
  boundary and advisory forecasts retain no production effect;
- the Action–Outcome evidence chain remains an authenticated read-only `GET`
  route over the immutable Action, cutoff-eligible audit, and eligible Outcome
  sources; its UI retains the synthetic-performance disclosure and its maturity
  remains merged and plan-verified but undeployed; release preflight must
  inspect all three Glue sources and runtime verification remains opt-in until
  deployment;
- the Outcome-to-Learning gate counts only cutoff-eligible observed Outcomes,
  reads the exact governed policy-proposal table, keeps policy activation and
  deterministic-rule replacement false, preserves named-human review, and
  remains merged but undeployed behind independent opt-in post-release
  verification;
- capability-neutral External Evidence and Decision Memory experiments remain
  local, controlled-synthetic, read-only ablations with higher evaluation
  layers explicitly unevaluated;
- the Agent Runtime registry, parity run, canonical input bundle, and host
  traces retain their no-network/no-mutation/no-approval boundary; and
- a separately supplied four-file adapter package passes inspected,
  deterministic, bundle-bound offline replay before it can be considered for
  any separately authorized registration or host comparison.

The manual **Project drift audit** workflow generates a Markdown report artifact
without assuming an AWS role.  It has `contents: read` permission and cannot
deploy, publish Pages, mutate Actions, activate policy, promote a model, or
enable a recurring schedule.

## Semantic review boundary

The deterministic audit protects explicit contracts; it cannot decide whether
a new product direction still serves GLAP's business purpose. A periodic AI
review should therefore read the generated report together with the canonical
architecture, `DEVELOPMENT_PLAN.md`, `CURRENT_DEVELOPMENT_STATUS.md`, temporal
rules, and routed implementation evidence. Archived TODOs and handoffs remain
historical evidence rather than current authority. The review must distinguish
implemented code, deployed staging evidence, actual-calendar maturity, future
simulation, and planned capability.

Enabling a recurring GitHub schedule is a separate human-owned change.  Until
that approval occurs, drift checks run automatically on repository changes and
the report workflow remains manually dispatchable.
