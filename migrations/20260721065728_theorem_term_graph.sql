-- Create "terms" table
CREATE TABLE "public"."terms" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "formal_system_id" uuid NOT NULL, "kind" character varying(16) NOT NULL, "constructor" character varying(512) NULL, "literal" character varying(512) NULL, "sort" character varying(128) NULL, "var_name" character varying(128) NULL, "bound_index" integer NULL, "digest" character varying(64) NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "fk_terms_formal_system_id_formal_systems" FOREIGN KEY ("formal_system_id") REFERENCES "public"."formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_terms_formal_system_id" to table: "terms"
CREATE INDEX "ix_terms_formal_system_id" ON "public"."terms" ("formal_system_id");
-- Create index "ix_terms_literal" to table: "terms"
CREATE INDEX "ix_terms_literal" ON "public"."terms" ("literal");
-- Create index "ix_terms_system_constructor" to table: "terms"
CREATE INDEX "ix_terms_system_constructor" ON "public"."terms" ("formal_system_id", "constructor");
-- Create index "uq_terms_system_digest" to table: "terms"
CREATE UNIQUE INDEX "uq_terms_system_digest" ON "public"."terms" ("formal_system_id", "digest");
-- Create "term_children" table
CREATE TABLE "public"."term_children" ("parent_id" uuid NOT NULL, "slot" character varying(128) NOT NULL, "position" integer NOT NULL DEFAULT 0, "child_id" uuid NOT NULL, PRIMARY KEY ("parent_id", "slot"), CONSTRAINT "fk_term_children_child_id_terms" FOREIGN KEY ("child_id") REFERENCES "public"."terms" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION, CONSTRAINT "fk_term_children_parent_id_terms" FOREIGN KEY ("parent_id") REFERENCES "public"."terms" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_term_children_child_id" to table: "term_children"
CREATE INDEX "ix_term_children_child_id" ON "public"."term_children" ("child_id");
-- Modify "theorems" table: structural search moves from the JSONB `pattern`
-- blob to the term graph above. Dropping `pattern` is safe — no code path has
-- ever written to `theorems`, so the column is NULL everywhere it exists.
-- atlas:nolint destructive
ALTER TABLE "public"."theorems" DROP COLUMN "pattern", ADD COLUMN "statement_term_id" uuid NULL, ADD CONSTRAINT "fk_theorems_statement_term_id_terms" FOREIGN KEY ("statement_term_id") REFERENCES "public"."terms" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION;
-- Create index "ix_theorems_statement_term_id" to table: "theorems"
CREATE INDEX "ix_theorems_statement_term_id" ON "public"."theorems" ("statement_term_id");
