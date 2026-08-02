-- Modify "proofs" table
ALTER TABLE "proofs" ADD COLUMN "title" text NULL;
-- Create "label_descriptions" table
CREATE TABLE "label_descriptions" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "formal_system_id" uuid NOT NULL,
  "label" character varying(128) NOT NULL,
  "title" text NULL,
  "text" text NOT NULL DEFAULT '',
  CONSTRAINT "pk_label_descriptions" PRIMARY KEY ("id"),
  CONSTRAINT "fk_label_descriptions_formal_system_id_formal_systems" FOREIGN KEY ("formal_system_id") REFERENCES "formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_label_descriptions_formal_system_id" to table: "label_descriptions"
CREATE INDEX "ix_label_descriptions_formal_system_id" ON "label_descriptions" ("formal_system_id");
-- Create index "uq_label_descriptions_system_label" to table: "label_descriptions"
CREATE UNIQUE INDEX "uq_label_descriptions_system_label" ON "label_descriptions" ("formal_system_id", "label");
-- Create "label_attributions" table
CREATE TABLE "label_attributions" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "description_id" uuid NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  "kind" character varying(64) NOT NULL,
  "who" character varying(128) NOT NULL,
  "dated" character varying(64) NOT NULL,
  CONSTRAINT "pk_label_attributions" PRIMARY KEY ("id"),
  CONSTRAINT "fk_label_attributions_description_id_label_descriptions" FOREIGN KEY ("description_id") REFERENCES "label_descriptions" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_label_attributions_description_id" to table: "label_attributions"
CREATE INDEX "ix_label_attributions_description_id" ON "label_attributions" ("description_id");
-- Create index "ix_label_attributions_kind" to table: "label_attributions"
CREATE INDEX "ix_label_attributions_kind" ON "label_attributions" ("kind");
-- Create index "ix_label_attributions_who" to table: "label_attributions"
CREATE INDEX "ix_label_attributions_who" ON "label_attributions" ("who");
