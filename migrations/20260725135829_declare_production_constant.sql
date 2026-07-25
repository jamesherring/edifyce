-- Modify "symbols" table
ALTER TABLE "symbols" ADD COLUMN "denotes_constant" boolean NOT NULL DEFAULT false;
