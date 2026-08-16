import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import test from "node:test";
import { HERO_CASE_SOURCE_MANIFEST, IDENTICAL_PAIR_ALLOWLIST } from "./hero-case-source-manifest.mjs";

const { heroCases } = await import(new URL("../app/pilot/baltimore/hero-case-data.ts", import.meta.url));
const { timelineNodeView } = await import(new URL("../app/pilot/baltimore/hero-case-visibility.ts", import.meta.url));

const pilotSource = await readFile(new URL("../app/pilot/baltimore/BaltimorePilot.tsx", import.meta.url), "utf8");
const dataSource = await readFile(new URL("../app/pilot/baltimore/hero-case-data.ts", import.meta.url), "utf8");
const legacyRouteSource = await readFile(new URL("../app/pilot/baltimore/page.tsx", import.meta.url), "utf8");
const routeSource = await readFile(new URL("../app/pilot/human-evaluation/page.tsx", import.meta.url), "utf8");

test("formal Human Evaluation uses the authenticated survey while the legacy preview stays local-only", () => {
  assert.match(legacyRouteSource, /NODE_ENV !== "development"/);
  assert.match(legacyRouteSource, /notFound\(\)/);
  assert.match(routeSource, /SurveyClient/);
  assert.doesNotMatch(routeSource, /BaltimorePilot/);
  assert.match(routeSource, /Formal Review/);
  assert.match(pilotSource, /Experience preview/);
  assert.match(pilotSource, /no submission/);
  assert.match(pilotSource, /committed and saved locally/);
});

test("pilot contains five hero cases and fifteen decision moments", () => {
  const caseIds = [
    "baltimore-key-bridge",
    "panama-canal-drought",
    "red-sea-security",
    "faa-notam-outage",
    "cyclone-gabrielle-roads",
  ];
  for (const caseId of caseIds) assert.match(dataSource, new RegExp(`id: "${caseId}"`));
  assert.equal((dataSource.match(/mode: "(?:OCEAN|AIR|ROAD)"/g) ?? []).length, 5);
  assert.equal((dataSource.match(/moment: "T[012]"/g) ?? []).length, 15);
});

test("each hero case exercises a different decision mechanism", () => {
  assert.equal((dataSource.match(/decisionLens:/g) ?? []).length, 5);
  const distinctMechanics = [
    "Option value under uncertainty",
    "Allocating scarce capacity across customers",
    "Safety thresholds and route governance",
    "Recovery sequencing during a network incident",
    "The no-go boundary when no safe route exists",
  ];
  for (const mechanic of distinctMechanics) assert.match(dataSource, new RegExp(mechanic));

  assert.match(dataSource, /Allocate slots proportionally across customers/);
  assert.match(dataSource, /Trigger a company-wide Red Sea suspension/);
  assert.match(dataSource, /Create one cross-carrier recovery sequence/);
  assert.match(dataSource, /Keep the no-go absolute/);
});

test("the generic backup-versus-wait template is confined to Baltimore", () => {
  const postBaltimore = dataSource.slice(dataSource.indexOf('id: "panama-canal-drought"'));
  assert.equal(postBaltimore.includes("准备备选运输方案"), false);
  assert.equal(postBaltimore.includes("Prepare backup transport now"), false);
  assert.equal(postBaltimore.includes("继续等待恢复时间明确"), false);
});

test("every pilot stage maps to the exact frozen package position", async () => {
  const bundle = JSON.parse(await readFile(new URL("../data/review-bundle.json", import.meta.url), "utf8"));
  const packages = new Map(bundle.packages.map((item) => [item.review_id, item]));
  assert.equal(HERO_CASE_SOURCE_MANIFEST.length, 15);
  assert.equal(IDENTICAL_PAIR_ALLOWLIST.size, 7);

  for (const mapping of HERO_CASE_SOURCE_MANIFEST) {
    const frozen = packages.get(mapping.reviewId);
    assert.ok(frozen, mapping.reviewId);
    assert.equal(frozen.scenario.cutoff_id, mapping.cutoff);
    assert.deepEqual(frozen.options.map((option) => option.recommendation), mapping.recommendations);

    const [frozenA, frozenB] = frozen.options;
    const frozenIdentical = ["recommendation", "priority", "human_review_required", "rationale"].every(
      (field) => frozenA[field] === frozenB[field],
    ) && JSON.stringify(frozenA.content) === JSON.stringify(frozenB.content);
    assert.equal(frozenIdentical, mapping.identical, mapping.reviewId);
    assert.equal(IDENTICAL_PAIR_ALLOWLIST.has(mapping.reviewId), mapping.identical, mapping.reviewId);

    const heroCase = heroCases.find((item) => item.id === mapping.caseId);
    const stage = heroCase?.stages.find((item) => item.moment === mapping.moment);
    assert.ok(stage, `${mapping.caseId}:${mapping.moment}`);
    const visibleOption = ({ title, body, tradeoff }) => ({ title, body, tradeoff });
    const pilotIdentical = JSON.stringify(visibleOption(stage.options[0])) === JSON.stringify(visibleOption(stage.options[1]));
    assert.equal(pilotIdentical, mapping.identical, `${mapping.caseId}:${mapping.moment}`);

    if (!mapping.identical) assert.notEqual(mapping.recommendations[0], mapping.recommendations[1]);
  }
});

