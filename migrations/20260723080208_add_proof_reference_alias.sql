-- Modify "proof_references" table
ALTER TABLE "proof_references" ADD COLUMN "alias" character varying(64) NOT NULL DEFAULT '', ADD COLUMN "position" integer NOT NULL DEFAULT 0;
-- Create index "uq_proof_references_proof_alias" to table: "proof_references"
CREATE UNIQUE INDEX "uq_proof_references_proof_alias" ON "proof_references" ("proof_id", "alias");
