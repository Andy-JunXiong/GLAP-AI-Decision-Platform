import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { fileURLToPath } from "node:url";

import {
  SOURCE_SCHEMA_VERSION,
  buildSystemEvidenceSnapshot,
  generateSystemEvidenceSnapshot,
  serializeSystemEvidenceSnapshot,
} from "../scripts/build-system-evidence-snapshot.mjs";

const sourcePath = new URL("../contracts/system-evidence-source.v2.json", import.meta.url);
const outputPath = new URL("../public/data/system-evidence-snapshot.json", import.meta.url);

async function source() {
  return JSON.parse(await readFile(sourcePath, "utf8"));
}

test("deterministically generates the tracked public projection", async () => {
  const value = await source();
  assert.equal(value.schema_version, SOURCE_SCHEMA_VERSION);
  const generated = serializeSystemEvidenceSnapshot(buildSystemEvidenceSnapshot(value, "2026-08-31"));
  assert.equal(generated, await readFile(outputPath, "utf8"));
  assert.deepEqual(await generateSystemEvidenceSnapshot({ check: true, sydneyDate: "2026-08-31" }), {
    status: "verified",
    output: fileURLToPath(outputPath),
  });
});

test("rejects source-document and authority drift before projection", async () => {
  const documents = await source();
  documents.source_documents[0] = "../private/runtime.json";
  assert.throws(() => buildSystemEvidenceSnapshot(documents, "2026-08-31"), /SYSTEM_EVIDENCE_SOURCE_INVALID/);

  const authority = await source();
  authority.public_snapshot.authority.schedule_change = true;
  assert.throws(() => buildSystemEvidenceSnapshot(authority, "2026-08-31"), /SYSTEM_EVIDENCE_AUTHORITY_INVALID/);
});

test("rejects a source date after the Sydney validation boundary", async () => {
  const value = await source();
  value.public_snapshot.as_of_date = "2026-09-01";
  assert.throws(() => buildSystemEvidenceSnapshot(value, "2026-08-31"), /SYSTEM_EVIDENCE_BOUNDARY_INVALID/);
});
