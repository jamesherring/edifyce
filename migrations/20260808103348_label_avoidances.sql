-- Create "label_avoidances" table
CREATE TABLE "label_avoidances" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "formal_system_id" uuid NOT NULL,
  "label" character varying(128) NOT NULL,
  "avoided" character varying(128) NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  CONSTRAINT "pk_label_avoidances" PRIMARY KEY ("id"),
  CONSTRAINT "fk_label_avoidances_formal_system_id_formal_systems" FOREIGN KEY ("formal_system_id") REFERENCES "formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_label_avoidances_avoided" to table: "label_avoidances"
CREATE INDEX "ix_label_avoidances_avoided" ON "label_avoidances" ("avoided");
-- Create index "ix_label_avoidances_formal_system_id" to table: "label_avoidances"
CREATE INDEX "ix_label_avoidances_formal_system_id" ON "label_avoidances" ("formal_system_id");
-- Create index "ix_label_avoidances_system_label" to table: "label_avoidances"
CREATE INDEX "ix_label_avoidances_system_label" ON "label_avoidances" ("formal_system_id", "label");
