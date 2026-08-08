-- Enable pg_trgm (required by every gin_trgm_ops index below). Hand-added for
-- the reason the initial migration records of "vector": the community Atlas
-- build omits CREATE EXTENSION from diffs, so re-add this and run
-- `atlas migrate hash` if this migration is regenerated.
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
-- Create index "ix_label_descriptions_label_trgm" to table: "label_descriptions"
CREATE INDEX "ix_label_descriptions_label_trgm" ON "label_descriptions" USING GIN ("label" gin_trgm_ops);
-- Create index "ix_label_descriptions_text_trgm" to table: "label_descriptions"
CREATE INDEX "ix_label_descriptions_text_trgm" ON "label_descriptions" USING GIN ("text" gin_trgm_ops);
-- Create index "ix_label_descriptions_title_trgm" to table: "label_descriptions"
CREATE INDEX "ix_label_descriptions_title_trgm" ON "label_descriptions" USING GIN ("title" gin_trgm_ops);
-- Create index "ix_proofs_description_trgm" to table: "proofs"
CREATE INDEX "ix_proofs_description_trgm" ON "proofs" USING GIN ("description" gin_trgm_ops);
-- Create index "ix_proofs_name_trgm" to table: "proofs"
CREATE INDEX "ix_proofs_name_trgm" ON "proofs" USING GIN ("name" gin_trgm_ops);
-- Create index "ix_proofs_title_trgm" to table: "proofs"
CREATE INDEX "ix_proofs_title_trgm" ON "proofs" USING GIN ("title" gin_trgm_ops);
