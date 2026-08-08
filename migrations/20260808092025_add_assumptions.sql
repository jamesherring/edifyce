-- Create "assumptions" table
CREATE TABLE "assumptions" (
  "theorem_id" uuid NOT NULL,
  "reason" text NOT NULL,
  "source" text NULL,
  "asserted_by_id" uuid NULL,
  "created_at" timestamptz NOT NULL DEFAULT now(),
  "updated_at" timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT "pk_assumptions" PRIMARY KEY ("theorem_id"),
  CONSTRAINT "fk_assumptions_asserted_by_id_users" FOREIGN KEY ("asserted_by_id") REFERENCES "users" ("id") ON UPDATE NO ACTION ON DELETE SET NULL,
  CONSTRAINT "fk_assumptions_theorem_id_promoted_theorems" FOREIGN KEY ("theorem_id") REFERENCES "promoted_theorems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_assumptions_asserted_by_id" to table: "assumptions"
CREATE INDEX "ix_assumptions_asserted_by_id" ON "assumptions" ("asserted_by_id");
-- Create "theorem_assumptions" table
CREATE TABLE "theorem_assumptions" (
  "theorem_id" uuid NOT NULL,
  "assumption_id" uuid NOT NULL,
  CONSTRAINT "pk_theorem_assumptions" PRIMARY KEY ("theorem_id", "assumption_id"),
  CONSTRAINT "fk_theorem_assumptions_assumption_id_promoted_theorems" FOREIGN KEY ("assumption_id") REFERENCES "promoted_theorems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE,
  CONSTRAINT "fk_theorem_assumptions_theorem_id_promoted_theorems" FOREIGN KEY ("theorem_id") REFERENCES "promoted_theorems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_theorem_assumptions_assumption" to table: "theorem_assumptions"
CREATE INDEX "ix_theorem_assumptions_assumption" ON "theorem_assumptions" ("assumption_id");
