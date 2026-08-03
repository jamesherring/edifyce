-- Create "notation_rules" table
CREATE TABLE "notation_rules" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "formal_system_id" uuid NOT NULL,
  "notation" character varying(64) NOT NULL,
  "name" character varying(128) NOT NULL,
  "constructor" character varying(512) NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  CONSTRAINT "pk_notation_rules" PRIMARY KEY ("id"),
  CONSTRAINT "fk_notation_rules_formal_system_id_formal_systems" FOREIGN KEY ("formal_system_id") REFERENCES "formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_notation_rules_constructor" to table: "notation_rules"
CREATE INDEX "ix_notation_rules_constructor" ON "notation_rules" ("constructor");
-- Create index "ix_notation_rules_formal_system_id" to table: "notation_rules"
CREATE INDEX "ix_notation_rules_formal_system_id" ON "notation_rules" ("formal_system_id");
-- Create index "uq_notation_rules_system_notation_name" to table: "notation_rules"
CREATE UNIQUE INDEX "uq_notation_rules_system_notation_name" ON "notation_rules" ("formal_system_id", "notation", "name");
-- Create "notation_rule_pieces" table
CREATE TABLE "notation_rule_pieces" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "rule_id" uuid NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  "kind" character varying(8) NOT NULL,
  "text" character varying(512) NOT NULL,
  CONSTRAINT "pk_notation_rule_pieces" PRIMARY KEY ("id"),
  CONSTRAINT "fk_notation_rule_pieces_rule_id_notation_rules" FOREIGN KEY ("rule_id") REFERENCES "notation_rules" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_notation_rule_pieces_rule_id" to table: "notation_rule_pieces"
CREATE INDEX "ix_notation_rule_pieces_rule_id" ON "notation_rule_pieces" ("rule_id");
-- Create index "uq_notation_rule_pieces_rule_position" to table: "notation_rule_pieces"
CREATE UNIQUE INDEX "uq_notation_rule_pieces_rule_position" ON "notation_rule_pieces" ("rule_id", "position");
-- Create "notation_rule_pins" table
CREATE TABLE "notation_rule_pins" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "rule_id" uuid NOT NULL,
  "slot" character varying(512) NOT NULL,
  "constructor" character varying(512) NOT NULL,
  CONSTRAINT "pk_notation_rule_pins" PRIMARY KEY ("id"),
  CONSTRAINT "fk_notation_rule_pins_rule_id_notation_rules" FOREIGN KEY ("rule_id") REFERENCES "notation_rules" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_notation_rule_pins_rule_id" to table: "notation_rule_pins"
CREATE INDEX "ix_notation_rule_pins_rule_id" ON "notation_rule_pins" ("rule_id");
-- Create index "uq_notation_rule_pins_rule_slot" to table: "notation_rule_pins"
CREATE UNIQUE INDEX "uq_notation_rule_pins_rule_slot" ON "notation_rule_pins" ("rule_id", "slot");
