-- Modify "rules" table
ALTER TABLE "rules" ADD COLUMN "matching" character varying(16) NOT NULL DEFAULT 'structural';
