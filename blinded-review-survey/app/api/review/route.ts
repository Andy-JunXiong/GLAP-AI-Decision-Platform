import reviewBundle from "@/data/review-bundle.json";
import rubric from "@/data/rubric.json";
import { requireReviewer, sameOrigin } from "../../account-auth";
import { getD1 } from "@/db/runtime";
import { DIMENSION_IDS, type ComparativeJudgments, type Locale, type Preference, type StoryReviewAnswer } from "@/lib/review-types";
import { TRANSLATION_VERSION } from "@/lib/translations";
import { localizeReviewPackages } from "@/lib/server-review-translations";
import { attachStoryProfiles } from "@/lib/server-story-profiles";

export const dynamic = "force-dynamic";

type D1Row = Record<string, unknown>;
const COLLECTION_VERSION = "human-evaluation-story.v1";
const REVIEW_SCHEMA_VERSION = "decision-quality-comparative-review.v1";

function jsonError(message: string, status = 400) {
  return Response.json({ error: message }, { status });
}

function isChoice(value: unknown): value is Preference {
  return typeof value === "string" && ["OPTION_A", "OPTION_B", "TIE"].includes(value);
}

function validJudgments(value: unknown): value is ComparativeJudgments {
  if (!value || typeof value !== "object") return false;
  const judgments = value as Record<string, unknown>;
  return Object.keys(judgments).length === DIMENSION_IDS.length &&
    DIMENSION_IDS.every((id) => judgments[id] === null || isChoice(judgments[id]));
}

function validAnswer(value: unknown): value is StoryReviewAnswer {
  if (!value || typeof value !== "object") return false;
  const answer = value as Partial<StoryReviewAnswer>;
  return (
    typeof answer.reviewId === "string" &&
    typeof answer.packageDigest === "string" &&
    validJudgments(answer.judgments) &&
    (answer.preferred === null || isChoice(answer.preferred)) &&
    (answer.confidence === null || (Number.isInteger(answer.confidence) && Number(answer.confidence) >= 1 && Number(answer.confidence) <= 5)) &&
    typeof answer.notes === "string" &&
    answer.notes.length <= 1000
  );
}

function answerComplete(answer: StoryReviewAnswer) {
  return (
    DIMENSION_IDS.every((id) => isChoice(answer.judgments[id])) &&
    answer.preferred !== null &&
    answer.confidence !== null
  );
}

function packageFor(reviewId: string) {
  return reviewBundle.packages.find((item) => item.review_id === reviewId);
}

function precedingReviewIds(reviewId: string): string[] {
  const frozen = packageFor(reviewId);
  if (!frozen) return [];
  const disruptionType = frozen.scenario.scenario_profile.disruption_type;
  const story = reviewBundle.packages.filter(
    (item) => item.scenario.scenario_profile.disruption_type === disruptionType,
  );
  const position = story.findIndex((item) => item.review_id === reviewId);
  return story.slice(0, position).map((item) => item.review_id);
}

async function sessionFor(db: D1Database, userId: string) {
  return db.prepare("SELECT * FROM story_review_sessions WHERE user_id = ? AND bundle_id = ? AND collection_version = ? LIMIT 1")
    .bind(userId, reviewBundle.bundle_id, COLLECTION_VERSION)
    .first<D1Row>();
}

function deserializeAnswer(row: D1Row): StoryReviewAnswer {
  return {
    reviewId: String(row.review_id),
    packageDigest: String(row.package_digest),
    judgments: JSON.parse(String(row.comparative_judgments)) as ComparativeJudgments,
    preferred: String(row.preferred) as Preference,
    confidence: Number(row.confidence),
    notes: String(row.notes ?? ""),
  };
}

export async function GET(request: Request) {
  try {
    const reviewer = await requireReviewer(request);
    const db = getD1();
    const session = await sessionFor(db, reviewer.userId);
    const result = session
      ? await db.prepare("SELECT * FROM story_review_answers WHERE session_id = ? ORDER BY id").bind(session.id).all<D1Row>()
      : { results: [] as D1Row[] };
    return Response.json({
      bootstrap: {
        bundleId: reviewBundle.bundle_id,
        bundleDigest: reviewBundle.bundle_digest,
        collectionVersion: COLLECTION_VERSION,
        reviewSchemaVersion: REVIEW_SCHEMA_VERSION,
        packages: attachStoryProfiles(localizeReviewPackages(reviewBundle.packages)),
        dimensions: rubric.dimensions,
      },
      session: session ? {
        locale: session.locale,
        status: session.status,
        currentIndex: Number(session.current_index),
        submittedAt: session.submitted_at,
      } : null,
      answers: result.results.map(deserializeAnswer),
    }, { headers: { "cache-control": "no-store" } });
  } catch (error) {
    if (error instanceof Response) return error;
    return jsonError(error instanceof Error ? error.message : "Unable to load review", 500);
  }
}

