-- Modify "definitions" table
ALTER TABLE "definitions" ADD COLUMN "justification_label" character varying(64) NULL, ADD COLUMN "justification_statement" character varying(512) NULL;
