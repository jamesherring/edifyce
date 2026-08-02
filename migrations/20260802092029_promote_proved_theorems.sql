-- Create index "ix_proof_lines_rule" to table: "proof_lines"
CREATE INDEX "ix_proof_lines_rule" ON "proof_lines" ("rule");
-- Modify "promoted_theorems" table
ALTER TABLE "promoted_theorems" ADD COLUMN "proved_by_id" uuid NULL, ADD CONSTRAINT "fk_promoted_theorems_proved_by_id_proofs" FOREIGN KEY ("proved_by_id") REFERENCES "proofs" ("id") ON UPDATE NO ACTION ON DELETE CASCADE;
-- Create index "ix_promoted_theorems_proved_by_id" to table: "promoted_theorems"
CREATE INDEX "ix_promoted_theorems_proved_by_id" ON "promoted_theorems" ("proved_by_id");
