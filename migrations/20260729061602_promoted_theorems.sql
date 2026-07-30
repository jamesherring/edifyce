-- Create "promoted_theorems" table
CREATE TABLE "promoted_theorems" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "system_id" uuid NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  "label" character varying(128) NOT NULL,
  "statement" text NOT NULL,
  "primitive" boolean NOT NULL DEFAULT false,
  "matching" character varying(16) NOT NULL DEFAULT 'structural',
  "statement_term_id" uuid NULL,
  "schema_digest" character varying(64) NULL,
  CONSTRAINT "pk_promoted_theorems" PRIMARY KEY ("id"),
  CONSTRAINT "fk_promoted_theorems_statement_term_id_terms" FOREIGN KEY ("statement_term_id") REFERENCES "terms" ("id") ON UPDATE NO ACTION ON DELETE SET NULL,
  CONSTRAINT "fk_promoted_theorems_system_id_formal_systems" FOREIGN KEY ("system_id") REFERENCES "formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_promoted_theorems_label" to table: "promoted_theorems"
CREATE INDEX "ix_promoted_theorems_label" ON "promoted_theorems" ("label");
-- Create index "ix_promoted_theorems_statement_term_id" to table: "promoted_theorems"
CREATE INDEX "ix_promoted_theorems_statement_term_id" ON "promoted_theorems" ("statement_term_id");
-- Create index "ix_promoted_theorems_system_id" to table: "promoted_theorems"
CREATE INDEX "ix_promoted_theorems_system_id" ON "promoted_theorems" ("system_id");
-- Create index "ix_promoted_theorems_system_primitive" to table: "promoted_theorems"
CREATE INDEX "ix_promoted_theorems_system_primitive" ON "promoted_theorems" ("system_id", "primitive");
-- Create index "uq_promoted_theorems_system_label" to table: "promoted_theorems"
CREATE UNIQUE INDEX "uq_promoted_theorems_system_label" ON "promoted_theorems" ("system_id", "label");
-- Create "promoted_theorem_bindings" table
CREATE TABLE "promoted_theorem_bindings" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "theorem_id" uuid NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  "var" character varying(128) NOT NULL,
  "symbol_id" uuid NOT NULL,
  CONSTRAINT "pk_promoted_theorem_bindings" PRIMARY KEY ("id"),
  CONSTRAINT "fk_promoted_theorem_bindings_symbol_id_symbols" FOREIGN KEY ("symbol_id") REFERENCES "symbols" ("id") ON UPDATE NO ACTION ON DELETE CASCADE,
  CONSTRAINT "fk_promoted_theorem_bindings_theorem_id_promoted_theorems" FOREIGN KEY ("theorem_id") REFERENCES "promoted_theorems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_promoted_theorem_bindings_symbol_id" to table: "promoted_theorem_bindings"
CREATE INDEX "ix_promoted_theorem_bindings_symbol_id" ON "promoted_theorem_bindings" ("symbol_id");
-- Create index "ix_promoted_theorem_bindings_theorem_id" to table: "promoted_theorem_bindings"
CREATE INDEX "ix_promoted_theorem_bindings_theorem_id" ON "promoted_theorem_bindings" ("theorem_id");
-- Create "promoted_theorem_premises" table
CREATE TABLE "promoted_theorem_premises" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "theorem_id" uuid NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  "statement" text NOT NULL,
  "label" character varying(128) NULL,
  "term_id" uuid NULL,
  CONSTRAINT "pk_promoted_theorem_premises" PRIMARY KEY ("id"),
  CONSTRAINT "fk_promoted_theorem_premises_term_id_terms" FOREIGN KEY ("term_id") REFERENCES "terms" ("id") ON UPDATE NO ACTION ON DELETE SET NULL,
  CONSTRAINT "fk_promoted_theorem_premises_theorem_id_promoted_theorems" FOREIGN KEY ("theorem_id") REFERENCES "promoted_theorems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_promoted_theorem_premises_term_id" to table: "promoted_theorem_premises"
CREATE INDEX "ix_promoted_theorem_premises_term_id" ON "promoted_theorem_premises" ("term_id");
-- Create index "ix_promoted_theorem_premises_theorem_id" to table: "promoted_theorem_premises"
CREATE INDEX "ix_promoted_theorem_premises_theorem_id" ON "promoted_theorem_premises" ("theorem_id");
-- Modify "proofs" table
ALTER TABLE "proofs" ADD COLUMN "theorem_id" uuid NULL, ADD CONSTRAINT "fk_proofs_theorem_id_promoted_theorems" FOREIGN KEY ("theorem_id") REFERENCES "promoted_theorems" ("id") ON UPDATE NO ACTION ON DELETE SET NULL;
-- Create index "ix_proofs_theorem_id" to table: "proofs"
CREATE INDEX "ix_proofs_theorem_id" ON "proofs" ("theorem_id");
-- Modify "side_conditions" table
ALTER TABLE "side_conditions" DROP CONSTRAINT "ck_side_conditions_one_owner", ADD CONSTRAINT "ck_side_conditions_one_owner" CHECK (((definition_id IS NOT NULL) AND (rule_id IS NULL) AND (promoted_theorem_id IS NULL)) OR ((definition_id IS NULL) AND (rule_id IS NOT NULL) AND (promoted_theorem_id IS NULL)) OR ((definition_id IS NULL) AND (rule_id IS NULL) AND (promoted_theorem_id IS NOT NULL))), ADD COLUMN "promoted_theorem_id" uuid NULL, ADD CONSTRAINT "fk_side_conditions_promoted_theorem_id_promoted_theorems" FOREIGN KEY ("promoted_theorem_id") REFERENCES "promoted_theorems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE;
-- Create index "ix_side_conditions_promoted_theorem_id" to table: "side_conditions"
CREATE INDEX "ix_side_conditions_promoted_theorem_id" ON "side_conditions" ("promoted_theorem_id");
-- Create index "uq_side_conditions_promoted_theorem_root" to table: "side_conditions"
CREATE UNIQUE INDEX "uq_side_conditions_promoted_theorem_root" ON "side_conditions" ("promoted_theorem_id") WHERE (parent_id IS NULL);
