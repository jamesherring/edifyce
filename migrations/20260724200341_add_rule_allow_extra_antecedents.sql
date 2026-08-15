-- Modify "rules" table
ALTER TABLE "rules" ADD COLUMN "allow_extra_antecedents" boolean NOT NULL DEFAULT false;
