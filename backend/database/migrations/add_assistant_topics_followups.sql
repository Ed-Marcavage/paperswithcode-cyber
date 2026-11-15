-- Cyber assistant only; additive and safe to reapply after either story.
ALTER TABLE assistant_runs ADD COLUMN IF NOT EXISTS topic VARCHAR(100);
