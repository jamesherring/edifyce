-- Enable pgvector (required by "theorems".embedding and its HNSW index).
-- Hand-added: the community Atlas build omits CREATE EXTENSION from diffs, so
-- re-add this and run `atlas migrate hash` if the initial migration is regenerated.
CREATE EXTENSION IF NOT EXISTS "vector";
-- Create "users" table
CREATE TABLE "public"."users" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "is_active" boolean NOT NULL DEFAULT true, "is_superuser" boolean NOT NULL DEFAULT false, "is_verified" boolean NOT NULL DEFAULT false, "display_name" character varying(256) NULL, "email" character varying(320) NOT NULL, "hashed_password" character varying(1024) NOT NULL, "created_at" timestamptz NOT NULL DEFAULT now(), "updated_at" timestamptz NOT NULL DEFAULT now(), PRIMARY KEY ("id"));
-- Create index "ix_users_email" to table: "users"
CREATE UNIQUE INDEX "ix_users_email" ON "public"."users" ("email");
-- Create "formal_systems" table
CREATE TABLE "public"."formal_systems" ("owner_id" uuid NULL, "name" character varying(256) NOT NULL, "slug" character varying(256) NOT NULL, "description" text NULL, "inherits_from_id" uuid NULL, "published_at" timestamptz NULL, "id" uuid NOT NULL DEFAULT gen_random_uuid(), "created_at" timestamptz NOT NULL DEFAULT now(), "updated_at" timestamptz NOT NULL DEFAULT now(), PRIMARY KEY ("id"), CONSTRAINT "fk_formal_systems_inherits_from_id_formal_systems" FOREIGN KEY ("inherits_from_id") REFERENCES "public"."formal_systems" ("id") ON UPDATE NO ACTION ON DELETE SET NULL, CONSTRAINT "fk_formal_systems_owner_id_users" FOREIGN KEY ("owner_id") REFERENCES "public"."users" ("id") ON UPDATE NO ACTION ON DELETE SET NULL);
-- Create index "ix_formal_systems_inherits_from_id" to table: "formal_systems"
CREATE INDEX "ix_formal_systems_inherits_from_id" ON "public"."formal_systems" ("inherits_from_id");
-- Create index "ix_formal_systems_owner_id" to table: "formal_systems"
CREATE INDEX "ix_formal_systems_owner_id" ON "public"."formal_systems" ("owner_id");
-- Create index "ix_formal_systems_slug" to table: "formal_systems"
CREATE INDEX "ix_formal_systems_slug" ON "public"."formal_systems" ("slug");
-- Create index "uq_formal_systems_owner_slug" to table: "formal_systems"
CREATE UNIQUE INDEX "uq_formal_systems_owner_slug" ON "public"."formal_systems" ("owner_id", "slug") WHERE (owner_id IS NOT NULL);
-- Create "axioms" table
CREATE TABLE "public"."axioms" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "system_id" uuid NOT NULL, "position" integer NOT NULL DEFAULT 0, "label" character varying(64) NOT NULL, "name" character varying(128) NOT NULL, "formula" character varying(512) NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "fk_axioms_system_id_formal_systems" FOREIGN KEY ("system_id") REFERENCES "public"."formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_axioms_label" to table: "axioms"
CREATE INDEX "ix_axioms_label" ON "public"."axioms" ("label");
-- Create index "ix_axioms_name" to table: "axioms"
CREATE INDEX "ix_axioms_name" ON "public"."axioms" ("name");
-- Create index "ix_axioms_system_id" to table: "axioms"
CREATE INDEX "ix_axioms_system_id" ON "public"."axioms" ("system_id");
-- Create "axiom_bindings" table
CREATE TABLE "public"."axiom_bindings" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "axiom_id" uuid NOT NULL, "position" integer NOT NULL DEFAULT 0, "var" character varying(64) NOT NULL, "sort" character varying(128) NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "fk_axiom_bindings_axiom_id_axioms" FOREIGN KEY ("axiom_id") REFERENCES "public"."axioms" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_axiom_bindings_axiom_id" to table: "axiom_bindings"
CREATE INDEX "ix_axiom_bindings_axiom_id" ON "public"."axiom_bindings" ("axiom_id");
-- Create index "ix_axiom_bindings_sort" to table: "axiom_bindings"
CREATE INDEX "ix_axiom_bindings_sort" ON "public"."axiom_bindings" ("sort");
-- Create "definitions" table
CREATE TABLE "public"."definitions" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "system_id" uuid NOT NULL, "position" integer NOT NULL DEFAULT 0, "sort" character varying(128) NOT NULL, "name" character varying(128) NOT NULL, "higher" character varying(512) NOT NULL, "lower" character varying(512) NOT NULL, "condition" character varying(512) NULL, PRIMARY KEY ("id"), CONSTRAINT "fk_definitions_system_id_formal_systems" FOREIGN KEY ("system_id") REFERENCES "public"."formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_definitions_name" to table: "definitions"
CREATE INDEX "ix_definitions_name" ON "public"."definitions" ("name");
-- Create index "ix_definitions_sort" to table: "definitions"
CREATE INDEX "ix_definitions_sort" ON "public"."definitions" ("sort");
-- Create index "ix_definitions_system_id" to table: "definitions"
CREATE INDEX "ix_definitions_system_id" ON "public"."definitions" ("system_id");
-- Create "definition_bindings" table
CREATE TABLE "public"."definition_bindings" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "definition_id" uuid NOT NULL, "position" integer NOT NULL DEFAULT 0, "var" character varying(64) NOT NULL, "sort" character varying(128) NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "fk_definition_bindings_definition_id_definitions" FOREIGN KEY ("definition_id") REFERENCES "public"."definitions" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_definition_bindings_definition_id" to table: "definition_bindings"
CREATE INDEX "ix_definition_bindings_definition_id" ON "public"."definition_bindings" ("definition_id");
-- Create index "ix_definition_bindings_sort" to table: "definition_bindings"
CREATE INDEX "ix_definition_bindings_sort" ON "public"."definition_bindings" ("sort");
-- Create "line_types" table
CREATE TABLE "public"."line_types" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "system_id" uuid NOT NULL, "position" integer NOT NULL DEFAULT 0, "name" character varying(128) NOT NULL, "shape" character varying(256) NOT NULL, "logical_sort" character varying(128) NULL, PRIMARY KEY ("id"), CONSTRAINT "fk_line_types_system_id_formal_systems" FOREIGN KEY ("system_id") REFERENCES "public"."formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_line_types_system_id" to table: "line_types"
CREATE INDEX "ix_line_types_system_id" ON "public"."line_types" ("system_id");
-- Create "line_parts" table
CREATE TABLE "public"."line_parts" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "line_id" uuid NOT NULL, "position" integer NOT NULL DEFAULT 0, "name" character varying(128) NOT NULL, "regex" character varying(512) NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "fk_line_parts_line_id_line_types" FOREIGN KEY ("line_id") REFERENCES "public"."line_types" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_line_parts_line_id" to table: "line_parts"
CREATE INDEX "ix_line_parts_line_id" ON "public"."line_parts" ("line_id");
-- Create "notation_brackets" table
CREATE TABLE "public"."notation_brackets" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "system_id" uuid NOT NULL, "position" integer NOT NULL DEFAULT 0, "opening" character varying(16) NOT NULL, "closing" character varying(16) NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "fk_notation_brackets_system_id_formal_systems" FOREIGN KEY ("system_id") REFERENCES "public"."formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_notation_brackets_system_id" to table: "notation_brackets"
CREATE INDEX "ix_notation_brackets_system_id" ON "public"."notation_brackets" ("system_id");
-- Create "oauth_accounts" table
CREATE TABLE "public"."oauth_accounts" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "user_id" uuid NOT NULL, "oauth_name" character varying(100) NOT NULL, "access_token" character varying(1024) NOT NULL, "expires_at" integer NULL, "refresh_token" character varying(1024) NULL, "account_id" character varying(320) NOT NULL, "account_email" character varying(320) NOT NULL, "created_at" timestamptz NOT NULL DEFAULT now(), "updated_at" timestamptz NOT NULL DEFAULT now(), PRIMARY KEY ("id"), CONSTRAINT "fk_oauth_accounts_user_id_users" FOREIGN KEY ("user_id") REFERENCES "public"."users" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_oauth_accounts_account_id" to table: "oauth_accounts"
CREATE INDEX "ix_oauth_accounts_account_id" ON "public"."oauth_accounts" ("account_id");
-- Create index "ix_oauth_accounts_oauth_name" to table: "oauth_accounts"
CREATE INDEX "ix_oauth_accounts_oauth_name" ON "public"."oauth_accounts" ("oauth_name");
-- Create index "ix_oauth_accounts_user_id" to table: "oauth_accounts"
CREATE INDEX "ix_oauth_accounts_user_id" ON "public"."oauth_accounts" ("user_id");
-- Create "sorts" table
CREATE TABLE "public"."sorts" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "system_id" uuid NOT NULL, "position" integer NOT NULL DEFAULT 0, "name" character varying(128) NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "fk_sorts_system_id_formal_systems" FOREIGN KEY ("system_id") REFERENCES "public"."formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_sorts_name" to table: "sorts"
CREATE INDEX "ix_sorts_name" ON "public"."sorts" ("name");
-- Create index "ix_sorts_system_id" to table: "sorts"
CREATE INDEX "ix_sorts_system_id" ON "public"."sorts" ("system_id");
-- Create index "uq_sorts_system_name" to table: "sorts"
CREATE UNIQUE INDEX "uq_sorts_system_name" ON "public"."sorts" ("system_id", "name");
-- Create "productions" table
CREATE TABLE "public"."productions" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "system_id" uuid NOT NULL, "sort_id" uuid NOT NULL, "position" integer NOT NULL DEFAULT 0, "name" character varying(128) NOT NULL, "kind" character varying(16) NOT NULL, "template" character varying(512) NULL, "regex" character varying(512) NULL, PRIMARY KEY ("id"), CONSTRAINT "fk_productions_sort_id_sorts" FOREIGN KEY ("sort_id") REFERENCES "public"."sorts" ("id") ON UPDATE NO ACTION ON DELETE CASCADE, CONSTRAINT "fk_productions_system_id_formal_systems" FOREIGN KEY ("system_id") REFERENCES "public"."formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_productions_name" to table: "productions"
CREATE INDEX "ix_productions_name" ON "public"."productions" ("name");
-- Create index "ix_productions_sort_id" to table: "productions"
CREATE INDEX "ix_productions_sort_id" ON "public"."productions" ("sort_id");
-- Create index "ix_productions_system_id" to table: "productions"
CREATE INDEX "ix_productions_system_id" ON "public"."productions" ("system_id");
-- Create "production_bindings" table
CREATE TABLE "public"."production_bindings" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "production_id" uuid NOT NULL, "position" integer NOT NULL DEFAULT 0, "var" character varying(64) NOT NULL, "sort" character varying(128) NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "fk_production_bindings_production_id_productions" FOREIGN KEY ("production_id") REFERENCES "public"."productions" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_production_bindings_production_id" to table: "production_bindings"
CREATE INDEX "ix_production_bindings_production_id" ON "public"."production_bindings" ("production_id");
-- Create index "ix_production_bindings_sort" to table: "production_bindings"
CREATE INDEX "ix_production_bindings_sort" ON "public"."production_bindings" ("sort");
-- Create "proof_folders" table
CREATE TABLE "public"."proof_folders" ("owner_id" uuid NULL, "formal_system_id" uuid NOT NULL, "parent_id" uuid NULL, "name" character varying(256) NOT NULL, "slug" character varying(256) NOT NULL, "position" integer NOT NULL DEFAULT 0, "published_at" timestamptz NULL, "id" uuid NOT NULL DEFAULT gen_random_uuid(), "created_at" timestamptz NOT NULL DEFAULT now(), "updated_at" timestamptz NOT NULL DEFAULT now(), PRIMARY KEY ("id"), CONSTRAINT "fk_proof_folders_formal_system_id_formal_systems" FOREIGN KEY ("formal_system_id") REFERENCES "public"."formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE, CONSTRAINT "fk_proof_folders_owner_id_users" FOREIGN KEY ("owner_id") REFERENCES "public"."users" ("id") ON UPDATE NO ACTION ON DELETE SET NULL, CONSTRAINT "fk_proof_folders_parent_id_proof_folders" FOREIGN KEY ("parent_id") REFERENCES "public"."proof_folders" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_proof_folders_formal_system_id" to table: "proof_folders"
CREATE INDEX "ix_proof_folders_formal_system_id" ON "public"."proof_folders" ("formal_system_id");
-- Create index "ix_proof_folders_owner_id" to table: "proof_folders"
CREATE INDEX "ix_proof_folders_owner_id" ON "public"."proof_folders" ("owner_id");
-- Create index "ix_proof_folders_parent_id" to table: "proof_folders"
CREATE INDEX "ix_proof_folders_parent_id" ON "public"."proof_folders" ("parent_id");
-- Create index "ix_proof_folders_slug" to table: "proof_folders"
CREATE INDEX "ix_proof_folders_slug" ON "public"."proof_folders" ("slug");
-- Create "proofs" table
CREATE TABLE "public"."proofs" ("owner_id" uuid NULL, "formal_system_id" uuid NOT NULL, "folder_id" uuid NULL, "name" character varying(256) NOT NULL, "slug" character varying(256) NOT NULL, "description" text NULL, "source" text NOT NULL DEFAULT '', "position" integer NOT NULL DEFAULT 0, "result" jsonb NULL, "valid" boolean NULL, "published_at" timestamptz NULL, "id" uuid NOT NULL DEFAULT gen_random_uuid(), "created_at" timestamptz NOT NULL DEFAULT now(), "updated_at" timestamptz NOT NULL DEFAULT now(), PRIMARY KEY ("id"), CONSTRAINT "fk_proofs_folder_id_proof_folders" FOREIGN KEY ("folder_id") REFERENCES "public"."proof_folders" ("id") ON UPDATE NO ACTION ON DELETE SET NULL, CONSTRAINT "fk_proofs_formal_system_id_formal_systems" FOREIGN KEY ("formal_system_id") REFERENCES "public"."formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE, CONSTRAINT "fk_proofs_owner_id_users" FOREIGN KEY ("owner_id") REFERENCES "public"."users" ("id") ON UPDATE NO ACTION ON DELETE SET NULL);
-- Create index "ix_proofs_folder_id" to table: "proofs"
CREATE INDEX "ix_proofs_folder_id" ON "public"."proofs" ("folder_id");
-- Create index "ix_proofs_formal_system_id" to table: "proofs"
CREATE INDEX "ix_proofs_formal_system_id" ON "public"."proofs" ("formal_system_id");
-- Create index "ix_proofs_owner_id" to table: "proofs"
CREATE INDEX "ix_proofs_owner_id" ON "public"."proofs" ("owner_id");
-- Create index "ix_proofs_slug" to table: "proofs"
CREATE INDEX "ix_proofs_slug" ON "public"."proofs" ("slug");
-- Create "proof_references" table
CREATE TABLE "public"."proof_references" ("proof_id" uuid NOT NULL, "references_id" uuid NOT NULL, PRIMARY KEY ("proof_id", "references_id"), CONSTRAINT "fk_proof_references_proof_id_proofs" FOREIGN KEY ("proof_id") REFERENCES "public"."proofs" ("id") ON UPDATE NO ACTION ON DELETE CASCADE, CONSTRAINT "fk_proof_references_references_id_proofs" FOREIGN KEY ("references_id") REFERENCES "public"."proofs" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create "rules" table
CREATE TABLE "public"."rules" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "system_id" uuid NOT NULL, "position" integer NOT NULL DEFAULT 0, "label" character varying(64) NOT NULL, "name" character varying(128) NOT NULL, "deduction" character varying(512) NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "fk_rules_system_id_formal_systems" FOREIGN KEY ("system_id") REFERENCES "public"."formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_rules_label" to table: "rules"
CREATE INDEX "ix_rules_label" ON "public"."rules" ("label");
-- Create index "ix_rules_name" to table: "rules"
CREATE INDEX "ix_rules_name" ON "public"."rules" ("name");
-- Create index "ix_rules_system_id" to table: "rules"
CREATE INDEX "ix_rules_system_id" ON "public"."rules" ("system_id");
-- Create "rule_antecedents" table
CREATE TABLE "public"."rule_antecedents" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "rule_id" uuid NOT NULL, "position" integer NOT NULL DEFAULT 0, "pattern" character varying(512) NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "fk_rule_antecedents_rule_id_rules" FOREIGN KEY ("rule_id") REFERENCES "public"."rules" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_rule_antecedents_rule_id" to table: "rule_antecedents"
CREATE INDEX "ix_rule_antecedents_rule_id" ON "public"."rule_antecedents" ("rule_id");
-- Create "rule_bindings" table
CREATE TABLE "public"."rule_bindings" ("id" uuid NOT NULL DEFAULT gen_random_uuid(), "rule_id" uuid NOT NULL, "position" integer NOT NULL DEFAULT 0, "var" character varying(64) NOT NULL, "sort" character varying(128) NOT NULL, PRIMARY KEY ("id"), CONSTRAINT "fk_rule_bindings_rule_id_rules" FOREIGN KEY ("rule_id") REFERENCES "public"."rules" ("id") ON UPDATE NO ACTION ON DELETE CASCADE);
-- Create index "ix_rule_bindings_rule_id" to table: "rule_bindings"
CREATE INDEX "ix_rule_bindings_rule_id" ON "public"."rule_bindings" ("rule_id");
-- Create index "ix_rule_bindings_sort" to table: "rule_bindings"
CREATE INDEX "ix_rule_bindings_sort" ON "public"."rule_bindings" ("sort");
-- Create "theorems" table
CREATE TABLE "public"."theorems" ("formal_system_id" uuid NOT NULL, "proof_id" uuid NULL, "statement" text NOT NULL, "pattern" jsonb NULL, "embedding" public.vector(1536) NULL, "id" uuid NOT NULL DEFAULT gen_random_uuid(), "created_at" timestamptz NOT NULL DEFAULT now(), "updated_at" timestamptz NOT NULL DEFAULT now(), PRIMARY KEY ("id"), CONSTRAINT "fk_theorems_formal_system_id_formal_systems" FOREIGN KEY ("formal_system_id") REFERENCES "public"."formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE, CONSTRAINT "fk_theorems_proof_id_proofs" FOREIGN KEY ("proof_id") REFERENCES "public"."proofs" ("id") ON UPDATE NO ACTION ON DELETE SET NULL);
-- Create index "ix_theorems_embedding" to table: "theorems"
CREATE INDEX "ix_theorems_embedding" ON "public"."theorems" USING hnsw ("embedding" vector_cosine_ops);
-- Create index "ix_theorems_formal_system_id" to table: "theorems"
CREATE INDEX "ix_theorems_formal_system_id" ON "public"."theorems" ("formal_system_id");
-- Create index "ix_theorems_pattern" to table: "theorems"
CREATE INDEX "ix_theorems_pattern" ON "public"."theorems" USING gin ("pattern");
-- Create index "ix_theorems_proof_id" to table: "theorems"
CREATE INDEX "ix_theorems_proof_id" ON "public"."theorems" ("proof_id");
