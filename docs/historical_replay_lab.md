# Historical Replay Lab v0.4

**Scenario contract:** `historical-replay-scenario.v1`
**Corpus contract:** `historical-replay-corpus.v1`
**Evidence class:** `HYBRID_HISTORICAL_REPLAY`
**Maturity:** `PILOT_NOT_BENCHMARK`

## Purpose

Historical Replay freezes what GLAP could have known at selected historical
cutoffs, combines that public evidence with explicitly controlled synthetic
enterprise state, and repeats a paired capability experiment. It accelerates
evaluation without presenting synthetic Inventory, SLA, priority, or capacity
assumptions as company records.

`HYBRID_HISTORICAL_REPLAY` is an evaluation evidence class, not a lifecycle
`execution_mode`. Its rows cannot enter operational views, default backtests,
label readiness, production reporting, or policy/model promotion evidence.

The corpus now contains five events, five disruption types, three regions,
three transport modes (OCEAN, AIR, and RAIL), and two severity bands (HIGH and
MEDIUM). It proves cross-mode and no-delta-control mechanics while remaining
below the representative logistics benchmark threshold.

## Frozen corpus

| Scenario | Disruption type | Region | Cutoff behavior |
| --- | --- | --- | --- |
| 2024 Baltimore Key Bridge | Infrastructure failure | North America | No delta at T0; A303-attributed delta at T1 and T2 |
| 2023 Panama Canal drought | Capacity restriction | Central America | No delta at T0 or medium-signal T1; attributed delta after high-risk T2 evidence |
| 2023–2024 Red Sea attacks | Maritime security | Middle East | No delta at T0; attributed delta at T1 and T2 |
| 2023 FAA NOTAM outage | Air-traffic system outage | North America | No delta before or during LOW/MEDIUM signals; attributed delta after the nationwide ground stop |
| 2022 U.S. rail labor dispute | Labor-disruption risk | North America | MEDIUM evidence at T1 and T2; no A303 delta at any cutoff |

Across the corpus there are 15 decision cutoffs: six with an attributed A303
decision change and nine with no delta. These are scenario-level attribution
counts, not wins, quality scores, or business effects.

## Authoritative source sets

The corpus stores source metadata, short paraphrased facts, and SHA-256 digests
of those extracted facts. It does not copy full articles or reports.

### Baltimore

