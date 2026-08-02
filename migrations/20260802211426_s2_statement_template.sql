-- Modify "system_relations" table
ALTER TABLE "system_relations" ADD COLUMN "statement_template" character varying(512) NULL;
-- Create "system_relation_extras" table
CREATE TABLE "system_relation_extras" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "relation_id" uuid NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  "name" character varying(128) NOT NULL,
  "sort" character varying(128) NOT NULL,
  CONSTRAINT "pk_system_relation_extras" PRIMARY KEY ("id"),
  CONSTRAINT "fk_system_relation_extras_relation_id_system_relations" FOREIGN KEY ("relation_id") REFERENCES "system_relations" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_system_relation_extras_relation_id" to table: "system_relation_extras"
CREATE INDEX "ix_system_relation_extras_relation_id" ON "system_relation_extras" ("relation_id");
-- Create index "uq_system_relation_extras_name" to table: "system_relation_extras"
CREATE UNIQUE INDEX "uq_system_relation_extras_name" ON "system_relation_extras" ("relation_id", "name");
