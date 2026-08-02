-- Modify "definition_fresh" table
ALTER TABLE "definition_fresh" ADD COLUMN "term_id" uuid NULL, ADD CONSTRAINT "fk_definition_fresh_term_id_terms" FOREIGN KEY ("term_id") REFERENCES "terms" ("id") ON UPDATE NO ACTION ON DELETE SET NULL;
-- Create index "ix_definition_fresh_term_id" to table: "definition_fresh"
CREATE INDEX "ix_definition_fresh_term_id" ON "definition_fresh" ("term_id");
