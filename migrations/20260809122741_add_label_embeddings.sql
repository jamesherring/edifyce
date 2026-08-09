-- Create "label_embeddings" table
CREATE TABLE "label_embeddings" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "formal_system_id" uuid NOT NULL,
  "label" character varying(128) NOT NULL,
  "model" character varying(128) NOT NULL,
  "embedding" vector(1536) NOT NULL,
  "source_digest" character varying(64) NOT NULL,
  "tokens" integer NULL,
  "created_at" timestamptz NOT NULL DEFAULT now(),
  "updated_at" timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT "pk_label_embeddings" PRIMARY KEY ("id"),
  CONSTRAINT "fk_label_embeddings_formal_system_id_formal_systems" FOREIGN KEY ("formal_system_id") REFERENCES "formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_label_embeddings_embedding" to table: "label_embeddings"
CREATE INDEX "ix_label_embeddings_embedding" ON "label_embeddings" USING HNSW ("embedding" vector_cosine_ops);
-- Create index "ix_label_embeddings_formal_system_id" to table: "label_embeddings"
CREATE INDEX "ix_label_embeddings_formal_system_id" ON "label_embeddings" ("formal_system_id");
-- Create index "uq_label_embeddings_system_label_model" to table: "label_embeddings"
CREATE UNIQUE INDEX "uq_label_embeddings_system_label_model" ON "label_embeddings" ("formal_system_id", "label", "model");
