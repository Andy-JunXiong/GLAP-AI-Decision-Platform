import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  SYSTEM_EVIDENCE_SCHEMA_VERSION,
  validateSystemEvidenceSnapshot,
} from "../app/system-evidence-snapshot.ts";

const snapshotPath = new URL("../public/data/system-evidence-snapshot.json", import.meta.url);

async function snapshot() {
  return JSON.parse(await readFile(snapshotPath, "utf8"));
}

test("accepts the exact read-only repository architecture snapshot", async () => {
  const value = await snapshot();
  const validated = validateSystemEvidenceSnapshot(value, "2026-08-31");
  assert.equal(validated.schema_version, SYSTEM_EVIDENCE_SCHEMA_VERSION);
  assert.equal(validated.services.length, 6);
  assert.equal(validated.live_aws_inspection, false);
  assert.deepEqual(new Set(Object.values(validated.authority)), new Set([false]));
});

test("rejects future, live, writable, or staging-authority drift", async () => {
  const future = await snapshot();
  future.repository_as_of_date = "2026-09-01";
  assert.throws(() => validateSystemEvidenceSnapshot(future, "2026-08-31"), /SYSTEM_EVIDENCE_BOUNDARY_INVALID/);

  const live = await snapshot();
  live.live_aws_inspection = true;
  assert.throws(() => validateSystemEvidenceSnapshot(live, "2026-08-31"), /SYSTEM_EVIDENCE_BOUNDARY_INVALID/);

  const writable = await snapshot();
  writable.authority.aws_write = true;
  assert.throws(() => validateSystemEvidenceSnapshot(writable, "2026-08-31"), /SYSTEM_EVIDENCE_AUTHORITY_INVALID/);

  const staging = await snapshot();
  staging.staging_track.scheduler_present = true;
  assert.throws(() => validateSystemEvidenceSnapshot(staging, "2026-08-31"), /SYSTEM_EVIDENCE_STAGING_TRACK_INVALID/);
});

test("rejects reliability, service-order, and envelope drift", async () => {
  const reliability = await snapshot();
  reliability.reliability.quality_check_count = 9;
  assert.throws(() => validateSystemEvidenceSnapshot(reliability, "2026-08-31"), /SYSTEM_EVIDENCE_RELIABILITY_INVALID/);

  const services = await snapshot();
  services.services.reverse();
  assert.throws(() => validateSystemEvidenceSnapshot(services, "2026-08-31"), /SYSTEM_EVIDENCE_SERVICE_INVALID/);

  const envelope = await snapshot();
  envelope.private_identifier = "forbidden";
  assert.throws(() => validateSystemEvidenceSnapshot(envelope, "2026-08-31"), /SYSTEM_EVIDENCE_ENVELOPE_INVALID/);
});
