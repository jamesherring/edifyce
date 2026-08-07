-- Modify "label_descriptions" table
ALTER TABLE "label_descriptions" ADD COLUMN "discouraged_usage" boolean NOT NULL DEFAULT false, ADD COLUMN "discouraged_modification" boolean NOT NULL DEFAULT false;
-- Create "label_references" table
CREATE TABLE "label_references" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "description_id" uuid NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  "target" character varying(512) NOT NULL,
  "start_offset" integer NOT NULL,
  "end_offset" integer NOT NULL,
  CONSTRAINT "pk_label_references" PRIMARY KEY ("id"),
  CONSTRAINT "fk_label_references_description_id_label_descriptions" FOREIGN KEY ("description_id") REFERENCES "label_descriptions" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_label_references_description_id" to table: "label_references"
CREATE INDEX "ix_label_references_description_id" ON "label_references" ("description_id");
-- Create index "ix_label_references_target" to table: "label_references"
CREATE INDEX "ix_label_references_target" ON "label_references" ("target");
