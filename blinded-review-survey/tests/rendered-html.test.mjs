import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

test("builds the bilingual review shell", async () => {
  const [page, client, translations, packageJson] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/SurveyClient.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/translations.ts", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
  ]);
  assert.match(page, /GLAP Independent Blinded Review/);
  assert.match(client, /GLAP Human Evaluation/);
  assert.match(client, /Formal review · story mode · submits/);
  assert.match(translations, /中文/);
  assert.match(translations, /English/);
  assert.doesNotMatch(`${page}\n${client}\n${translations}\n${packageJson}`, /Your site is taking shape|react-loading-skeleton/);
});

test("routes Human Evaluation through the formal authenticated v3 client", async () => {
  const [route, client] = await Promise.all([
    readFile(new URL("../app/pilot/human-evaluation/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/SurveyClient.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(route, /SurveyClient/);
  assert.doesNotMatch(route, /BaltimorePilot/);
  assert.match(route, /Formal Review/);
  assert.match(client, /\/api\/auth\/login/);
  assert.match(client, /api\(\{ action: "save"/);
  assert.match(client, /api\(\{ action: "submit" \}\)/);
  assert.match(client, /attestations/);
});

test("ships the exact reviewer-safe frozen bundle without an owner key", async () => {
  const bundle = JSON.parse(await readFile(new URL("../data/review-bundle.json", import.meta.url), "utf8"));
  assert.equal(bundle.schema_version, "historical-replay-review-bundle.v3");
  assert.equal(bundle.bundle_id, "35397ba1fb3d15d87ad7c071");
  assert.equal(bundle.bundle_digest, "60ebd29e920a489c3c171d1daf27b6fe85efbc884e77d2763b64b7b6a14d3cdb");
  assert.equal(bundle.decision_option_contract_version, "decision-option-contract.v3");
  assert.equal(bundle.package_count, 30);
  assert.equal(bundle.packages.length, 30);
  const source = JSON.stringify(bundle);
  assert.doesNotMatch(source, /BASELINE|CHALLENGER|key_bundle|variant_id/);
  const files = (await readdir(new URL("../data/", import.meta.url), { recursive: true })).map(String);
  assert.equal(files.some((name) => /owner-key|key-bundle/i.test(name)), false);
  const visibleFields = ["recommendation", "priority", "human_review_required", "rationale"];
  const identicalControls = bundle.packages.filter(({ options }) =>
    visibleFields.every((field) => options[0][field] === options[1][field])
      && JSON.stringify(options[0].content) === JSON.stringify(options[1].content));
  assert.equal(identicalControls.length, 14);
});

test("renders story-complete v3 options instead of generic recommendation cards", async () => {
  const [bundle, storyClient, storyData, translations] = await Promise.all([
    readFile(new URL("../data/review-bundle.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../app/pilot/human-evaluation/FormalStoryReview.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/pilot/human-evaluation/formal-story-data.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/translations.ts", import.meta.url), "utf8"),
  ]);
  const richPayloads = new Set();
  for (const reviewPackage of bundle.packages) {
    const visibleEvidence = new Map(reviewPackage.scenario.visible_evidence.map((item) => [
      item.evidence_id,
      new Set(item.facts.map((fact) => fact.fact_id)),
    ]));
    for (const option of reviewPackage.options) {
      assert.equal(option.content.contract_version, "decision-option-contract.v3");
      assert.equal(option.content.action_plan.steps.length, 3);
      assert.ok(option.content.problem_response.difficulty_points.length >= 3);
      assert.deepEqual(Object.keys(option.content.solution_horizons), ["immediate", "short_term", "long_term"]);
      assert.ok(Object.values(option.content.intended_benefits).flat().every((item) => item.claim_status === "EXPECTED_NOT_OBSERVED"));
      assert.ok(option.content.tradeoffs_and_uncertainty.length >= 3);
      assert.equal(option.content.authority_boundary.proposal_only, true);
      for (const citation of option.content.decision_basis.evidence_citations) {
        assert.ok(visibleEvidence.has(citation.evidence_id));
        assert.ok(citation.fact_ids.every((factId) => visibleEvidence.get(citation.evidence_id).has(factId)));
      }
      richPayloads.add(JSON.stringify(option.content));
    }
  }
  assert.ok(richPayloads.size > 20);
  assert.match(storyData, /content_zh/);
  assert.match(storyData, /action_plan\.steps/);
  assert.match(storyData, /tradeoffs_and_uncertainty/);
  assert.match(storyClient, /Two executable choices/);
  assert.match(storyClient, /named-human approval/);
  assert.match(translations, /为什么这样判断/);
  assert.match(translations, /预期收益（尚未验证）/);
  assert.match(translations, /Trade-offs and uncertainty/);
});

test("explains the story, difficulties, and conditional impacts without treating the case label as evidence", async () => {
  const [bundle, storyData, storyClient, translations, serverTranslations] = await Promise.all([
    readFile(new URL("../data/review-bundle.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../app/pilot/human-evaluation/formal-story-data.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/pilot/human-evaluation/FormalStoryReview.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/translations.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/server-review-translations.ts", import.meta.url), "utf8"),
  ]);
  assert.equal(bundle.packages[0].scenario.cutoff_id, "T0_PRE_EVENT");
  assert.equal(bundle.packages[0].scenario.visible_evidence.length, 0);
  assert.match(storyData, /briefZh\.story_summary/);
  assert.match(storyData, /visible_evidence/);
  assert.match(storyClient, /What is newly known/);
  assert.match(storyClient, /Later facts are not shown early/);
  assert.match(translations, /如果不处理，可能影响什么/);
  assert.match(serverTranslations, /标题用于标识完整历史案例/);
  assert.match(bundle.packages[0].scenario.brief.story_summary, /pre-confirmation control point/);
  assert.match(translations, /glap-review-zh-v3/);
});

test("explains identical control options without revealing blinded identities", async () => {
  const [storyClient, storyData, translations, types] = await Promise.all([
    readFile(new URL("../app/pilot/human-evaluation/FormalStoryReview.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/pilot/human-evaluation/formal-story-data.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/translations.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/review-types.ts", import.meta.url), "utf8"),
  ]);
  assert.match(storyData, /source\.recommendation === "RISK_MITIGATION"/);
  assert.match(storyData, /optionText\(item, 0, profile\)/);
  assert.match(storyClient, /OPTION_A/);
  assert.match(translations, /冻结评审包中的对照样本/);
  assert.match(translations, /control sample in the frozen review package/);
  assert.match(types, /optionA\.recommendation === optionB\.recommendation/);
  assert.doesNotMatch(`${storyClient}\n${storyData}\n${translations}\n${types}`, /BASELINE|CHALLENGER|variant_id/);
});

test("keeps persisted identity and package fields server-derived", async () => {
  const [route, migration] = await Promise.all([
    readFile(new URL("../app/api/review/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../drizzle/0003_rapid_misty_knight.sql", import.meta.url), "utf8"),
  ]);
  assert.match(route, /reviewer-ops-01/);
  assert.match(route, /packageFor\(answer\.reviewId\)/);
  assert.match(route, /frozen\.package_digest !== answer\.packageDigest/);
  assert.match(route, /story_review_answers/);
  assert.match(route, /already committed and locked/);
  assert.match(route, /WHERE user_id = \? AND bundle_id = \? AND collection_version = \?/);
  assert.match(route, /reviewBundle\.bundle_id/);
  assert.match(migration, /story_review_sessions_user_bundle_collection_unique/);
  assert.match(migration, /comparative_judgments/);
  assert.match(migration, /committed_at/);
  const allFiles = (await readdir(new URL("../app/", import.meta.url), { recursive: true })).join("\n");
  assert.doesNotMatch(allFiles, /_sites-preview/);
});

test("requires the dedicated account and keeps frozen cases out of the public client", async () => {
  const [page, client, auth, loginRoute, reviewRoute] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/SurveyClient.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/account-auth.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/auth/login/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/review/route.ts", import.meta.url), "utf8"),
  ]);
  assert.doesNotMatch(page, /review-bundle/);
  assert.match(client, /\/api\/auth\/login/);
  assert.match(auth, /PBKDF2/);
  assert.match(auth, /HMAC/);
  assert.match(auth, /HttpOnly/);
  assert.match(auth, /SameSite=Strict/);
  assert.match(auth, /8 \* 60 \* 60/);
  assert.match(auth, /PBKDF2_ITERATIONS = 100000/);
  assert.match(loginRoute, /MAX_FAILURES = 5/);
  assert.match(loginRoute, /15 \* 60 \* 1000/);
  assert.match(reviewRoute, /export async function GET[\s\S]*requireReviewer\(request\)[\s\S]*attachStoryProfiles\(localizeReviewPackages\(reviewBundle\.packages\)\)/);

  const clientFiles = (await readdir(new URL("../dist/client/", import.meta.url), { recursive: true }))
    .filter((name) => /\.(?:css|html|js)$/u.test(String(name)));
  const clientSource = (await Promise.all(clientFiles.map((name) => readFile(new URL(String(name), new URL("../dist/client/", import.meta.url)), "utf8")))).join("\n");
  assert.doesNotMatch(clientSource, /Port of Baltimore access disruption after the Francis Scott Key Bridge collapse/);
  assert.doesNotMatch(clientSource, /USACE activated emergency operations/);
  assert.doesNotMatch(clientSource, /60ebd29e920a489c3c171d1daf27b6fe85efbc884e77d2763b64b7b6a14d3cdb/);
});

test("formal story mode contains ten distinct server-side case profiles and comparative judgments", async () => {
  const [profiles, storyClient, route, types] = await Promise.all([
    readFile(new URL("../lib/server-story-profiles.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/pilot/human-evaluation/FormalStoryReview.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/review/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/review-types.ts", import.meta.url), "utf8"),
  ]);
  assert.equal((profiles.match(/decisionLens:/g) ?? []).length, 10);
  assert.equal((profiles.match(/statuses:/g) ?? []).length, 10);
  assert.equal((profiles.match(/questions:/g) ?? []).length, 10);
  assert.equal((profiles.match(/regionLabel:/g) ?? []).length, 10);
  assert.equal((profiles.match(/disruptionLabel:/g) ?? []).length, 10);
  const profileIds = [...profiles.matchAll(/\n\s+id: "([a-z0-9-]+)"/g)].map((match) => match[1]);
  assert.equal(profileIds.length, 10);
  assert.equal(new Set(profileIds).size, 10);
  const decisionLenses = [...profiles.matchAll(/decisionLens: l\("[^"]+", "([^"]+)"\)/g)].map((match) => match[1]);
  assert.equal(decisionLenses.length, 10);
  assert.equal(new Set(decisionLenses).size, 10);
  for (const focus of ["scarce transit slots", "network-wide stop", "truck-capacity capture", "canal queueing", "berth congestion", "fragmented network"]) {
    assert.match(profiles, new RegExp(focus));
  }
  assert.match(storyClient, /DIMENSION_IDS\.map/);
  assert.match(storyClient, /Compare the two plans/);
  assert.match(storyClient, /10 distinct decision stories/i);
  assert.doesNotMatch(storyClient, /replaceAll\("_", " "\)/);
  assert.match(route, /human-evaluation-story\.v1/);
  assert.match(route, /decision-quality-comparative-review\.v1/);
  assert.match(route, /Earlier decision moments in this story must be committed first/);
  assert.match(route, /This decision moment is already committed and locked/);
  assert.match(route, /INSERT OR IGNORE INTO story_review_answers/);
  assert.match(types, /ComparativeJudgments/);
});
