-- Modify "rule_antecedents" table
ALTER TABLE "rule_antecedents" ADD COLUMN "term_id" uuid NULL, ADD CONSTRAINT "fk_rule_antecedents_term_id_terms" FOREIGN KEY ("term_id") REFERENCES "terms" ("id") ON UPDATE NO ACTION ON DELETE SET NULL;
-- Create index "ix_rule_antecedents_term_id" to table: "rule_antecedents"
CREATE INDEX "ix_rule_antecedents_term_id" ON "rule_antecedents" ("term_id");
-- Modify "rules" table
ALTER TABLE "rules" ADD COLUMN "schema_digest" character varying(64) NULL, ADD COLUMN "deduction_term_id" uuid NULL, ADD COLUMN "subproof_derive_term_id" uuid NULL, ADD COLUMN "subproof_assume_term_id" uuid NULL, ADD COLUMN "subproof_fresh_term_id" uuid NULL, ADD CONSTRAINT "fk_rules_deduction_term_id_terms" FOREIGN KEY ("deduction_term_id") REFERENCES "terms" ("id") ON UPDATE NO ACTION ON DELETE SET NULL, ADD CONSTRAINT "fk_rules_subproof_assume_term_id_terms" FOREIGN KEY ("subproof_assume_term_id") REFERENCES "terms" ("id") ON UPDATE NO ACTION ON DELETE SET NULL, ADD CONSTRAINT "fk_rules_subproof_derive_term_id_terms" FOREIGN KEY ("subproof_derive_term_id") REFERENCES "terms" ("id") ON UPDATE NO ACTION ON DELETE SET NULL, ADD CONSTRAINT "fk_rules_subproof_fresh_term_id_terms" FOREIGN KEY ("subproof_fresh_term_id") REFERENCES "terms" ("id") ON UPDATE NO ACTION ON DELETE SET NULL;
-- Create index "ix_rules_deduction_term_id" to table: "rules"
CREATE INDEX "ix_rules_deduction_term_id" ON "rules" ("deduction_term_id");
-- Create index "ix_rules_subproof_assume_term_id" to table: "rules"
CREATE INDEX "ix_rules_subproof_assume_term_id" ON "rules" ("subproof_assume_term_id");
-- Create index "ix_rules_subproof_derive_term_id" to table: "rules"
CREATE INDEX "ix_rules_subproof_derive_term_id" ON "rules" ("subproof_derive_term_id");
-- Create index "ix_rules_subproof_fresh_term_id" to table: "rules"
CREATE INDEX "ix_rules_subproof_fresh_term_id" ON "rules" ("subproof_fresh_term_id");
