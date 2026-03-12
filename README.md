# GLAP — AI-Native Logistics Decision Intelligence Platform

GLAP (Global Logistics Analytics Platform) is an AI-native logistics decision intelligence system designed to transform traditional analytics pipelines into an automated operational AI platform.

The system detects logistics anomalies, performs root cause analysis, generates decision recommendations, and visualizes insights through operational dashboards.

---

## System Architecture

![System Architecture](docs/architecture.png)

GLAP combines a modern lakehouse architecture with AI reasoning and automation:

Synthetic Logistics Generator  
→ Iceberg Lakehouse (S3 + Glue + Athena)  
→ AI Anomaly Detection  
→ Root Cause Analysis  
→ Decision Recommendation Engine  
→ Lambda Orchestration  
→ EventBridge Scheduling  
→ Operational Intelligence Dashboards

---

## Data Lineage

![Data Lineage](docs/data_lineage.png)

The AI decision pipeline follows a structured lineage from raw logistics events to governed metrics, AI anomaly signals, root cause explanations, and decision outputs.

---

## Dashboard Demo

![Dashboard](docs/dashboard.png)

Amazon QuickSight dashboards expose AI-generated operational intelligence including decision feeds, priority distribution, recommended actions, and route performance insights.

---

## Key Features

- **AI Anomaly Detection**  
  Detect abnormal logistics behavior using statistical anomaly detection.

- **Root Cause Analysis Agent**  
  Automatically interpret anomaly signals and identify operational causes.

- **Decision Recommendation Engine**  
  Generate structured logistics actions with decision priorities.

- **Lakehouse Data Platform**  
  Built on Apache Iceberg with AWS S3, Glue, and Athena.

- **Automated AI Pipeline**  
  Lambda orchestration with EventBridge scheduling.

- **Operational Intelligence Dashboards**  
  Visualize AI insights using Amazon QuickSight.

---

## AI Decision Flywheel

The system forms a continuous operational intelligence loop:

Detection  
→ Root Cause Analysis  
→ Decision Generation  
→ Operational Insights  
→ Outcome Evaluation  
→ Learning Signals  
→ Policy Update

This flywheel enables the platform to continuously improve operational decision quality.

---

## Technology Stack

- Amazon S3
- Apache Iceberg
- AWS Glue Data Catalog
- Amazon Athena
- AWS Lambda
- Amazon EventBridge Scheduler
- Amazon CloudWatch
- Amazon QuickSight
- Python
- SQL

---

## Repository Structure

```text
GLAP-AI-Decision-Platform/
│
├── README.md
├── GLAP_Technical_Implementation.md
│
└── docs/
    ├── architecture.png
    ├── data_lineage.png
    └── dashboard.png
