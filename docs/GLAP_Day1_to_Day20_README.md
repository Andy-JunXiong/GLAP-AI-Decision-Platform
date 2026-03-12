
# GLAP — AI‑Native Logistics Decision Platform
## Full Engineering Journey (Day 1 → Day 20)

GLAP is an end‑to‑end **AI‑driven logistics decision intelligence platform** built using a modern **AWS lakehouse + serverless + AI agent architecture**.

This project demonstrates how operational data pipelines can evolve into an **AI decision system** capable of:

- Detecting operational anomalies
- Explaining root causes
- Generating operational decisions
- Automating daily execution
- Delivering insights via dashboards

The project was intentionally built **incrementally across 20 engineering days** to simulate the development lifecycle of a real AI platform.

---

# Final System Overview

The completed GLAP platform operates as an automated AI decision pipeline.

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

# Technology Stack

Cloud Platform

- AWS S3
- AWS Lambda
- Amazon Athena
- AWS Glue Data Catalog
- Amazon EventBridge Scheduler
- Amazon QuickSight

Data & Processing

- Apache Iceberg
- SQL
- Python

Architecture Patterns

- Lakehouse architecture
- Serverless data platform
- AI agent decision pipeline
- Automated orchestration

---

# Project Evolution

This section describes the **engineering evolution from Day 1 to Day 20**.

---

# Phase 1 — Synthetic Logistics Data (Day 1–4)

The project began by building a **synthetic logistics operations dataset**.

Real logistics systems require shipment events, delivery times, and route data to analyze operations.

### Goals

Create a controllable dataset that simulates real logistics behavior.

### Generator Characteristics

- ~400–500 shipments per day
- 5–10% random variability
- Delivery performance ~90–95%

### Example Fields

```
shipment_id
origin_port
destination_port
carrier
event_time
delivery_time
status
```

### Output Table

```
fact_shipment_events_extended_iceberg
```

This dataset became the operational foundation for all downstream AI analysis.

---

# Phase 2 — Lakehouse Data Platform (Day 5–8)

The next step was building the **data platform architecture**.

Instead of a traditional warehouse, the system used a **lakehouse model**.

### Architecture

```
S3 Storage
↓
Iceberg Tables
↓
Glue Data Catalog
↓
Athena SQL
```

### Advantages

- ACID transactions
- Schema evolution
- Time travel
- Low‑cost analytics

### Data Layers

```
raw
curated
clean
```

This phase established the **data engineering backbone of the system**.

---

# Phase 3 — AI Anomaly Detection (Day 9–12)

Once the logistics data platform existed, the next step was detecting operational issues.

### Metrics Monitored

```
breach_rate
avg_leg_duration_days
```

### Detection Method

Statistical anomaly detection using **z‑score**.

```
z_score = (metric_value − baseline_value) / std_dev
```

### Output Table

```
fact_ai_anomaly_scores_v1
```

### Schema

```
run_date
entity_key
metric_name
metric_value
baseline_value
z_score
```

This stage allowed the system to **detect abnormal logistics behavior automatically**.

---

# Phase 4 — Root Cause Agent (Day 13–15)

The anomaly detection system identified problems, but it did not explain them.

Day 13–15 introduced the **Root Cause Agent**.

### Purpose

Translate anomaly signals into operational explanations.

### Example Rules

```
avg_leg_duration_days ↑
→ carrier delay
→ port congestion

breach_rate ↑
→ SLA reliability degradation
```

### Output Table

```
fact_ai_root_cause_v1
```

### Fields

```
run_date
entity_key
metric_name
root_cause
confidence_score
supporting_metric
created_at
```

This step introduced the first **AI reasoning layer** in the platform.

---

# Phase 5 — Decision Agent (Day 16–17)

Once root causes were identified, the system could recommend actions.

### Decision Logic

```
confidence ≥ 0.75 → HIGH priority

confidence < 0.75 → MEDIUM priority
```

### Example Recommendations

```
Investigate carrier delay
Escalate SLA reliability issue
Continue monitoring metrics
```

### Output Table

```
fact_ai_decision_explanations_v1
```

### Fields

```
run_date
entity_key
metric_name
recommended_action
decision_reason
action_priority
created_at
```

This stage turned the platform into a **decision intelligence system**.

---

# Phase 6 — AI Decision Flywheel (Day 17)

At this stage the system formed an operational AI loop.

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

This architecture is commonly referred to as an **AI Decision Flywheel**.

---

# Phase 7 — Dashboard Layer (Day 18–19)

The AI pipeline existed but lacked visibility.

Day 18–19 focused on building an **operations dashboard**.

### Tool

```
Amazon QuickSight
```

### Dataset

```
fact_ai_decision_explanations_v1
```

### Dashboard Components

Decision Table

```
run_date
route_label
metric_name
recommended_action
action_priority
```

Decision Priority Distribution

```
HIGH
MEDIUM
```

Recommended Action Distribution

```
monitor metrics
investigate delay
escalate SLA issue
```

Top Problem Routes

Shows routes with the highest anomaly frequency.

### UX Improvements

A calculated field `route_label` was created to transform internal entity keys into readable route names.

Example

```
DEHAM → AUSYD (DHL)
```

This phase transformed GLAP from a backend system into an **operational product interface**.

---

# Phase 8 — Automation & Orchestration (Day 20)

The final phase automated the entire system.

### Orchestrator

```
AWS Lambda
```

Responsibilities

```
Read anomaly scores
Generate root cause analysis
Insert root cause records
Generate decisions
Insert decision records
```

### Automation

```
EventBridge Scheduler
```

Daily trigger

```
glap-ai-agent-orchestrator
```

### Execution Flow

```
Scheduler
↓
Lambda Orchestrator
↓
Athena queries
↓
Iceberg tables updated
↓
QuickSight dashboard refresh
```

The platform became a **fully automated AI decision pipeline**.

---

# Example Decision Output

```
Route: DEHAM → AUSYD (MAERSK)

Metric:
avg_leg_duration_days

Root Cause:
Transit time increased relative to historical baseline

Recommended Action:
Investigate carrier transit delay

Priority:
HIGH
```

---

# Final System Capabilities

By Day 20 the GLAP platform could:

```
Generate logistics data
Detect operational anomalies
Explain root causes
Generate decisions
Store insights in Iceberg tables
Visualize insights in dashboards
Run automatically every day
```

---

# System Architecture Summary

GLAP demonstrates a modern AI‑native architecture combining:

- Lakehouse data platform
- AI reasoning agents
- Serverless orchestration
- Automated scheduling
- Operational dashboards

The project represents a realistic **AI operations platform prototype**.

---

# Author

Jun Xiong

Background

- Data Science
- Logistics Operations
- Cloud Architecture
- AI Systems Engineering

---

# Project Goal

GLAP explores how **AI‑native architectures can transform operational analytics into automated decision intelligence systems.**
