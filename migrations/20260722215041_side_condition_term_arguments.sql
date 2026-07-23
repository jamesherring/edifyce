-- Modify "side_conditions" table: a predicate argument may now be a literal term
-- expression, not just a metavariable name. Its surface string is stored in the
-- (widened) left_name/right_name columns, and the new left_is_term/right_is_term
-- flags record which arguments are terms (vs metavariables checked against the
-- owner's bindings).
ALTER TABLE "public"."side_conditions" ALTER COLUMN "left_name" TYPE character varying(512), ALTER COLUMN "right_name" TYPE character varying(512), ADD COLUMN "left_is_term" boolean NOT NULL DEFAULT false, ADD COLUMN "right_is_term" boolean NOT NULL DEFAULT false;
