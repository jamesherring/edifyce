-- atlas:nolint
-- Intentional, coordinated remodel: the `sorts` and `productions` tables are
-- unified into a single `symbols` table, and every grammar reference becomes a
-- `symbol_id` foreign key. The DROP TABLE/COLUMN and NOT NULL `symbol_id` adds
-- that lint flags (DS102/DS103/MF103) are safe here — this schema is not yet
-- populated in any deployed environment, so they only ever touch empty tables.
-- Create "symbols" table
CREATE TABLE "public"."symbols" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "system_id" uuid NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  "name" character varying(128) NOT NULL,
  "kind" character varying(16) NOT NULL,
  "template" character varying(512) NULL,
  "regex" character varying(512) NULL,
  "member_of_union_id" uuid NULL,
  CONSTRAINT "pk_symbols" PRIMARY KEY ("id"),
  CONSTRAINT "fk_symbols_member_of_union_id_symbols" FOREIGN KEY ("member_of_union_id") REFERENCES "public"."symbols" ("id") ON UPDATE NO ACTION ON DELETE CASCADE,
  CONSTRAINT "fk_symbols_system_id_formal_systems" FOREIGN KEY ("system_id") REFERENCES "public"."formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_symbols_member_of_union_id" to table: "symbols"
CREATE INDEX "ix_symbols_member_of_union_id" ON "public"."symbols" ("member_of_union_id");
-- Create index "ix_symbols_name" to table: "symbols"
CREATE INDEX "ix_symbols_name" ON "public"."symbols" ("name");
-- Create index "ix_symbols_system_id" to table: "symbols"
CREATE INDEX "ix_symbols_system_id" ON "public"."symbols" ("system_id");
-- Create index "uq_symbols_system_name" to table: "symbols"
CREATE UNIQUE INDEX "uq_symbols_system_name" ON "public"."symbols" ("system_id", "name");
-- Modify "rule_bindings" table
ALTER TABLE "public"."rule_bindings" DROP COLUMN "sort", ADD COLUMN "symbol_id" uuid NOT NULL, ADD
 CONSTRAINT "fk_rule_bindings_symbol_id_symbols" FOREIGN KEY ("symbol_id") REFERENCES "public"."symbols" ("id") ON UPDATE NO ACTION ON DELETE CASCADE;
-- Create index "ix_rule_bindings_symbol_id" to table: "rule_bindings"
CREATE INDEX "ix_rule_bindings_symbol_id" ON "public"."rule_bindings" ("symbol_id");
-- Modify "axiom_bindings" table
ALTER TABLE "public"."axiom_bindings" DROP COLUMN "sort", ADD COLUMN "symbol_id" uuid NOT NULL, ADD
 CONSTRAINT "fk_axiom_bindings_symbol_id_symbols" FOREIGN KEY ("symbol_id") REFERENCES "public"."symbols" ("id") ON UPDATE NO ACTION ON DELETE CASCADE;
-- Create index "ix_axiom_bindings_symbol_id" to table: "axiom_bindings"
CREATE INDEX "ix_axiom_bindings_symbol_id" ON "public"."axiom_bindings" ("symbol_id");
-- Modify "definitions" table
ALTER TABLE "public"."definitions" DROP COLUMN "sort", ADD COLUMN "symbol_id" uuid NOT NULL, ADD
 CONSTRAINT "fk_definitions_symbol_id_symbols" FOREIGN KEY ("symbol_id") REFERENCES "public"."symbols" ("id") ON UPDATE NO ACTION ON DELETE CASCADE;
-- Create index "ix_definitions_symbol_id" to table: "definitions"
CREATE INDEX "ix_definitions_symbol_id" ON "public"."definitions" ("symbol_id");
-- Modify "production_bindings" table
ALTER TABLE "public"."production_bindings" DROP CONSTRAINT "fk_production_bindings_production_id_productions", DROP COLUMN "sort", ADD COLUMN "symbol_id" uuid NOT NULL, ADD
 CONSTRAINT "fk_production_bindings_production_id_symbols" FOREIGN KEY ("production_id") REFERENCES "public"."symbols" ("id") ON UPDATE NO ACTION ON DELETE CASCADE, ADD
 CONSTRAINT "fk_production_bindings_symbol_id_symbols" FOREIGN KEY ("symbol_id") REFERENCES "public"."symbols" ("id") ON UPDATE NO ACTION ON DELETE CASCADE;
-- Create index "ix_production_bindings_symbol_id" to table: "production_bindings"
CREATE INDEX "ix_production_bindings_symbol_id" ON "public"."production_bindings" ("symbol_id");
-- Modify "definition_bindings" table
ALTER TABLE "public"."definition_bindings" DROP COLUMN "sort", ADD COLUMN "symbol_id" uuid NOT NULL, ADD
 CONSTRAINT "fk_definition_bindings_symbol_id_symbols" FOREIGN KEY ("symbol_id") REFERENCES "public"."symbols" ("id") ON UPDATE NO ACTION ON DELETE CASCADE;
-- Create index "ix_definition_bindings_symbol_id" to table: "definition_bindings"
CREATE INDEX "ix_definition_bindings_symbol_id" ON "public"."definition_bindings" ("symbol_id");
-- Modify "line_types" table
ALTER TABLE "public"."line_types" DROP COLUMN "logical_sort", ADD COLUMN "logical_symbol_id" uuid NULL, ADD
 CONSTRAINT "fk_line_types_logical_symbol_id_symbols" FOREIGN KEY ("logical_symbol_id") REFERENCES "public"."symbols" ("id") ON UPDATE NO ACTION ON DELETE CASCADE;
-- Create index "ix_line_types_logical_symbol_id" to table: "line_types"
CREATE INDEX "ix_line_types_logical_symbol_id" ON "public"."line_types" ("logical_symbol_id");
-- Drop "productions" table
DROP TABLE "public"."productions";
-- Drop "sorts" table
DROP TABLE "public"."sorts";
