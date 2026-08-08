-- Create "source_documents" table
CREATE TABLE "source_documents" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "kind" character varying(16) NOT NULL,
  "identifier" character varying(512) NOT NULL,
  "version" character varying(64) NOT NULL DEFAULT '',
  "title" text NULL,
  "url" text NULL,
  "content_hash" character varying(128) NULL,
  "licence" character varying(128) NULL,
  "retrieved_at" timestamptz NULL,
  "registered_by_id" uuid NULL,
  "created_at" timestamptz NOT NULL DEFAULT now(),
  "updated_at" timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT "pk_source_documents" PRIMARY KEY ("id"),
  CONSTRAINT "fk_source_documents_registered_by_id_users" FOREIGN KEY ("registered_by_id") REFERENCES "users" ("id") ON UPDATE NO ACTION ON DELETE SET NULL
);
-- Create index "ix_source_documents_registered_by_id" to table: "source_documents"
CREATE INDEX "ix_source_documents_registered_by_id" ON "source_documents" ("registered_by_id");
-- Create index "uq_source_documents_identity" to table: "source_documents"
CREATE UNIQUE INDEX "uq_source_documents_identity" ON "source_documents" ("kind", "identifier", "version");
-- Create "formalizations" table
CREATE TABLE "formalizations" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "document_id" uuid NOT NULL,
  "claim" character varying(256) NOT NULL,
  "informal_statement" text NOT NULL,
  "formal_system_id" uuid NOT NULL,
  "statement_term_id" uuid NOT NULL,
  "proof_id" uuid NULL,
  "attested_by_id" uuid NULL,
  "attested_as" character varying(128) NULL,
  "reasoning" text NOT NULL,
  "review_verdict" character varying(16) NULL,
  "review_note" text NULL,
  "reviewed_by_id" uuid NULL,
  "reviewed_at" timestamptz NULL,
  "created_at" timestamptz NOT NULL DEFAULT now(),
  "updated_at" timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT "pk_formalizations" PRIMARY KEY ("id"),
  CONSTRAINT "fk_formalizations_attested_by_id_users" FOREIGN KEY ("attested_by_id") REFERENCES "users" ("id") ON UPDATE NO ACTION ON DELETE SET NULL,
  CONSTRAINT "fk_formalizations_document_id_source_documents" FOREIGN KEY ("document_id") REFERENCES "source_documents" ("id") ON UPDATE NO ACTION ON DELETE CASCADE,
  CONSTRAINT "fk_formalizations_formal_system_id_formal_systems" FOREIGN KEY ("formal_system_id") REFERENCES "formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE,
  CONSTRAINT "fk_formalizations_proof_id_proofs" FOREIGN KEY ("proof_id") REFERENCES "proofs" ("id") ON UPDATE NO ACTION ON DELETE SET NULL,
  CONSTRAINT "fk_formalizations_reviewed_by_id_users" FOREIGN KEY ("reviewed_by_id") REFERENCES "users" ("id") ON UPDATE NO ACTION ON DELETE SET NULL,
  CONSTRAINT "fk_formalizations_statement_term_id_terms" FOREIGN KEY ("statement_term_id") REFERENCES "terms" ("id") ON UPDATE NO ACTION ON DELETE NO ACTION
);
-- Create index "ix_formalizations_attested_by_id" to table: "formalizations"
CREATE INDEX "ix_formalizations_attested_by_id" ON "formalizations" ("attested_by_id");
-- Create index "ix_formalizations_document_id" to table: "formalizations"
CREATE INDEX "ix_formalizations_document_id" ON "formalizations" ("document_id");
-- Create index "ix_formalizations_formal_system_id" to table: "formalizations"
CREATE INDEX "ix_formalizations_formal_system_id" ON "formalizations" ("formal_system_id");
-- Create index "ix_formalizations_proof_id" to table: "formalizations"
CREATE INDEX "ix_formalizations_proof_id" ON "formalizations" ("proof_id");
-- Create index "ix_formalizations_reviewed_by_id" to table: "formalizations"
CREATE INDEX "ix_formalizations_reviewed_by_id" ON "formalizations" ("reviewed_by_id");
-- Create index "ix_formalizations_statement_term_id" to table: "formalizations"
CREATE INDEX "ix_formalizations_statement_term_id" ON "formalizations" ("statement_term_id");
-- Create "glossary_entries" table
CREATE TABLE "glossary_entries" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "formalization_id" uuid NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  "notion" character varying(256) NOT NULL,
  "label" character varying(128) NULL,
  "term_id" uuid NULL,
  "reasoning" text NULL,
  CONSTRAINT "pk_glossary_entries" PRIMARY KEY ("id"),
  CONSTRAINT "fk_glossary_entries_formalization_id_formalizations" FOREIGN KEY ("formalization_id") REFERENCES "formalizations" ("id") ON UPDATE NO ACTION ON DELETE CASCADE,
  CONSTRAINT "fk_glossary_entries_term_id_terms" FOREIGN KEY ("term_id") REFERENCES "terms" ("id") ON UPDATE NO ACTION ON DELETE SET NULL
);
-- Create index "ix_glossary_entries_formalization_id" to table: "glossary_entries"
CREATE INDEX "ix_glossary_entries_formalization_id" ON "glossary_entries" ("formalization_id");
-- Create index "ix_glossary_entries_term_id" to table: "glossary_entries"
CREATE INDEX "ix_glossary_entries_term_id" ON "glossary_entries" ("term_id");
