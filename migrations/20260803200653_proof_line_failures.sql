-- Modify "proof_lines" table
ALTER TABLE "proof_lines" ADD COLUMN "failure_code" character varying(32) NULL, ADD COLUMN "failure_detail" jsonb NULL;
-- Create index "ix_proof_lines_failure_code" to table: "proof_lines"
CREATE INDEX "ix_proof_lines_failure_code" ON "proof_lines" ("failure_code");
