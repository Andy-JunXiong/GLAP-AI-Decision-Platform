# Historical Replay Lab v0.9

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

The corpus now contains ten events, ten disruption types, eight regions,
four transport modes (OCEAN, AIR, RAIL, and ROAD), and two severity bands (HIGH and
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
| 2023 Gotthard road-tunnel closure | Road-tunnel infrastructure failure | Europe | No delta before the dated closure source is conservatively available; attributed delta at T1 and T2; reopening remains reveal-only |
| 2021 Ever Given grounding | Canal vessel grounding | North Africa | No delta before the dated response source is conservatively available; attributed delta at T1 and T2; refloating and restored traffic remain reveal-only |
| 2023 Cyclone Gabrielle | Extreme-weather road-network disruption | Oceania | No delta before the first exact-timestamp NZTA notice; attributed delta after Coromandel closures at T1 and Northland isolation at T2; partial reopening remains reveal-only |
| 2024 Singapore port congestion | Container-port congestion | Southeast Asia | No delta before the first MPA source is conservatively available; attributed delta after the two-to-three-day berth delay at T1 and during sustained capacity demand at T2; reduced wait time remains reveal-only |
| 2024 Rio Grande do Sul floods | Flood-damaged highway network | South America | No delta before the first exact-timestamp recovery bulletin; attributed delta after 40 full closures at T1 and while extensive restrictions continued at T2; the first BR-470 reopening remains reveal-only |

Across the corpus there are 30 decision cutoffs: sixteen with an attributed
A303 decision change and fourteen with no delta. These are scenario-level attribution
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

### Gotthard road-tunnel closure

- [FEDRO closure notice of 11 September 2023](https://www.news.admin.ch/de/nsb?id=97678)
- [FEDRO damaged-ceiling removal update of 12 September 2023](https://www.admin.ch/de/nsb?id=97707)
- [FEDRO reopening-decision update of 14 September 2023](https://www.admin.ch/de/nsb?id=97735)
- [FEDRO reopening notice of 15 September 2023](https://www.admin.ch/de/nsb?id=97750)

The first three dated notices freeze the continued closure and repair state at
successive cutoffs. The fourth states that the tunnel would reopen at 20:00 on
15 September and is isolated as a recovery reveal. Because the official pages
show dates rather than signed publication timestamps, each source becomes
eligible only at local midnight on the next day. This scenario adds ROAD and
Europe coverage without backdating the reopening fact.

### Ever Given grounding

- [SCA refloating-effort update of 26 March 2021](https://www.suezcanal.gov.eg/English/MediaCenter/News/Pages/navigation-26-03-2021.aspx)
- [SCA successful-refloating update of 29 March 2021](https://www.suezcanal.gov.eg/English/MediaCenter/News/Pages/nav_29-03-2021.aspx)
- [SCA restored-navigation update of 31 March 2021](https://www.suezcanal.gov.eg/English/MediaCenter/News/Pages/31-3-2021.aspx)

The first dated notice provides the decision-time HIGH grounding signal. The
final cutoff occurs during 29 March but, under the conservative date-only
policy, cannot see that day's refloating notice. Refloating and subsequent
full-capacity navigation are therefore isolated as factual recovery reveals.
This scenario adds North Africa and vessel-grounding coverage without treating
the recovery as information available earlier that day.

### Cyclone Gabrielle road-network disruption

- [NZTA Coromandel highway closures at 10:39 on 13 February 2023](https://nzta.govt.nz/media-releases/coromandel-highways-compromised-by-cyclone-gabrielle)
- [NZTA Northland network update at 19:44 on 14 February 2023](https://nzta.govt.nz/media-releases/northland-network-update)
- [NZTA Northland reopening update at 12:36 on 15 February 2023](https://nzta.govt.nz/media-releases/northland-network-begins-to-re-open)

The first two exact-timestamp notices freeze high-severity highway closures and
regional road-network isolation at successive decision cutoffs. The following
day's partial reopening update is isolated as a factual recovery reveal and
cannot influence those earlier recommendations. This scenario adds Oceania and
extreme-weather road-network coverage without inferring publication times.

### Singapore container-port congestion

- [MPA extended container-berth waiting-time statement of 30 May 2024](https://www.mpa.gov.sg/media-centre/details/in-response-to-media-queries-on--vessels--extended-waiting-times-for-berths-in-the-port-of-singapore)
- [MPA strong container-capacity demand statement of 8 June 2024](https://www.mpa.gov.sg/media-centre/details/continued-strong-growth-in-container-volumes)
- [MPA reduced berth-wait update of 4 September 2024](https://www.mpa.gov.sg/media-centre/details/mpa-to-permit-night-movement-of-line-towed-container-barges-at-pasir-panjang-terminal)

The first dated statement supplies the HIGH congestion signal through its
two-to-three-day average wait when immediate berthing was unavailable. The
second confirms that container-capacity demand remained strong; the first HIGH
signal remains visible at that cutoff. The later statement reports a reduction
to less than one day and is isolated as a factual recovery reveal. Because the
pages expose dates rather than signed timestamps, each source becomes eligible
only at local midnight on the following day. This scenario adds Southeast Asia
and container-port-congestion coverage.

### Rio Grande do Sul flood-damaged highways

- [Brazil Ministry of Transport highway bulletin updated at 20:06 on 17 May 2024](https://www.gov.br/transportes/pt-br/assuntos/noticias/2024/05/boletim-de-recuperacao-de-rodovias-federais-17-05-2024)
- [Brazil Ministry of Transport highway bulletin published at 18:57 on 24 May 2024](https://www.gov.br/transportes/pt-br/assuntos/noticias/2024/05/boletim-de-recuperacao-de-rodovias-federais-24-05-2024)
- [DNIT first BR-470 segment reopening at 18:15 on 22 June 2024](https://www.gov.br/dnit/pt-br/assuntos/noticias/dnit-libera-primeiro-segmento-bloqueado-da-br-470-rs-em-veranopolis)

The first exact-timestamp bulletin reports 40 fully closed federal-highway
sections and supplies the initial HIGH signal. The second reports that 11
sections remained fully closed and 23 remained partially closed, preserving
the HIGH disruption state at the final cutoff. DNIT's later reopening of the
first blocked BR-470 segment is isolated as a factual recovery reveal. The
first page's current-revision availability uses its displayed 20:06 update
time, not its earlier 20:01 publication time. This scenario adds South America
and flood-damaged-highway coverage.

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
blinded reviews per variant. The current corpus passes every structural coverage
requirement, including scenario count. The hosted story-v2 collection contains
two complete independent-review submissions, but the local runner has not been
given a governed export and the three-review minimum is not met. It therefore
still returns `eligible=false` and `status=NOT_MET`.

Decision Quality and Business Outcome Effect remain `NOT_EVALUATED`.
Historical reveals do not identify the counterfactual result of an unchosen
action.

## Frozen blinded-review handoff

The v0.9 corpus, all ten ordered scenario documents, and the Decision Quality
v1 rubric are content-addressed together with the v3 decision-option content
contract by
[`review_freeze_v3.json`](../tests/fixtures/historical_replay/review_freeze_v3.json).
The local
[`build_historical_replay_review_bundle.py`](../ops/build_historical_replay_review_bundle.py)
runner validates every digest and then deterministically creates one blinded
package for each of the 30 cutoffs. It creates the reviewer-safe bundle and the
study-owner-only blind-key bundle separately, and it excludes every reveal-only
source from decision evidence. Every case contains a point-in-time story,
decision pressure, difficulties, conditional downstream risks, and a fact
boundary. Every option contains cited reasoning, a targeted problem response,
immediate/short-term/long-term solution paths, expected benefits with
measurement signals, trade-offs, and an explicit proposal-only authority
boundary.

The v1 package format is superseded because its two generic rationale templates
did not make all five rubric dimensions assessable. V2 remains superseded
because its richer rule explanation still did not present a complete problem
story or solution-and-benefit chain. Preserved v1/v2 drafts are non-evidence
and cannot be combined with v3. The v3 repository-side freeze and handoff are
available in the authenticated v3 review infrastructure. Sites v8's numeric
questionnaire and Sites v9's technical story-v1 presentation are superseded and
ineligible. Sites v12 is the canary-verified formal story-v2 entry across all
ten cases and 30 moments; the five-case preview remains a development-only
browser-local artifact. Seven pseudonymous reviewer accounts isolate hosted
sessions and answers. The database contains two complete story-v2 submissions
and one isolated three-answer story-v1 draft; all six additional accounts'
zero-write canaries created no review data. The two complete
submissions do not satisfy the three-review minimum, reviewer independence
still depends on truthful human attestation and study-owner enforcement, and
benchmark status remains `NOT_MET`.

Before calling the corpus a benchmark:

- preserve the frozen scenario, rubric, and v3 option-contract digests
  throughout review collection;
- freeze controlled enterprise-state generation separately from decision
  policy;
- collect genuinely independent blinded reviews;
- report scenario-level results and uncertainty rather than one aggregate win
  rate.
