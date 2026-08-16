import { integer, sqliteTable, text, uniqueIndex } from "drizzle-orm/sqlite-core";

export const reviewSessions = sqliteTable(
  "review_sessions",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    userId: text("user_id").notNull(),
    bundleId: text("bundle_id").notNull().default("bac46037f8e090ff9e4e2662"),
    bundleDigest: text("bundle_digest").notNull().default("dc380ea7934dd04b17a1e8aa2fbd0eab437de7888aa617d274476d225c3796d0"),
    reviewerRef: text("reviewer_ref").notNull(),
    locale: text("locale").notNull().default("zh"),
    translationVersion: text("translation_version").notNull(),
    independentAttested: integer("independent_attested", { mode: "boolean" }).notNull(),
    noConflictAttested: integer("no_conflict_attested", { mode: "boolean" }).notNull(),
    noBlindKeyAttested: integer("no_blind_key_attested", { mode: "boolean" }).notNull(),
    status: text("status").notNull().default("DRAFT"),
    currentIndex: integer("current_index").notNull().default(0),
    createdAt: text("created_at").notNull(),
    updatedAt: text("updated_at").notNull(),
    submittedAt: text("submitted_at"),
  },
  (table) => [
    uniqueIndex("review_sessions_user_bundle_unique").on(table.userId, table.bundleId),
  ],
);

export const reviewAnswers = sqliteTable(
  "review_answers",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    sessionId: integer("session_id").notNull(),
    reviewId: text("review_id").notNull(),
    packageDigest: text("package_digest").notNull(),
    optionAScores: text("option_a_scores").notNull(),
    optionBScores: text("option_b_scores").notNull(),
    preferred: text("preferred"),
    confidence: integer("confidence"),
    notes: text("notes").notNull().default(""),
    isFinal: integer("is_final", { mode: "boolean" }).notNull().default(false),
    updatedAt: text("updated_at").notNull(),
  },
  (table) => [
    uniqueIndex("review_answers_session_review_unique").on(
      table.sessionId,
      table.reviewId,
    ),
  ],
);

export const storyReviewSessions = sqliteTable(
  "story_review_sessions",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    userId: text("user_id").notNull(),
    bundleId: text("bundle_id").notNull(),
    bundleDigest: text("bundle_digest").notNull(),
    collectionVersion: text("collection_version").notNull().default("human-evaluation-story.v1"),
    reviewerRef: text("reviewer_ref").notNull(),
    locale: text("locale").notNull().default("zh"),
    translationVersion: text("translation_version").notNull(),
    independentAttested: integer("independent_attested", { mode: "boolean" }).notNull(),
    noConflictAttested: integer("no_conflict_attested", { mode: "boolean" }).notNull(),
    noBlindKeyAttested: integer("no_blind_key_attested", { mode: "boolean" }).notNull(),
    status: text("status").notNull().default("DRAFT"),
    currentIndex: integer("current_index").notNull().default(0),
    createdAt: text("created_at").notNull(),
    updatedAt: text("updated_at").notNull(),
    submittedAt: text("submitted_at"),
  },
  (table) => [
    uniqueIndex("story_review_sessions_user_bundle_collection_unique").on(
      table.userId,
      table.bundleId,
      table.collectionVersion,
    ),
  ],
);

export const storyReviewAnswers = sqliteTable(
  "story_review_answers",
  {
    id: integer("id").primaryKey({ autoIncrement: true }),
    sessionId: integer("session_id").notNull(),
    reviewId: text("review_id").notNull(),
    packageDigest: text("package_digest").notNull(),
    comparativeJudgments: text("comparative_judgments").notNull(),
    preferred: text("preferred").notNull(),
    confidence: integer("confidence").notNull(),
    notes: text("notes").notNull().default(""),
    isFinal: integer("is_final", { mode: "boolean" }).notNull().default(false),
    committedAt: text("committed_at").notNull(),
    updatedAt: text("updated_at").notNull(),
  },
  (table) => [
    uniqueIndex("story_review_answers_session_review_unique").on(
      table.sessionId,
      table.reviewId,
    ),
  ],
);

export const loginAttempts = sqliteTable("login_attempts", {
  attemptKey: text("attempt_key").primaryKey(),
  failedCount: integer("failed_count").notNull().default(0),
  windowStartedAt: text("window_started_at").notNull(),
  lockedUntil: text("locked_until"),
  updatedAt: text("updated_at").notNull(),
});
