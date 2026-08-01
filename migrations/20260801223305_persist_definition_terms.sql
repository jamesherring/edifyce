-- Modify "definitions" table
ALTER TABLE "definitions" ADD COLUMN "term_digest" character varying(64) NULL, ADD COLUMN "higher_term_id" uuid NULL, ADD COLUMN "lower_term_id" uuid NULL, ADD CONSTRAINT "fk_definitions_higher_term_id_terms" FOREIGN KEY ("higher_term_id") REFERENCES "terms" ("id") ON UPDATE NO ACTION ON DELETE SET NULL, ADD CONSTRAINT "fk_definitions_lower_term_id_terms" FOREIGN KEY ("lower_term_id") REFERENCES "terms" ("id") ON UPDATE NO ACTION ON DELETE SET NULL;
-- Create index "ix_definitions_higher_term_id" to table: "definitions"
CREATE INDEX "ix_definitions_higher_term_id" ON "definitions" ("higher_term_id");
-- Create index "ix_definitions_lower_term_id" to table: "definitions"
CREATE INDEX "ix_definitions_lower_term_id" ON "definitions" ("lower_term_id");
