-- Create "definition_fresh" table
CREATE TABLE "definition_fresh" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "definition_id" uuid NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  "var" character varying(64) NOT NULL,
  "symbol_id" uuid NOT NULL,
  CONSTRAINT "pk_definition_fresh" PRIMARY KEY ("id"),
  CONSTRAINT "fk_definition_fresh_definition_id_definitions" FOREIGN KEY ("definition_id") REFERENCES "definitions" ("id") ON UPDATE NO ACTION ON DELETE CASCADE,
  CONSTRAINT "fk_definition_fresh_symbol_id_symbols" FOREIGN KEY ("symbol_id") REFERENCES "symbols" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_definition_fresh_definition_id" to table: "definition_fresh"
CREATE INDEX "ix_definition_fresh_definition_id" ON "definition_fresh" ("definition_id");
-- Create index "ix_definition_fresh_symbol_id" to table: "definition_fresh"
CREATE INDEX "ix_definition_fresh_symbol_id" ON "definition_fresh" ("symbol_id");
