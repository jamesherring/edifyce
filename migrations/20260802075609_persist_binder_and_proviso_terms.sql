-- Modify "definition_fresh" table
ALTER TABLE "definition_fresh" ADD COLUMN "term_id" uuid NULL, ADD CONSTRAINT "fk_definition_fresh_term_id_terms" FOREIGN KEY ("term_id") REFERENCES "terms" ("id") ON UPDATE NO ACTION ON DELETE SET NULL;
-- Create index "ix_definition_fresh_term_id" to table: "definition_fresh"
CREATE INDEX "ix_definition_fresh_term_id" ON "definition_fresh" ("term_id");
-- Modify "side_conditions" table
ALTER TABLE "side_conditions" ADD COLUMN "term_digest" character varying(64) NULL, ADD COLUMN "left_term_id" uuid NULL, ADD COLUMN "right_term_id" uuid NULL, ADD CONSTRAINT "fk_side_conditions_left_term_id_terms" FOREIGN KEY ("left_term_id") REFERENCES "terms" ("id") ON UPDATE NO ACTION ON DELETE SET NULL, ADD CONSTRAINT "fk_side_conditions_right_term_id_terms" FOREIGN KEY ("right_term_id") REFERENCES "terms" ("id") ON UPDATE NO ACTION ON DELETE SET NULL;
-- Create index "ix_side_conditions_left_term_id" to table: "side_conditions"
CREATE INDEX "ix_side_conditions_left_term_id" ON "side_conditions" ("left_term_id");
-- Create index "ix_side_conditions_right_term_id" to table: "side_conditions"
CREATE INDEX "ix_side_conditions_right_term_id" ON "side_conditions" ("right_term_id");
