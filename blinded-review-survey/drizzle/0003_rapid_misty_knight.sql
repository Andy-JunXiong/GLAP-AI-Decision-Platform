CREATE TABLE `story_review_answers` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`session_id` integer NOT NULL,
	`review_id` text NOT NULL,
	`package_digest` text NOT NULL,
	`comparative_judgments` text NOT NULL,
	`preferred` text NOT NULL,
	`confidence` integer NOT NULL,
	`notes` text DEFAULT '' NOT NULL,
	`is_final` integer DEFAULT false NOT NULL,
	`committed_at` text NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `story_review_answers_session_review_unique` ON `story_review_answers` (`session_id`,`review_id`);--> statement-breakpoint
CREATE TABLE `story_review_sessions` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`user_id` text NOT NULL,
	`bundle_id` text NOT NULL,
	`bundle_digest` text NOT NULL,
	`collection_version` text DEFAULT 'human-evaluation-story.v1' NOT NULL,
	`reviewer_ref` text NOT NULL,
	`locale` text DEFAULT 'zh' NOT NULL,
	`translation_version` text NOT NULL,
	`independent_attested` integer NOT NULL,
	`no_conflict_attested` integer NOT NULL,
	`no_blind_key_attested` integer NOT NULL,
	`status` text DEFAULT 'DRAFT' NOT NULL,
	`current_index` integer DEFAULT 0 NOT NULL,
	`created_at` text NOT NULL,
	`updated_at` text NOT NULL,
	`submitted_at` text
);
--> statement-breakpoint
CREATE UNIQUE INDEX `story_review_sessions_user_bundle_collection_unique` ON `story_review_sessions` (`user_id`,`bundle_id`,`collection_version`);