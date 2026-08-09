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
- implemented Action operations remain exactly `APPROVE`, `REJECT`, and
  `COMPLETE`, while edit, owner, and due date remain explicitly unimplemented;
- authenticated Operations queries retain the operational actual-calendar
  boundary and advisory forecasts retain no production effect.

The manual **Project drift audit** workflow generates a Markdown report artifact
without assuming an AWS role.  It has `contents: read` permission and cannot
deploy, publish Pages, mutate Actions, activate policy, promote a model, or
enable a recurring schedule.

## Semantic review boundary

The deterministic audit protects explicit contracts; it cannot decide whether
a new product direction still serves GLAP's business purpose.  A periodic AI
review should therefore read the generated report together with the canonical
architecture, roadmap, TODO, latest handoff, and implementation evidence.  That
review must distinguish implemented code, deployed staging evidence,
actual-calendar maturity, future simulation, and planned capability.

Enabling a recurring GitHub schedule is a separate human-owned change.  Until
that approval occurs, drift checks run automatically on repository changes and
the report workflow remains manually dispatchable.
