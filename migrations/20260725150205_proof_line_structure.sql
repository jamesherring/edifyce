-- Create "proof_lines" table
CREATE TABLE "proof_lines" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "proof_id" uuid NOT NULL,
  "position" integer NOT NULL,
  "number" integer NULL,
  "indent" integer NOT NULL DEFAULT 0,
  "display" text NOT NULL DEFAULT '',
  "line_type" character varying(256) NULL,
  "behaviour" character varying(32) NULL,
  "label" character varying(256) NULL,
  "reference" text NULL,
  "rule" character varying(256) NULL,
  "term_id" uuid NULL,
  "valid" boolean NOT NULL DEFAULT true,
  "invalid_message" text NULL,
  "warning_message" text NULL,
  "opens_scope" character varying(32) NULL,
  "scope_id" uuid NULL,
  CONSTRAINT "pk_proof_lines" PRIMARY KEY ("id"),
  CONSTRAINT "fk_proof_lines_proof_id_proofs" FOREIGN KEY ("proof_id") REFERENCES "proofs" ("id") ON UPDATE NO ACTION ON DELETE CASCADE,
  CONSTRAINT "fk_proof_lines_scope_id_proof_lines" FOREIGN KEY ("scope_id") REFERENCES "proof_lines" ("id") ON UPDATE NO ACTION ON DELETE CASCADE,
  CONSTRAINT "fk_proof_lines_term_id_terms" FOREIGN KEY ("term_id") REFERENCES "terms" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION
);
-- Create index "ix_proof_lines_proof_id" to table: "proof_lines"
CREATE INDEX "ix_proof_lines_proof_id" ON "proof_lines" ("proof_id");
-- Create index "ix_proof_lines_proof_number" to table: "proof_lines"
CREATE INDEX "ix_proof_lines_proof_number" ON "proof_lines" ("proof_id", "number");
-- Create index "ix_proof_lines_scope_id" to table: "proof_lines"
CREATE INDEX "ix_proof_lines_scope_id" ON "proof_lines" ("scope_id");
-- Create index "ix_proof_lines_term_id" to table: "proof_lines"
CREATE INDEX "ix_proof_lines_term_id" ON "proof_lines" ("term_id");
-- Create index "uq_proof_lines_proof_position" to table: "proof_lines"
CREATE UNIQUE INDEX "uq_proof_lines_proof_position" ON "proof_lines" ("proof_id", "position");
-- Create "proof_line_antecedents" table
CREATE TABLE "proof_line_antecedents" (
  "line_id" uuid NOT NULL,
  "position" integer NOT NULL,
  "role" character varying(32) NOT NULL DEFAULT 'antecedent',
  "antecedent_line_id" uuid NULL,
  "antecedent_proof_id" uuid NULL,
  "antecedent_number" integer NULL,
  CONSTRAINT "pk_proof_line_antecedents" PRIMARY KEY ("line_id", "position"),
  CONSTRAINT "fk_proof_line_antecedents_antecedent_line_id_proof_lines" FOREIGN KEY ("antecedent_line_id") REFERENCES "proof_lines" ("id") ON UPDATE NO ACTION ON DELETE CASCADE,
  CONSTRAINT "fk_proof_line_antecedents_antecedent_proof_id_proofs" FOREIGN KEY ("antecedent_proof_id") REFERENCES "proofs" ("id") ON UPDATE NO ACTION ON DELETE CASCADE,
  CONSTRAINT "fk_proof_line_antecedents_line_id_proof_lines" FOREIGN KEY ("line_id") REFERENCES "proof_lines" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_proof_line_antecedents_antecedent_line_id" to table: "proof_line_antecedents"
CREATE INDEX "ix_proof_line_antecedents_antecedent_line_id" ON "proof_line_antecedents" ("antecedent_line_id");
-- Create index "ix_proof_line_antecedents_antecedent_proof_id" to table: "proof_line_antecedents"
CREATE INDEX "ix_proof_line_antecedents_antecedent_proof_id" ON "proof_line_antecedents" ("antecedent_proof_id");
