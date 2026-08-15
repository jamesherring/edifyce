-- Modify "side_conditions" table: generalise the owner from a definition to a
-- definition *or* a rule. `definition_id` becomes nullable, a nullable `rule_id`
-- is added, and a CHECK enforces exactly one owner per node.
ALTER TABLE "public"."side_conditions" ALTER COLUMN "definition_id" DROP NOT NULL, ADD COLUMN "rule_id" uuid NULL, ADD CONSTRAINT "ck_side_conditions_one_owner" CHECK ((definition_id IS NULL) <> (rule_id IS NULL)), ADD CONSTRAINT "fk_side_conditions_rule_id_rules" FOREIGN KEY ("rule_id") REFERENCES "public"."rules" ("id") ON UPDATE NO ACTION ON DELETE CASCADE;
-- Create index "ix_side_conditions_rule_id" to table: "side_conditions"
CREATE INDEX "ix_side_conditions_rule_id" ON "public"."side_conditions" ("rule_id");
-- Create index "ix_side_conditions_rule_kind" to table: "side_conditions"
CREATE INDEX "ix_side_conditions_rule_kind" ON "public"."side_conditions" ("rule_id", "kind");
-- Create index "uq_side_conditions_rule_root" to table: "side_conditions"
CREATE UNIQUE INDEX "uq_side_conditions_rule_root" ON "public"."side_conditions" ("rule_id") WHERE (parent_id IS NULL);
