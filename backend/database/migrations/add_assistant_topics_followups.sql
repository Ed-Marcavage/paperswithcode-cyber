-- Cyber assistant only; additive and safe to reapply after either story.
ALTER TABLE assistant_runs ADD COLUMN IF NOT EXISTS topic VARCHAR(100);
ALTER TABLE assistant_messages ADD COLUMN IF NOT EXISTS follow_ups JSON NOT NULL DEFAULT '[]';
