-- Create "label_claims" table
CREATE TABLE "label_claims" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "formal_system_id" uuid NOT NULL,
  "subject" character varying(128) NOT NULL,
  "kind" character varying(64) NOT NULL,
  "object" character varying(128) NULL,
  "position" integer NOT NULL DEFAULT 0,
  CONSTRAINT "pk_label_claims" PRIMARY KEY ("id"),
  CONSTRAINT "fk_label_claims_formal_system_id_formal_systems" FOREIGN KEY ("formal_system_id") REFERENCES "formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_label_claims_formal_system_id" to table: "label_claims"
CREATE INDEX "ix_label_claims_formal_system_id" ON "label_claims" ("formal_system_id");
-- Create index "ix_label_claims_object_kind" to table: "label_claims"
CREATE INDEX "ix_label_claims_object_kind" ON "label_claims" ("object", "kind");
-- Create index "ix_label_claims_system_subject" to table: "label_claims"
CREATE INDEX "ix_label_claims_system_subject" ON "label_claims" ("formal_system_id", "subject");
-- Carry the `usage … avoids` rows across before dropping their table. Atlas
-- plans a schema diff and cannot know that `label_claims` *is* `label_avoidances`
-- generalised, so it wrote a bare DROP — which silently costs an existing corpus
-- 3,107 rows that only a full re-import can rebuild (`scripts/rebuild_markup.py`
-- re-reads stored prose and never sees a `$j` block). Found in review.
INSERT INTO "label_claims" ("id", "formal_system_id", "subject", "kind", "object", "position")
SELECT "id", "formal_system_id", "label", 'usage_avoids', "avoided", "position"
FROM "label_avoidances";
-- Drop "label_avoidances" table
DROP TABLE "label_avoidances";
