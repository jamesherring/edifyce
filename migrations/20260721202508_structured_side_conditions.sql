-- Modify "definitions" table: the opaque proviso string is replaced by the
-- structured side_conditions tree below. Dropping it outright (no backfill) is
-- safe because the persistence layer is not yet populated — the deployed
-- database has no `definitions` rows — so no stored `where` clause is lost.
-- atlas:nolint destructive
ALTER TABLE "public"."definitions" DROP COLUMN "condition";
-- Create "side_conditions" table
CREATE TABLE "public"."side_conditions" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "definition_id" uuid NOT NULL, "parent_id" uuid NULL, "position" integer NOT NULL DEFAULT 0, "kind" character varying(16) NOT NULL, "left_name" character varying(128) NULL, "right_name" character varying(128) NULL, "sort_symbol_id" uuid NULL, CONSTRAINT "pk_side_conditions" PRIMARY KEY ("id"), CONSTRAINT "fk_side_conditions_definition_id_definitions" FOREIGN KEY ("definition_id") REFERENCES "public"."definitions" ("id") ON UPDATE NO ACTION ON DELETE CASCADE, CONSTRAINT "fk_side_conditions_parent_id_side_conditions" FOREIGN KEY ("parent_id") REFERENCES "public"."side_conditions" ("id") ON UPDATE NO ACTION ON DELETE CASCADE, CONSTRAINT "fk_side_conditions_sort_symbol_id_symbols" FOREIGN KEY ("sort_symbol_id") REFERENCES "public"."symbols" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_side_conditions_definition_id" to table: "side_conditions"
CREATE INDEX "ix_side_conditions_definition_id" ON "public"."side_conditions" ("definition_id");
-- Create index "ix_side_conditions_definition_kind" to table: "side_conditions"
CREATE INDEX "ix_side_conditions_definition_kind" ON "public"."side_conditions" ("definition_id", "kind");
-- Create index "ix_side_conditions_parent_id" to table: "side_conditions"
CREATE INDEX "ix_side_conditions_parent_id" ON "public"."side_conditions" ("parent_id");
-- Create index "ix_side_conditions_sort_symbol_id" to table: "side_conditions"
CREATE INDEX "ix_side_conditions_sort_symbol_id" ON "public"."side_conditions" ("sort_symbol_id");
-- Create index "uq_side_conditions_definition_root" to table: "side_conditions"
CREATE UNIQUE INDEX "uq_side_conditions_definition_root" ON "public"."side_conditions" ("definition_id") WHERE (parent_id IS NULL);
