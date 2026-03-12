
# GLAP — Technical Implementation
## AI‑Native Logistics Decision Platform

This section describes the **technical implementation of GLAP**, covering how the system was engineered across the full stack: data generation, lakehouse architecture, anomaly detection, AI agents, orchestration, automation, and dashboards.

GLAP demonstrates how a logistics analytics pipeline can evolve into an **AI‑driven decision intelligence platform** using a modern serverless architecture on AWS.

---

# 1. Synthetic Data Generator

GLAP begins with a **Python-based logistics data generator** that simulates real-world operational data.

## Implementation

The generator produces shipment-level logistics data with controlled variability.

Generated attributes include:

- shipment_id
- origin_port
- destination_port
- carrier
- planned_delivery_date
- actual_delivery_date
- status
- leg_duration_days

The generator enforces realistic operational constraints:

- ~400–500 shipments per day
- 5–10% random variation
- On‑time delivery (OTD) around 90–95%

## Output Pipeline

Generated data is written to:

- Amazon S3
- Apache Iceberg tables

Primary table:

```
fact_shipment_events_extended_iceberg
```

This dataset provides the **operational baseline for downstream AI analysis**.

---

# 2. Iceberg Lakehouse Architecture

GLAP uses a **lakehouse architecture** built on AWS.

## Architecture

```
Amazon S3
↓
Apache Iceberg Tables
↓
AWS Glue Data Catalog
↓
Amazon Athena SQL
```

## Storage

- Amazon S3 stores Parquet/Iceberg data files.

## Table Format

- Apache Iceberg provides:
  - ACID transactions
  - schema evolution
  - partition optimization
  - time‑travel capabilities

## Query Engine

- Amazon Athena Engine v3 is used for serverless querying.

## Metadata

- AWS Glue Data Catalog manages table definitions.

## Core Tables

```
fact_shipment_events_extended_iceberg
fact_ai_anomaly_scores_v1
fact_ai_root_cause_v1
fact_ai_decision_explanations_v1
```

---

# 3. Anomaly Detection Layer

The anomaly detection layer identifies abnormal logistics behavior.

## Input Data

Aggregated shipment metrics per route/carrier.

Key monitored metrics:

- breach_rate
- avg_leg_duration_days

## Detection Method

Statistical anomaly detection using **z-score**.

Formula:

```
z_score = (metric_value − baseline_value) / std_dev
```

## Output Table

```
fact_ai_anomaly_scores_v1
```

Schema:

```
run_date
entity_key
metric_name
metric_value
baseline_value
z_score
```

This layer enables **automated detection of operational issues**.

---

# 4. Root Cause Agent

The Root Cause Agent explains detected anomalies.

## Implementation

Currently implemented as a **rule‑based Python agent**.

The agent processes anomaly signals and converts them into operational explanations.

## Example Logic

```
avg_leg_duration_days ↑
→ Carrier transit delay
→ Port congestion

breach_rate ↑
→ SLA reliability degradation
```

## Output Table

```
fact_ai_root_cause_v1
```

Fields:

```
run_date
entity_key
metric_name
root_cause
confidence_score
supporting_metric
created_at
```

## Engineering Design

- Structured output instead of free text
- Traceable reasoning logic
- Easy upgrade path to LLM‑based reasoning

---

# 5. Decision Agent

The Decision Agent generates operational recommendations.

## Input

Root cause records produced by the Root Cause Agent.

## Decision Rules

Example decision logic:

```
if confidence ≥ 0.75:
    action_priority = HIGH
else:
    action_priority = MEDIUM
```

Example recommended actions:

```
Investigate carrier transit delay
Escalate SLA reliability issue
Continue monitoring operational metrics
```

## Output Table

```
fact_ai_decision_explanations_v1
```

Schema:

```
run_date
entity_key
metric_name
recommended_action
decision_reason
action_priority
created_at
```

At this stage the platform evolves into a **decision intelligence system**.

---

# 6. Lambda Orchestrator

The core system workflow is managed by an **AWS Lambda orchestrator**.

Lambda name:

```
glap-ai-agent-orchestrator
```

## Responsibilities

1. Read anomaly scores from Athena
2. Generate root cause explanations
3. Insert root cause records
4. Generate decision recommendations
5. Insert decision records

## Implementation Details

The Lambda function uses **boto3** to interact with Athena.

Key helper functions:

```
start_query(sql)
wait_for_query(query_id)
get_query_results(query_id)
run_query(sql)
```

The Lambda orchestrator executes SQL queries against Iceberg tables and manages the AI pipeline execution.

## Deduplication Protection

To avoid duplicate records:

- Check if a decision already exists for
  - run_date
  - entity_key
  - metric_name

If the record exists → skip insertion.

---

# 7. EventBridge Automation

The system is automated using **Amazon EventBridge Scheduler**.

## Scheduler

```
glap-ai-agent-orchestrator-daily
```

## Execution Flow

```
EventBridge Scheduler
↓
Lambda Orchestrator
↓
Athena SQL queries
↓
Iceberg tables updated
```

## Lambda Permission

The scheduler invokes the Lambda function using a **resource‑based policy**.

Example permission configuration:

```
Principal: scheduler.amazonaws.com
Action: lambda:InvokeFunction
SourceArn: EventBridge schedule ARN
```

This enables **fully automated daily execution**.

---

# 8. QuickSight Visualization Layer

GLAP exposes operational insights using **Amazon QuickSight dashboards**.

## Data Source

```
fact_ai_decision_explanations_v1
```

## Dashboard Components

### Decision Feed Table

Columns:

```
run_date
route_label
metric_name
recommended_action
action_priority
```

### Decision Priority Distribution

Horizontal bar chart showing:

```
HIGH
MEDIUM
```

### Recommended Action Distribution

Displays counts of:

```
Continue monitoring
Investigate delay
Escalate SLA issue
```

### Top Problem Routes

Identifies routes with the highest anomaly frequency.

## Readability Improvement

A calculated field `route_label` was created to convert internal entity keys into readable route names.

Example:

```
DEHAM → AUSYD (DHL)
```

---

# 9. End‑to‑End Data Flow

The full GLAP system operates as follows:

```
Synthetic Logistics Generator
↓
Iceberg Lakehouse (S3 + Glue)
↓
AI Anomaly Detection
↓
Root Cause Agent
↓
Decision Agent
↓
Lambda Orchestrator
↓
EventBridge Scheduler
↓
Iceberg Decision Tables
↓
QuickSight Dashboard
```

---

# 10. AI Decision Flywheel

GLAP forms a continuous operational intelligence loop.

```
Operations Data
↓
Anomaly Detection
↓
Root Cause Analysis
↓
Decision Generation
↓
Operational Insights
↓
Continuous Monitoring
```

This architecture represents an **AI Decision Flywheel**, enabling automated detection, explanation, and response to operational issues.

---

# Engineering Significance

GLAP is not a single script or dashboard project.

It is a **multi‑layer AI operations platform** consisting of:

- data generation
- lakehouse infrastructure
- anomaly detection
- reasoning agents
- decision agents
- orchestration
- automation
- operational dashboards

The project demonstrates how modern cloud architecture can support **AI‑native decision systems for logistics operations**.
