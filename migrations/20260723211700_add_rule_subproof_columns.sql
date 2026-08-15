-- Modify "rules" table
ALTER TABLE "rules" ADD COLUMN "subproof_derive" character varying(512) NULL, ADD COLUMN "subproof_assume" character varying(512) NULL, ADD COLUMN "subproof_fresh" character varying(512) NULL;
