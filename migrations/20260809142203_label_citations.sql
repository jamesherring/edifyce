-- Create "label_citations" table
CREATE TABLE "label_citations" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "description_id" uuid NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  "work" character varying(64) NOT NULL,
  "page" character varying(32) NOT NULL,
  "start_offset" integer NOT NULL,
  "end_offset" integer NOT NULL,
  CONSTRAINT "pk_label_citations" PRIMARY KEY ("id"),
  CONSTRAINT "fk_label_citations_description_id_label_descriptions" FOREIGN KEY ("description_id") REFERENCES "label_descriptions" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_label_citations_description_id" to table: "label_citations"
CREATE INDEX "ix_label_citations_description_id" ON "label_citations" ("description_id");
-- Create index "ix_label_citations_work" to table: "label_citations"
CREATE INDEX "ix_label_citations_work" ON "label_citations" ("work");
