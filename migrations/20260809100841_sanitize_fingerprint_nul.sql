-- Rewrite promoted-theorem fingerprints to the NUL-free form.
--
-- A fingerprint feature carries the signature skeleton's hole marker, a NUL
-- byte, which app/db/fingerprints.py now stores as the \u001d escape.
-- Postgres cannot extract a json value that contains a \u0000 escape
-- (it raises rather than skips, even for a clean element), so a fingerprint the
-- storage PR wrote before this would fault the goal-directed retrieval query.
-- This rewrites those rows in place to exactly what the current encoder emits:
-- a text replace of the escape json.dumps produces. No-op for rows already
-- NUL-free or NULL. Data only, no schema change.
UPDATE "promoted_theorems"
SET "conclusion_fingerprint" = replace("conclusion_fingerprint", '\u0000', '\u001d')
WHERE "conclusion_fingerprint" LIKE '%\u0000%';
