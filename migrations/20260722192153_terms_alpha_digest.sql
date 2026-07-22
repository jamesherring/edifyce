-- Modify "terms" table
ALTER TABLE "terms" ADD COLUMN "alpha_digest" character varying(64) NULL;
-- Create index "ix_terms_system_alpha_digest" to table: "terms"
CREATE INDEX "ix_terms_system_alpha_digest" ON "terms" ("formal_system_id", "alpha_digest");