test("T0 timeline HTML contains no future result semantics", () => {
  for (const heroCase of heroCases) {
    const views = heroCase.stages.map((stage, index) => timelineNodeView(stage, index, -1, "zh"));
    const html = renderToStaticMarkup(createElement("nav", null, views.map((view) =>
      createElement("button", { key: view.moment, disabled: view.disabled, "aria-label": view.ariaLabel },
        view.moment,
        view.status && createElement("strong", null, view.status),
        view.date && createElement("small", null, view.date),
      ),
    )));

    assert.match(html, new RegExp(heroCase.stages[0].status.zh));
    assert.match(html, new RegExp(heroCase.stages[0].date.zh));
    for (const future of heroCase.stages.slice(1)) {
      assert.equal(html.includes(future.status.zh), false, `${heroCase.id}:${future.moment}:status`);
      assert.equal(html.includes(future.date.zh), false, `${heroCase.id}:${future.moment}:date`);
    }
    assert.equal(views[1].disabled, true);
    assert.equal(views[2].disabled, true);
    assert.equal(views[1].ariaLabel, "T1 · 未解锁");
  }
});

test("timeline unlocks strictly in order and past judgments become read-only", () => {
  const stages = heroCases[0].stages;
  const afterT0 = stages.map((stage, index) => timelineNodeView(stage, index, 0, "en"));
  assert.equal(afterT0[0].isPast, true);
  assert.equal(afterT0[1].isCurrent, true);
  assert.equal(afterT0[1].disabled, false);
  assert.equal(afterT0[2].disabled, true);

  const afterT1 = stages.map((stage, index) => timelineNodeView(stage, index, 1, "en"));
  assert.equal(afterT1[0].isPast, true);
  assert.equal(afterT1[1].isPast, true);
  assert.equal(afterT1[2].isCurrent, true);
  assert.equal(afterT1[2].disabled, false);

  assert.match(pilotSource, /if \(viewingPast\) return/);
  assert.match(pilotSource, /disabled=\{viewingPast\}/);
  assert.match(pilotSource, /commitCurrentStage/);
  assert.equal(pilotSource.includes('"修改" : "Edit"'), false);
});

test("the frozen operational timeline is represented in business copy", () => {
  for (const date of ["26 March 2024", "31 March 2024", "5 April 2024", "31 October 2023", "5 January 2024", "11 January 2023", "14 February 2023"]) {
    assert.match(dataSource, new RegExp(date));
  }
  assert.match(dataSource, /18 per day/);
  assert.match(dataSource, /at least 18 shipping companies/i);
  assert.match(dataSource, /nationwide ground stop/i);
  assert.match(dataSource, /no heavy-vehicle detour/i);
});

test("pilot avoids leading the reviewer toward a tie", () => {
  const combined = pilotSource + dataSource;
  assert.equal(combined.includes("无差异时点"), false);
  assert.equal(combined.includes("no-difference moment"), false);
  assert.equal(combined.includes("可以选择“相当”"), false);
});

test("human-facing copy uses operational language instead of schema labels", () => {
  assert.match(dataSource, /计划路线/);
  assert.match(dataSource, /库存缓冲/);
  assert.match(dataSource, /客户优先级/);
  assert.match(dataSource, /备选运输/);
  assert.equal(dataSource.includes("中断节点暴露"), false);
  assert.equal(dataSource.includes("SLA 关键度"), false);
});

test("human-facing copy excludes harness identity and schema vocabulary", () => {
  const combined = (pilotSource + dataSource).toLowerCase();
  const forbidden = ["source_id", "fact_type", "cutoff_id", "capability flag", "a303", "baseline", "challenger", "rule trace", "package_digest", "provenance"];
  for (const token of forbidden) assert.equal(combined.includes(token), false, token);
});

test("development-only pilot does not call the official review persistence API", () => {
  assert.equal(pilotSource.includes("/api/review"), false);
  assert.equal(pilotSource.includes("fetch("), false);
  assert.equal(pilotSource.includes("onSubmit"), false);
});

test("pilot persists per-case progress locally and migrates the Baltimore draft", () => {
  assert.match(pilotSource, /glap:human-evaluation-pilot:v3/);
  assert.match(pilotSource, /glap:human-evaluation-pilot:v2/);
  assert.match(pilotSource, /glap:baltimore-human-evaluation-pilot:v1/);
  assert.match(pilotSource, /window\.localStorage\.getItem\(STORAGE_KEY\)/);
  assert.match(pilotSource, /window\.localStorage\.setItem\(STORAGE_KEY/);
  assert.match(pilotSource, /normalizeAnswers/);
  assert.match(pilotSource, /normalizeCommittedThrough/);
  assert.match(pilotSource, /normalizeLegacyAnswers/);
  assert.match(pilotSource, /不会计入 Decision Quality 证据/);
});

test("hub and case summary expose complete local progress", () => {
  assert.match(pilotSource, /completedCases/);
  assert.match(pilotSource, /totalComplete/);
  assert.match(pilotSource, /caseProgress/);
  assert.match(pilotSource, /resultGrid/);
  assert.match(pilotSource, /summaryLabels/);
  assert.match(pilotSource, /Clear all local results/);
});
