# Current Architecture and Trust Boundaries

## Product decision flow

```mermaid
flowchart LR
    SIGNALS[Shipment, port and disruption signals] --> DETECT[Detect anomaly]
    DETECT --> EXPOSE[Estimate fee and inventory exposure]
    EXPOSE --> DECIDE[Recommend action and priority]
    DECIDE --> REVIEW{Human review}
    REVIEW -->|Approve| ACTION[Execute diversion or escalation]
    REVIEW -->|Edit / reject| FEEDBACK[Record feedback]
    ACTION --> OUTCOME[Measure cost and in-stock outcome]
    FEEDBACK --> LEARN[Policy-learning input]
    OUTCOME --> LEARN
```

## AWS runtime and delivery architecture

```mermaid
flowchart TB
    subgraph Delivery[Delivery boundary]
        DEV[Git commit / PR] --> CI[GitHub Actions CI]
        CI -->|manual workflow| OIDC[GitHub OIDC]
        OIDC --> CANDIDATE[Lambda candidate]
        CANDIDATE --> DRYRUN[Read-only dry-run]
        DRYRUN --> VERSION[Immutable Lambda version]
        VERSION --> PROMOTER[Staging-only promoter]
        PROMOTER --> STAGING[staging alias]
        PROD[prod alias]
    end

    subgraph Runtime[Runtime boundary]
        SCHEDULER[EventBridge Scheduler] --> PROD
        RAW[S3 raw events] --> GLUE[Glue Catalog]
        GLUE --> ATHENA[Athena + Iceberg]
        PROD --> ATHENA
        STAGING -. dry-run only .-> ATHENA
        ATHENA --> OUTPUTS[Alert / insight / decision / action / outcome / learning]
        OUTPUTS --> QS[QuickSight]
        OUTPUTS --> EXPORT[Sanitized aggregate export]
        EXPORT --> PAGES[Public OPS Analytics]
    end

    subgraph Reliability[Reliability boundary]
        SCHEDULER -->|after retries| DLQ[Encrypted SQS DLQ]
        PROD --> CW[CloudWatch alarms]
        DLQ --> CW
        CW --> SNS[SNS notifications]
    end
```

## Key controls

- GitHub receives short-lived AWS credentials through OIDC.
- The staging deployer cannot update the `prod` alias.
- Candidate and staging smoke tests use dry-run mode and do not insert decisions.
- Alias mutation is delegated to code hard-locked to `staging`.
- Production Scheduler targets `prod`, not mutable `$LATEST`.
- Failed scheduled invocations retry twice before entering the encrypted DLQ.
- The public Pages role is read-only and publishes aggregate analytics without
  entity, route, carrier, account, ARN, or S3 identifiers.
- Current public health follows the v3/v2 decision flywheel. Stale v1 anomaly,
  root-cause, and decision tables remain historical evidence only.

## Isolated stateful multimodal staging boundary

The lifecycle and analytics foundation is deployed beside, not inside, the
production runtime boundary:

```mermaid
flowchart LR
    MANUAL[Manual invocation only] --> CTRL[Isolated success-gated controller]
    CTRL --> GEN[Stateful lifecycle generator]
    GEN --> ICE[Staging Iceberg lifecycle history]
    ICE --> LIFE[19 lifecycle checks]
    LIFE --> COMPAT[5 v2 compatibility checks]
    COMPAT --> ANALYTICS[8 multimodal analytics checks]
    ICE --> VIEWS[Six read-only operations / feature / label views]
    VIEWS --> PRIVATE[Private analysis and forecast backtesting]
```

Maersk and KN use Ocean routes, port milestones, containers, and per-container
cost. DHL uses Air routes, airport milestones, chargeable kilograms, and per-kg
cost. Origin, P2P, Destination, final delivery, SLA, and outcome semantics are
common. Lane decisions normalize simulated weight only for an explicit
Air-vs-Ocean cost comparison; operational commercial units remain separate.

The staging stack has no Scheduler resource, production alias, or permission to
write the current v2 production tables. Its next consumer is private,
time-ordered forecast backtesting, not autonomous production decisions.

## Authenticated internal Operations boundary — implemented in private staging

The authenticated Operations API, Cognito four-role boundary, and private
Operations cockpit are implemented, deployed, and verified in private staging.
They support the governed Decision Queue, Action Board, `APPROVE` / `REJECT` /
`COMPLETE` mutations, Risk Hotspots, Outcome Review, Pipeline Health, Forecast
Accuracy, and authorised Network Drill-down. Public GitHub Pages remains
aggregate-only and read-only, with no private API or Cognito configuration.

The repository additionally implements an append-only `EDIT` event for a named
Action owner and due date. It moves `PROPOSED` to `EDITED` and still requires a
separate approver. This is repository evidence only: the additive staging
schema migration in `sql/15_action_assignment_v1.sql` is plan-only and the
deployed Operations boundary remains the three-operation contract above.

This staging deployment does not authorise production expansion: production
aliases, recurring lifecycle or forecast schedules, automatic policy
activation, supervised-model promotion, and public entity-level writes remain
separate human-approved decisions.

```mermaid
flowchart LR
    USER[Authenticated operator] --> API[Operations API]
    API --> REVIEW[Human decision review]
    API --> ACTION[Action status]
    API --> OUTCOME[Observed outcome]
    REVIEW --> AUDIT[Append-only audit]
    ACTION --> AUDIT
    OUTCOME --> AUDIT
    REVIEW --> LAKE[Athena / Iceberg]
    ACTION --> LAKE
    OUTCOME --> LAKE
    AUDIT --> LAKE
    LAKE --> INTERNAL[Internal operations cockpit]
    LAKE -->|aggregate only| PUBLISH[Public OPS snapshot]
```

The private staging boundary retains success-gated orchestration and
data-quality controls. Future simulations remain isolated engineering evidence
and do not establish operational performance, outcome maturity, model
readiness, promotion, or production reporting. See the
[implementation roadmap](implementation_roadmap.md) for remaining production
readiness dependencies.
