-- Modify "symbols" table
ALTER TABLE "symbols" ADD COLUMN "atom_value" character varying(512) NULL, ADD COLUMN "atom_base" character varying(128) NULL;
