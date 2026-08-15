-- Create "system_relations" table
CREATE TABLE "system_relations" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "source_system_id" uuid NOT NULL,
  "target_system_id" uuid NOT NULL,
  "kind" character varying(16) NOT NULL DEFAULT 'extension',
  "status" character varying(16) NOT NULL DEFAULT 'draft',
  "position" integer NOT NULL DEFAULT 0,
  CONSTRAINT "pk_system_relations" PRIMARY KEY ("id"),
  CONSTRAINT "fk_system_relations_source_system_id_formal_systems" FOREIGN KEY ("source_system_id") REFERENCES "formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE,
  CONSTRAINT "fk_system_relations_target_system_id_formal_systems" FOREIGN KEY ("target_system_id") REFERENCES "formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_system_relations_source_system_id" to table: "system_relations"
CREATE INDEX "ix_system_relations_source_system_id" ON "system_relations" ("source_system_id");
-- Create index "ix_system_relations_target_status" to table: "system_relations"
CREATE INDEX "ix_system_relations_target_status" ON "system_relations" ("target_system_id", "status");
-- Create index "ix_system_relations_target_system_id" to table: "system_relations"
CREATE INDEX "ix_system_relations_target_system_id" ON "system_relations" ("target_system_id");
-- Create index "uq_system_relations_source_target" to table: "system_relations"
CREATE UNIQUE INDEX "uq_system_relations_source_target" ON "system_relations" ("source_system_id", "target_system_id");
-- Create "system_relation_obligations" table
CREATE TABLE "system_relation_obligations" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "relation_id" uuid NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  "source_label" character varying(128) NOT NULL,
  "discharged_by_primitive" character varying(128) NULL,
  "discharged_by_theorem_id" uuid NULL,
  "status" character varying(16) NOT NULL DEFAULT 'draft',
  CONSTRAINT "pk_system_relation_obligations" PRIMARY KEY ("id"),
  CONSTRAINT "fk_system_relation_obligations_discharged_by_theorem_id_3bed" FOREIGN KEY ("discharged_by_theorem_id") REFERENCES "promoted_theorems" ("id") ON UPDATE NO ACTION ON DELETE SET NULL,
  CONSTRAINT "fk_system_relation_obligations_relation_id_system_relations" FOREIGN KEY ("relation_id") REFERENCES "system_relations" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_system_relation_obligations_discharged_by_theorem_id" to table: "system_relation_obligations"
CREATE INDEX "ix_system_relation_obligations_discharged_by_theorem_id" ON "system_relation_obligations" ("discharged_by_theorem_id");
-- Create index "ix_system_relation_obligations_relation_id" to table: "system_relation_obligations"
CREATE INDEX "ix_system_relation_obligations_relation_id" ON "system_relation_obligations" ("relation_id");
-- Create index "uq_system_relation_obligations_label" to table: "system_relation_obligations"
CREATE UNIQUE INDEX "uq_system_relation_obligations_label" ON "system_relation_obligations" ("relation_id", "source_label");
-- Create "system_relation_sorts" table
CREATE TABLE "system_relation_sorts" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "relation_id" uuid NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  "source_sort" character varying(128) NOT NULL,
  "target_sort" character varying(128) NOT NULL,
  CONSTRAINT "pk_system_relation_sorts" PRIMARY KEY ("id"),
  CONSTRAINT "fk_system_relation_sorts_relation_id_system_relations" FOREIGN KEY ("relation_id") REFERENCES "system_relations" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_system_relation_sorts_relation_id" to table: "system_relation_sorts"
CREATE INDEX "ix_system_relation_sorts_relation_id" ON "system_relation_sorts" ("relation_id");
-- Create index "uq_system_relation_sorts_source" to table: "system_relation_sorts"
CREATE UNIQUE INDEX "uq_system_relation_sorts_source" ON "system_relation_sorts" ("relation_id", "source_sort");
-- Create "system_relation_symbols" table
CREATE TABLE "system_relation_symbols" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "relation_id" uuid NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  "source_symbol" character varying(128) NOT NULL,
  "target_symbol" character varying(128) NOT NULL,
  CONSTRAINT "pk_system_relation_symbols" PRIMARY KEY ("id"),
  CONSTRAINT "fk_system_relation_symbols_relation_id_system_relations" FOREIGN KEY ("relation_id") REFERENCES "system_relations" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_system_relation_symbols_relation_id" to table: "system_relation_symbols"
CREATE INDEX "ix_system_relation_symbols_relation_id" ON "system_relation_symbols" ("relation_id");
-- Create index "uq_system_relation_symbols_source" to table: "system_relation_symbols"
CREATE UNIQUE INDEX "uq_system_relation_symbols_source" ON "system_relation_symbols" ("relation_id", "source_symbol");
