-- Create "production_binding_scopes" table
CREATE TABLE "production_binding_scopes" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "binding_id" uuid NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  "scoped_binding_id" uuid NOT NULL,
  CONSTRAINT "pk_production_binding_scopes" PRIMARY KEY ("id"),
  CONSTRAINT "fk_production_binding_scopes_binding_id_production_bindings" FOREIGN KEY ("binding_id") REFERENCES "production_bindings" ("id") ON UPDATE NO ACTION ON DELETE CASCADE,
  CONSTRAINT "fk_production_binding_scopes_scoped_binding_id_producti_5854" FOREIGN KEY ("scoped_binding_id") REFERENCES "production_bindings" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_production_binding_scopes_binding_id" to table: "production_binding_scopes"
CREATE INDEX "ix_production_binding_scopes_binding_id" ON "production_binding_scopes" ("binding_id");
-- Create index "ix_production_binding_scopes_scoped_binding_id" to table: "production_binding_scopes"
CREATE INDEX "ix_production_binding_scopes_scoped_binding_id" ON "production_binding_scopes" ("scoped_binding_id");
