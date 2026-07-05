-- Enable pgvector (required by the "theorems".embedding column and its HNSW index).
-- Kept as the first statement by hand: Atlas does not emit CREATE EXTENSION in the
-- community build, so re-hash (atlas migrate hash) after editing this file.
CREATE EXTENSION IF NOT EXISTS "vector";
-- Create "users" table
CREATE TABLE "public"."users" ("email" character varying(320) NOT NULL, "display_name" character varying(256) NULL, "hashed_password" character varying(256) NULL, "is_active" boolean NOT NULL DEFAULT true, "id" uuid NOT NULL DEFAULT gen_random_uuid(), "created_at" timestamptz NOT NULL DEFAULT now(), "updated_at" timestamptz NOT NULL DEFAULT now(), PRIMARY KEY ("id"));
-- Create index "ix_users_email" to table: "users"
CREATE UNIQUE INDEX "ix_users_email" ON "public"."users" ("email");
-- Create "formal_systems" table
CREATE TABLE "public"."formal_systems" ("owner_id" uuid NULL, "name" character varying(256) NOT NULL, "slug" character varying(256) NOT NULL, "source" text NOT NULL DEFAULT '', "description" text NULL, "inherits_from_id" uuid NULL, "compiled" jsonb NULL, "published_at" timestamptz NULL, "id" uuid NOT NULL DEFAULT gen_random_uuid(), "created_at" timestamptz NOT NULL DEFAULT now(), "updated_at" timestamptz NOT NULL DEFAULT now(), PRIMARY KEY ("id"), CONSTRAINT "fk_formal_systems_inherits_from_id_formal_systems" FOREIGN KEY ("inherits_from_id") REFERENCES "public"."formal_systems" ("id") ON UPDATE NO ACTION ON DELETE SET NULL, CONSTRAINT "fk_formal_systems_owner_id_users" FOREIGN KEY ("owner_id") REFERENCES "public"."users" ("id") ON UPDATE NO ACTION ON DELETE SET NULL);
-- Create index "ix_formal_systems_inherits_from_id" to table: "formal_systems"
CREATE INDEX "ix_formal_systems_inherits_from_id" ON "public"."formal_systems" ("inherits_from_id");
-- Create index "ix_formal_systems_owner_id" to table: "formal_systems"
CREATE INDEX "ix_formal_systems_owner_id" ON "public"."formal_systems" ("owner_id");
-- Create index "ix_formal_systems_slug" to table: "formal_systems"
CREATE INDEX "ix_formal_systems_slug" ON "public"."formal_systems" ("slug");
-- Create index "uq_formal_systems_owner_slug" to table: "formal_systems"
CREATE UNIQUE INDEX "uq_formal_systems_owner_slug" ON "public"."formal_systems" ("owner_id", "slug");
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
