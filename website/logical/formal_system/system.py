"""The top-level :class:`FormalSystem`."""

from copy import copy

from ..kernel.definitions import Definition as KernelDefinition
from ..kernel.terms import from_match
from ..matching import Context, Match, Pattern, StringPattern, UnionPattern
from .promotion import PromotedTheorem
from .proof import Proof


def _line_field(match: Match, field: str) -> Match:
    # Project a LineType's declared formula/reference field off a line match.
    # The reserved value "self" denotes the whole match (an axiom asserting its
    # entire formula); any other value names a matched sub-field to read.
    if field == "self":
        return match
    return match.field(field)


class FormalSystem:
    """A formal system."""

    def __init__(self, name, line_types=None, inference_rules=None, build_context=None, context=None):

        # The name of the system
        self.name = name

        # A list of line types
        self.line_types = line_types if line_types is not None else []

        # A list of valid inference rules for the system
        self.inference_rules = inference_rules if inference_rules is not None else []

        # The system's definitional axioms (kernel Definitions). A proof cites
        # one by label, or lets the generic keyword search them all. Held here
        # rather than in the proof context because they are fixed once the system
        # is built - the context carries only the *notations* that let a defined
        # form parse (see matching.DefinedNotation).
        self.definitions: list[KernelDefinition] = []

        # Proved/imported theorems registered for schematic reuse, keyed by label.
        # Kept out of `inference_rules` so the system's *primitive* rules stay
        # distinguishable from its (potentially very many) derived theorems; the
        # reference resolver builds an ephemeral rule per citation. See promotion.
        self.promoted_theorems: dict[str, PromotedTheorem] = {}

        # The context the system was assembled in (see build_context)
        self.build_context = build_context

        # Per declared definition, in spec order, whether it layered: i.e. its
        # defining form was recognised given the definitions before it. The
        # declarative builder sets this; it stays empty for systems built another
        # way. Keyed by position (not by notation) so callers can tell two
        # distinct definitions apart even when they share a defined form.
        self.definition_layering: list[bool] = []

        # A pattern dictionary of all the patterns used in build context
        self.pattern_dictionary = {}

        # Default proof context
        self.context = Context(
            logical=context if context is not None else {}
        )

    def build_pattern_dictionary(self):
        # Build the pattern dictionary using items included in the build context

        if self.build_context is None:
            return

        def add_pattern(dct, pattern):
            # Add a pattern to the dictionary

            if pattern.url_id in dct:
                return

            # Add the pattern to the dictionary
            dct[pattern.url_id] = pattern

            # Look for subpatterns
            if isinstance(pattern, StringPattern):
                for sub_pattern in pattern.variables.values():
                    add_pattern(dct, sub_pattern)

            elif isinstance(pattern, UnionPattern):
                for sub_pattern in pattern.patterns:
                    add_pattern(dct, sub_pattern)

        # Look in the build dictionary variables for patterns
        for item in self.build_context.variables.values():
            if not isinstance(item, Pattern):
                continue

            # Add the pattern
            add_pattern(self.pattern_dictionary, item)

    def parse(self, text, proof=None, context=None):
        # Parse the text into a proof. To let the proof cite lemmas from other
        # proofs, build the `Proof` yourself, seed its `reference_context` with
        # them, and pass it as `proof` (see app/routers/proofs.py).
        #
        # Two steps, deliberately separable: read each line's *content* off the
        # grammar, then check the proof those lines make. Only the first step
        # needs the text — everything it produces (line type, formula term,
        # formula string, citation string) is also what a stored proof line
        # carries, so a caller that has those rows can populate the lines itself
        # and call `check_proof` directly, with no parse at all. See
        # docs/verification-from-rows.md.
        if proof is None:
            proof = Proof(formal_system=self)

        if context is None:
            context = copy(self.context)

        for raw in text.split("\n"):
            proof_line = proof.add_proof_line(raw.rstrip(), context)
            if not proof_line.empty:
                self.read_line(proof_line, context)

        return self.check_proof(proof, context)

    def read_line(self, proof_line, context):
        """Populate one line's content from its text, against this grammar.

        Sets exactly what a check needs and nothing derived: the matched line
        type, the formula as a kernel term (and its flat string, for the
        string-rewriting rule path), and the citation string. Numbering, scope
        and justification are `check_proof`'s, because they depend on the other
        lines and this does not.
        """
        # Assume valid unless we find an issue
        proof_line.valid = True

        line = proof_line.text.rstrip()

        found = False
        # Check the line is of a given line type
        for line_type in self.line_types:

            line = line.lstrip()
            result = line_type.parse_line(line, context)

            if result is None:
                continue

            # Otherwise meets this line type
            found = True

            # Record the line_type of this line
            proof_line.line_type = line_type

            # Project the line type's declared formula/reference fields off
            # the match. (`label`, `display` and axiom-marking are handled by
            # ProofLine's defaults and the `behaviour: axiom` line type - not
            # by string `get_by_path` accessors, which could no longer be
            # defined since the accessor-function syntax was removed.)
            if line_type.formula_field is not None:
                # The logical formula is the sub-field the line type declares
                # (or the whole match, for `formula: self`). Project it into a
                # kernel term *here*, while the match is still in hand: the
                # term is what every later check runs on, and the match itself
                # does not outlive this loop body.
                try:
                    formula = _line_field(result, line_type.formula_field)
                except KeyError:
                    # The line type names a field this line has no sub-match
                    # for: the line simply carries no formula.
                    formula = None

                if formula is not None:
                    proof_line.formula_string = formula.string
                    try:
                        proof_line.formula_term = from_match(formula)
                    except Exception as exc:
                        # The parse produced a shape the term layer cannot
                        # read. That used to surface as a raise out of the
                        # whole parse, from whichever rule check projected it
                        # first; failing the one line names where the problem
                        # is and lets the rest of the proof still report.
                        proof_line.valid = False
                        proof_line.invalid_message = f"Could not read the formula on this line: {exc}"

            if line_type.reference_field is not None:
                # The citation reference is the declared sub-field.
                try:
                    reference_match = _line_field(result, line_type.reference_field)
                except KeyError:
                    reference_match = None

                if reference_match is not None:
                    proof_line.reference_string = reference_match.string
                    proof_line.reference_string_display = reference_match.string

            # No need to check other line types
            break

        if not found:
            # The line doesn't match any of the line types. Invalid proof
            proof_line.invalid_message = "Could not parse line."
            proof_line.valid = False

    def check_proof(self, proof, context=None):
        """Check a proof whose lines are already populated, and return it.

        The half of `parse` that is not parsing: number each line, place it in
        its subproof, justify it, then read the proof's verdict off the lines.
        Public because a proof loaded from its stored rows arrives here with the
        same fields `read_line` would have set, and needs no text.

        The three steps stay interleaved **per line**, exactly as parsing does
        them. That ordering is load-bearing: a discharge cites its subproof by
        the opener's line number, and what stops it reaching a subproof *below*
        it is that later lines are not numbered or scoped yet when it runs.
        """
        if context is None:
            context = copy(self.context)

        for proof_line in proof.proof_lines:
            if proof_line.empty:
                # Ignore blank lines
                continue

            # Give the line its citation number. Done here, after the line type
            # is known, because whether a line can be cited depends on it.
            proof.assign_line_number(proof_line)

            # Place the line in its subproof (a no-op for systems that declare
            # no scope openers - every line then lands in the root scope).
            proof.assign_scope(proof_line)

            if proof_line.line_type is not None:
                # Execute the proof line
                proof_line.execute(context)

        # Check if the proof is valid or has warnings

        proof.valid = True
        proof.has_warnings = False

        for line in proof.proof_lines:
            if not line.valid:
                proof.valid = False
                break

        for line in proof.proof_lines:
            if line.warning_message is not None:
                proof.has_warnings = True
                break

        return proof

    def add_definition(self, definition: KernelDefinition) -> None:
        # Register a definitional axiom. Labels are checked for uniqueness by the
        # builder, so a citation resolves to exactly one.
        self.definitions.append(definition)

    def add_inference_rule(self, rule):
        # Add an inference rule

        # Remove existing inference rules with the same label
        self.inference_rules = [ir for ir in self.inference_rules if not ir.label == rule.label]

        # Add the new rule
        self.inference_rules.append(rule)

    def promote(self, theorem: PromotedTheorem) -> None:
        # Register a proved/imported theorem for schematic reuse under its label.
        # Deliberately separate from `inference_rules`: a citation of this label
        # resolves to an ephemeral rule built from the theorem (see
        # Proof.get_reference), so no per-theorem rule is persisted among the
        # system's primitives.
        self.promoted_theorems[theorem.label] = theorem

    def add_line_type(self, line_type):
        # Add a line type

        # Remove existing line types with the same name
        self.line_types = [lt for lt in self.line_types if not lt.name == line_type.name]

        # Add the new line type
        self.line_types.append(line_type)

    def __str__(self):
        return self.name
