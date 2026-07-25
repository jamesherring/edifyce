-- Modify "line_types" table
ALTER TABLE "line_types" ADD COLUMN "behaviour" character varying(16) NOT NULL DEFAULT 'logical';
