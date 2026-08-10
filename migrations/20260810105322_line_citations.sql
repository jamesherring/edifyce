-- Modify "proofs" table
ALTER TABLE "proofs" ADD COLUMN "citations_stored" boolean NOT NULL DEFAULT false;
-- Modify "proof_lines" table
ALTER TABLE "proof_lines" ADD COLUMN "theorem_id" uuid NULL, ADD CONSTRAINT "fk_proof_lines_theorem_id_promoted_theorems" FOREIGN KEY ("theorem_id") REFERENCES "promoted_theorems" ("id") ON UPDATE NO ACTION ON DELETE SET NULL;
-- Create index "ix_proof_lines_theorem_id" to table: "proof_lines"
CREATE INDEX "ix_proof_lines_theorem_id" ON "proof_lines" ("theorem_id");