export async function POST(request: Request) {
  try {
    if (!sameOrigin(request)) return jsonError("Request origin rejected", 403);
    const reviewer = await requireReviewer(request);
    const payload = (await request.json()) as Record<string, unknown>;
    const action = String(payload.action ?? "");
    const db = getD1();
    const now = new Date().toISOString();

    if (action === "start") {
      const locale: Locale = payload.locale === "en" ? "en" : "zh";
      const attestations = payload.attestations as Record<string, unknown> | undefined;
      if (attestations?.independent !== true || attestations?.noConflict !== true || attestations?.noBlindKey !== true) {
        return jsonError("All eligibility attestations are required");
      }
      const existing = await sessionFor(db, reviewer.userId);
      if (existing?.status === "SUBMITTED") return jsonError("Review is already submitted", 409);
      if (!existing) {
        await db.prepare(
          `INSERT INTO story_review_sessions
          (user_id, bundle_id, bundle_digest, collection_version, reviewer_ref, locale, translation_version, independent_attested,
           no_conflict_attested, no_blind_key_attested, status, current_index, created_at, updated_at)
          VALUES (?, ?, ?, ?, 'reviewer-ops-01', ?, ?, 1, 1, 1, 'DRAFT', 0, ?, ?)`,
        ).bind(
          reviewer.userId,
          reviewBundle.bundle_id,
          reviewBundle.bundle_digest,
          COLLECTION_VERSION,
          locale,
          TRANSLATION_VERSION,
          now,
          now,
        ).run();
      }
      return Response.json({ ok: true });
    }

    const session = await sessionFor(db, reviewer.userId);
    if (!session) return jsonError("Start the review first", 409);
    if (session.status === "SUBMITTED") return jsonError("Review is already submitted", 409);

    if (action === "save") {
      if (!validAnswer(payload.answer)) return jsonError("Answer does not match the review schema");
      const answer = payload.answer;
      const frozen = packageFor(answer.reviewId);
      if (!frozen || frozen.package_digest !== answer.packageDigest) return jsonError("Frozen review package identity mismatch");
      const locale: Locale = payload.locale === "en" ? "en" : "zh";
      if (!answerComplete(answer)) return jsonError("Complete every comparison, overall preference, and confidence before committing");
      const priorIds = precedingReviewIds(answer.reviewId);
      if (priorIds.length > 0) {
        const priorRows = await db.prepare("SELECT review_id FROM story_review_answers WHERE session_id = ?")
          .bind(session.id).all<{ review_id: string }>();
        const committedIds = new Set(priorRows.results.map((row) => row.review_id));
        if (!priorIds.every((reviewId) => committedIds.has(reviewId))) {
          return jsonError("Earlier decision moments in this story must be committed first", 409);
        }
      }
      const existing = await db.prepare("SELECT * FROM story_review_answers WHERE session_id = ? AND review_id = ? LIMIT 1")
        .bind(session.id, answer.reviewId).first<D1Row>();
      const normalized = { ...answer, notes: answer.notes.trim() };
      if (existing) {
        const committed = deserializeAnswer(existing);
        if (JSON.stringify(committed) !== JSON.stringify(normalized)) return jsonError("This decision moment is already committed and locked", 409);
      } else {
        await db.prepare(
          `INSERT OR IGNORE INTO story_review_answers
          (session_id, review_id, package_digest, comparative_judgments, preferred,
           confidence, notes, is_final, committed_at, updated_at)
          VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)`,
        ).bind(
          session.id, answer.reviewId, answer.packageDigest, JSON.stringify(answer.judgments),
          answer.preferred, answer.confidence, answer.notes.trim(), now, now,
        ).run();
        const committedRow = await db.prepare("SELECT * FROM story_review_answers WHERE session_id = ? AND review_id = ? LIMIT 1")
          .bind(session.id, answer.reviewId).first<D1Row>();
        if (!committedRow || JSON.stringify(deserializeAnswer(committedRow)) !== JSON.stringify(normalized)) {
          return jsonError("This decision moment is already committed and locked", 409);
        }
      }
      const savedRows = await db.prepare("SELECT COUNT(*) AS total FROM story_review_answers WHERE session_id = ?")
        .bind(session.id).first<{ total: number }>();
      await db.prepare("UPDATE story_review_sessions SET locale = ?, current_index = ?, updated_at = ? WHERE id = ?")
        .bind(locale, Number(savedRows?.total ?? 0), now, session.id).run();
      return Response.json({ ok: true, savedAt: now });
    }

    if (action === "submit") {
      const result = await db.prepare("SELECT * FROM story_review_answers WHERE session_id = ?").bind(session.id).all<D1Row>();
      const answers = result.results.map(deserializeAnswer);
      const expected = new Map(reviewBundle.packages.map((item) => [item.review_id, item.package_digest]));
      const complete = answers.length === reviewBundle.package_count &&
        answers.every((answer) => expected.get(answer.reviewId) === answer.packageDigest && answerComplete(answer));
      if (!complete) return jsonError("All 30 frozen review packages must be complete", 409);
      await db.batch([
        db.prepare("UPDATE story_review_answers SET is_final = 1, updated_at = ? WHERE session_id = ?").bind(now, session.id),
        db.prepare("UPDATE story_review_sessions SET status = 'SUBMITTED', current_index = 30, submitted_at = ?, updated_at = ? WHERE id = ? AND status = 'DRAFT'").bind(now, now, session.id),
      ]);
      return Response.json({ ok: true, submittedAt: now });
    }

    return jsonError("Unsupported action");
  } catch (error) {
    if (error instanceof Response) return error;
    return jsonError(error instanceof Error ? error.message : "Unable to update review", 500);
  }
}
