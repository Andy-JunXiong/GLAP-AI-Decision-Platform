DROP INDEX `review_sessions_user_id_unique`;--> statement-breakpoint
ALTER TABLE `review_sessions` ADD `bundle_id` text DEFAULT 'bac46037f8e090ff9e4e2662' NOT NULL;--> statement-breakpoint
ALTER TABLE `review_sessions` ADD `bundle_digest` text DEFAULT 'dc380ea7934dd04b17a1e8aa2fbd0eab437de7888aa617d274476d225c3796d0' NOT NULL;--> statement-breakpoint
CREATE UNIQUE INDEX `review_sessions_user_bundle_unique` ON `review_sessions` (`user_id`,`bundle_id`);