- [USACE initial channel response](https://www.nab.usace.army.mil/Media/News-Releases/Article/3719448/us-army-corps-of-engineers-leading-effort-to-clear-fort-mchenry-channel-followi/)
- [USACE tentative reopening timeline](https://www.nab.usace.army.mil/Media/News-Releases/Article/3731790/us-army-corps-of-engineers-develops-tentative-timeline-to-reopen-fort-mchenry-c/)
- [USACE limited-access progress](https://www.nab.usace.army.mil/Media/News-Stories/Article/3752210/us-army-corps-of-engineers-clears-wreckage-from-limited-access-channel-in-port/)
- [NTSB preliminary report](https://www.ntsb.gov/investigations/Documents/DCA24MM031_PreliminaryReport%203.pdf)

The first USACE page is labelled as published on 26 March but its current body
contains an “as of March 30” status. No trustworthy revision timestamp is
present. The inspected revision is therefore available only from
`2024-03-31T00:00:00-04:00`; it is not backdated to the original page date.

### Panama Canal

- [A-47-2023 booking-condition transition](https://pancanal.com/wp-content/uploads/2023/01/ADV47-2023.pdf)
- [A-48-2023 drought transit reduction](https://pancanal.com/wp-content/uploads/2023/01/ADV48-2023-Reduction-in-Transits-Due-to-the-Ongoing-Deficit-in-Precipitation-in-the-Canal-Watershed.pdf)
- [A-54-2023 later booking-slot increase](https://pancanal.com/wp-content/uploads/2023/01/ADV54-2023-Increase-in-the-Number-of-Booking-Slots-in-the-Panamax-and-Neopanamax-Locks-and-Other-Modifications-to-the-Transit-Reservation-System.pdf)

The first advisory is deliberately labelled MEDIUM. A303 does not fire merely
because some capacity-management evidence exists. The later drought and
progressive slot-reduction advisory supplies the first HIGH route-risk signal.
A-54 is isolated as a post-decision recovery reveal.

### Red Sea

- [IMO statement of 19 December 2023](https://www.imo.org/en/mediacentre/secretarygeneral/pages/red-sea-statement-19-december-2023.aspx)
- [IMO update of 4 January 2024](https://www.imo.org/en/mediacentre/pages/whatsnew-2023.aspx)
- [IMO Maritime Safety Committee update of 24 May 2024](https://www.imo.org/en/mediacentre/pressbriefings/pages/imo-msc-resolution-red-sea.aspx)

The first two records are eligible decision evidence at successive cutoffs.
The May update is reveal-only and cannot enter either earlier recommendation.

### FAA NOTAM outage

- [FAA outage hotline advisory at 00:47 UTC](https://www.fly.faa.gov/adv/adv_otherdis?adv_date=01112023&advn=4&facId=DCC&title=NOTAM+OUTAGE+HOTLINE_FYI&titleDate=01%2F11%2F23)
- [FAA system-failure advisory at 01:20 UTC](https://www.fly.faa.gov/adv/adv_otherdis?adv_date=01112023&advn=6&facId=DCC&title=NOTAM+SYSTEM+EQUIPMENT+OUTAGE_FYI&titleDate=01%2F11%2F23)
- [FAA nationwide ground stop at 12:21 UTC](https://www.fly.faa.gov/adv/adv_otherdis?adv_date=01112023&advn=28&facId=DCC&title=NATIONWIDE+GROUND+STOP&titleDate=01%2F11%2F23)
- [FAA stable-system operations update at 20:43 UTC](https://www.fly.faa.gov/adv/adv_otherdis?adv_date=01112023&advn=87&facId=DCC&title=OPERATIONS+PLAN&titleDate=01%2F11%2F23)

The first two advisories produce only LOW and MEDIUM signals. The ground-stop
advisory supplies the first HIGH signal; the later stable-system update is
reveal-only. This is the first AIR-mode scenario and the first use of official
minute-level source timestamps.

### U.S. rail labor dispute

- [Executive Order 14077 record](https://www.govinfo.gov/app/details/DCPD-202200629)
- [Presidential Emergency Board No. 250 report](https://nmb.gov/NMB_Application/wp-content/uploads/2022/08/PEB-250-Report-and-Recommendations.pdf)
- [Department of Labor tentative-agreement statement](https://www.dol.gov/newsroom/releases/osec/osec20220915)

This scenario measures then-observed operational impact rather than the
hypothetical worst case. The emergency-board and recommendation records are
MEDIUM decision evidence; no nationwide stoppage is observed within the frozen
decision window. The later tentative agreement is resolution reveal only.
Every cutoff therefore remains a no-delta control.

## Conservative availability policy

When an authoritative source exposes a signed or declared exact timestamp,
`published_at` and `available_at` must be identical and
`publication_precision=EXACT_TIMESTAMP`. The timestamp cannot be shifted by a
corpus author.

When a source exposes only a publication date:

1. represent `published_at` as `23:59:59` on that local date;
2. find the latest date stated by the extracted current revision;
3. set `available_at` to local midnight after the later date;
4. label the precision `DATE_ONLY_CONSERVATIVE_NEXT_DAY`;
5. never infer an earlier time from search-engine crawl metadata;
6. retain `retrieved_at`, revision notes, extracted-fact digest, and source URL.

An archived, timestamped historical copy may later replace this conservative
availability, but it must be a new revision and must not rewrite an existing
corpus record.

## Corpus selection policy

[`corpus_v1.json`](../tests/fixtures/historical_replay/corpus_v1.json) freezes
the inclusion and exclusion criteria separately from scenario outcomes.
Included scenarios require authoritative timestamped or dated sources, three cutoffs, an
isolated reveal, controlled synthetic enterprise state, and a deterministic
paired A303 comparison. Scenarios are excluded when availability cannot be
bounded, entity-level enterprise data is required, a cutoff is future-dated,
reveals cannot be isolated, or operational mutation is required.

Scenario profiles use the generic `exposed_to_disruption_node` field. This
replaces the Baltimore-specific `exposed_to_port` name without changing the
controlled-synthetic or aggregate-only boundary.

The declared scenario severity must equal the strongest evidence visible by
the final decision cutoff. A corpus author cannot label MEDIUM evidence as HIGH
to manufacture an A303 attribution or downgrade HIGH evidence to improve
coverage counts.

## Replay behavior

[`run_historical_replay.py`](../ops/run_historical_replay.py) validates and
runs one scenario. [`run_historical_replay_corpus.py`](../ops/run_historical_replay_corpus.py)
validates membership, runs every scenario, preserves scenario-level reports,
summarizes coverage, and evaluates benchmark gates.

```text
A303 OFF -> versioned MONITOR baseline
A303 ON  -> RISK_MITIGATION only when eligible public disruption evidence
            and controlled synthetic exposure jointly create HIGH route risk
```

Run locally:

```bash
python ops/run_historical_replay_corpus.py \
  tests/fixtures/historical_replay/corpus_v1.json
```

## Benchmark gate

The manifest requires at least 10 scenarios, four disruption types, three
regions, two transport modes, two severity bands, and three independent
blinded reviews per variant. The current pilot passes every structural coverage
requirement except scenario count. It has no independent reviews, so the runner
still returns `eligible=false` and `status=NOT_MET`.

Decision Quality and Business Outcome Effect remain `NOT_EVALUATED`.
Historical reveals do not identify the counterfactual result of an unchosen
action.

Before calling the corpus a benchmark:

- add at least five more scenarios, preferably including road coverage and
  another geography;
- freeze controlled enterprise-state generation separately from decision
  policy;
- collect genuinely independent blinded reviews;
- report scenario-level results and uncertainty rather than one aggregate win
  rate.
