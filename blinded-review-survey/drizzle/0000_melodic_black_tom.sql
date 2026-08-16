CREATE TABLE `review_answers` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`session_id` integer NOT NULL,
	`review_id` text NOT NULL,
	`package_digest` text NOT NULL,
	`option_a_scores` text NOT NULL,
	`option_b_scores` text NOT NULL,
	`preferred` text,
	`confidence` integer,
	`notes` text DEFAULT '' NOT NULL,
	`is_final` integer DEFAULT false NOT NULL,
	`updated_at` text NOT NULL
);
--> statement-breakpoint
CREATE UNIQUE INDEX `review_answers_session_review_unique` ON `review_answers` (`session_id`,`review_id`);--> statement-breakpoint
CREATE TABLE `review_sessions` (
	`id` integer PRIMARY KEY AUTOINCREMENT NOT NULL,
	`user_id` text NOT NULL,
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
CREATE UNIQUE INDEX `review_sessions_user_id_unique` ON `review_sessions` (`user_id`);