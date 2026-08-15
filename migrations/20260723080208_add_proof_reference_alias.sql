-- Modify "proof_references" table
ALTER TABLE "proof_references" ADD COLUMN "alias" character varying(64) NOT NULL DEFAULT '', ADD COLUMN "position" integer NOT NULL DEFAULT 0;
-- Backfill a distinct alias per citing proof so the unique index below can build
-- even if pre-existing edges were present (the column default would otherwise
-- give every edge the same empty alias). A no-op on an empty table.
UPDATE "proof_references" AS pr
SET "alias" = 'ref_' || sub.rn, "position" = sub.rn - 1
FROM (
  SELECT "proof_id", "references_id",
         row_number() OVER (PARTITION BY "proof_id" ORDER BY "references_id") AS rn
  FROM "proof_references"
) AS sub
WHERE pr."proof_id" = sub."proof_id" AND pr."references_id" = sub."references_id";
-- Create index "uq_proof_references_proof_alias" to table: "proof_references"
CREATE UNIQUE INDEX "uq_proof_references_proof_alias" ON "proof_references" ("proof_id", "alias");
