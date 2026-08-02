-- Create "notation_pieces" table
CREATE TABLE "notation_pieces" (
  "id" uuid NOT NULL DEFAULT gen_random_uuid(),
  "formal_system_id" uuid NOT NULL,
  "notation" character varying(64) NOT NULL,
  "constructor" character varying(512) NOT NULL,
  "position" integer NOT NULL DEFAULT 0,
  "kind" character varying(8) NOT NULL,
  "text" character varying(512) NOT NULL,
  CONSTRAINT "pk_notation_pieces" PRIMARY KEY ("id"),
  CONSTRAINT "fk_notation_pieces_formal_system_id_formal_systems" FOREIGN KEY ("formal_system_id") REFERENCES "formal_systems" ("id") ON UPDATE NO ACTION ON DELETE CASCADE
);
-- Create index "ix_notation_pieces_formal_system_id" to table: "notation_pieces"
CREATE INDEX "ix_notation_pieces_formal_system_id" ON "notation_pieces" ("formal_system_id");
-- Create index "uq_notation_pieces_system_notation_constructor_position" to table: "notation_pieces"
CREATE UNIQUE INDEX "uq_notation_pieces_system_notation_constructor_position" ON "notation_pieces" ("formal_system_id", "notation", "constructor", "position");
