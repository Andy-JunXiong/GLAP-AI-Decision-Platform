# GLAP three-minute product walkthrough

## Demo goal

Show how GLAP turns an emerging logistics disruption into an explainable,
human-reviewed decision and a measurable outcome. The scenario and financial
values are synthetic; the documented AWS implementation evidence is based on
inspected deployed resources.

Open [`../offline/glap-demo.html`](../offline/glap-demo.html) in a modern
browser. No server or account is required.

## 0:00–0:30 — Start with the operational problem

On **Control Tower**, point out the critical signals, pending decisions, cost
exposure and inventory at risk. Open **Divert 8 FCL via Melbourne** from the
attention queue.

Narrative:

> Sydney port congestion is 2.5 times its baseline and labour-strike
> probability has reached 82%. Twelve containers of critical inventory may
> remain at port longer than the eight days of inventory cover.

## 0:30–1:20 — Explain the recommendation

On **Decision Brief**, connect the recommendation to its evidence:

- expected dwell is nine days;
- free storage covers only three days;
- no-action storage exposure is AUD 15,840;
- diverting eight high-priority FCL produces a modelled net benefit of
  AUD 5,760 and lowers stockout risk.

Move the diversion slider away from eight. Show that the economics and risk
change immediately. Attempt to approve the override and record a reason. This
demonstrates that operator judgement is allowed but remains auditable.

## 1:20–2:05 — Demonstrate the human control

Return the slider to eight and approve the recommendation. Point out that:

- the approval is added to the decision ledger;
- the decision queue no longer reports the same pending item;
- affected shipment records reflect the approved action;
- Outcomes receives a pending expected-benefit record.

Change the owner or decision object after approval to show that the previous
approval is invalidated rather than silently reused.

## 2:05–2:40 — Close the decision loop

Open **Outcomes**. Contrast expected benefit with observed results for completed
decisions and distinguish the newly approved diversion, whose observed outcome
is still pending.

The important message is that GLAP does not count a recommendation as realised
value. It keeps expected and observed impact separate until reconciliation.

## 2:40–3:00 — Show the engineering evidence

Open **System** and briefly visit:

- **AWS Overview** for deployed compute, catalog, scheduling and monitoring;
- **Data Catalog** for the business meaning of the Iceberg contracts;
- **Logic & SQL** for deterministic rules and idempotency;
- **OPS Dashboard** for pipeline and failure-recovery evidence;
- **Release & Lineage** for GitHub OIDC, immutable versions and product-to-data
  mappings.

Finish with the evidence boundary: AWS runtime evidence is real, while public
shipment records, outcome values and savings are synthetic validation data.

## Optional follow-up questions

### Why deterministic rules instead of an autonomous agent?

Port diversion has real cost and service consequences. Deterministic rules make
the recommendation explainable and testable, while the human gate controls
execution. A language model can later assist with explanation or policy
analysis without bypassing the safety rules.

### What would make this production-ready?

Durable approval APIs, carrier or TMS integration, identity and role controls,
live source-quality monitoring, observed-outcome reconciliation and production
performance validation are still required.
