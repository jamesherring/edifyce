-- Modify "promoted_theorems" table
-- IF NOT EXISTS: this migration was first authored as 20260808121751, which
-- landed on develop out of order and was renamed to this later version so it
-- applies after the formalization-record migration already on the develop
-- database. A long-lived database that applied the earlier version already has
-- this column, so the add must be a no-op there while still creating it where
-- the earlier version never ran (the Neon develop/main databases).
ALTER TABLE "promoted_theorems" ADD COLUMN IF NOT EXISTS "conclusion_fingerprint" text NULL;
