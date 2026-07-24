from website.logical.matching import *
from website.logical.matching import Pattern
from website.logical.formal_system import (
    FormalSystem,
    InferenceRule,
    LineType,
    ProofLine,
    PromotedTheorem,
    SubproofSchema,
)
from website.logical.formal_system.side_condition_syntax import parse_side_condition
from website.logical.kernel import And, Node, Var, from_match, intern
from collections.abc import Mapping, Sequence
from copy import copy, deepcopy
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from website.logical.kernel.terms import Term


@dataclass(eq=False)
class PendingDefinition:
    """A definition staged during compilation, resolved into a matching.Definition later."""

    lower: str
    higher: str
    pattern: Pattern
    variables: dict = field(default_factory=dict)
    # Bound variables of the defining form as (name, sort-name) pairs, and
    # kernel-vocabulary provisos as raw source lines. Both are resolved against
    # the (complete) context when the definition is finalised, not here, so a
    # sort or metavariable defined later in the block still resolves.
    fresh: list = field(default_factory=list)
    where_strings: list = field(default_factory=list)
    # Optional name a proof cites the definition by (`[<label>, <line>]`).
    label: str | None = None


def get_inherited_system(code: str) -> str | None:
    # Get referenced systems from the given code

    slug = None

    lines = code.split("\n")
    for line in lines:
        line = line.strip()
        if line.startswith("inherit "):
            slug = line[8:]

    return slug


def compile(code: str, system_dict: dict | None = None) -> dict:
    # Compile the given code string into a tree. Return the formal system.

    # Optionally specify a system_dict of reference systems

    # Create an initial context
    context = FormalSystemContext()
    context.system_dict = system_dict if system_dict is not None else {}

    # Create a root node
    root = AbstractSyntaxTree()
    root.add_lines(code.split("\n"))

    context = root.run(context)

    # Return error log if there are errors
    if len(context.error_log) > 0:
        return {"errors": context.error_log}

    # Return the formal system
    for item in context.variables.values():
        if isinstance(item, FormalSystem):
            return {"system": item}

    # Return an empty formal system
    return {"system": FormalSystem(name="")}


def build_schema_pattern(text: str, context, name: str):
    # Build a rule-schema pattern from a source token. A bare constant atom
    # (e.g. a falsum `⊥`) resolves to its *declared* AtomPattern, so the rule's
    # literal and the proof line's atom are the same constructor on the term
    # representation - otherwise a StringPattern literal and the atom would be
    # different constructors and the (now term-based) checker would reject the
    # step. A referenced pattern name is used directly; anything else becomes a
    # StringPattern template with the ambient string variables applied.
    if text in context.variables:
        return context.variables[text]

    for candidate in context.variables.values():
        if isinstance(candidate, AtomPattern) and candidate.is_constant and candidate.is_member(text):
            return candidate

    pattern = StringPattern(name=name, pattern=text)
    pattern.add_variables(context.string_variables)

    # Precompute the schema's nested kernel term. A template like a Hilbert axiom
    # `(p → (q → p))` denotes an implication whose right side is itself an
    # implication, but the StringPattern is a single flat production. The
    # term-based checker matches a schema against a proof formula by comparing
    # term trees, and a proof formula is built compositionally from the system's
    # productions, so the schema must project to the *same* nested tree. Parse
    # the template against the productions (with the rule's variables treated as
    # metavariables) once, here, and stash the resulting term; _schema_term uses
    # it. None when the template is a bare variable (from_pattern already nests
    # trivially) or nothing parses it (fall back to the flat projection).
    pattern.schema_term = compose_schema_term(pattern, context)
    return pattern


def compose_schema_term(pattern: Pattern, context) -> "Term | None":
    # Project a compound rule-schema template into its nested kernel term by
    # parsing it against the system's productions. See build_schema_pattern.
    if not pattern.variable_locations or not pattern.non_variable_locations:
        # A bare variable/sort (no literal structure) needs no compositional
        # parse - from_pattern projects it correctly already.
        return None

    # Match against the system's productions only, never its staged definitions.
    # During compilation `context.definitions` holds unresolved PendingDefinition
    # records (finalised at the end of the formal-system block), so letting the
    # parse fall through to a definition-unfold would call `.match` on one and
    # crash. Composition is about productions; a schema recognisable only via a
    # definition simply falls back to the flat projection.
    parse_context = copy(context)
    parse_context.definitions = []

    for candidate in context.variables.values():
        if isinstance(candidate, UnionPattern):
            match = candidate.match(pattern.pattern, parse_context)
            if match is not None:
                return _revariabilise(from_match(match, parse_context), context.string_variables)

    return None


def _revariabilise(term: "Term", metavariables: dict) -> "Term":
    # Re-mark the rule's metavariables in a compositionally-parsed schema term.
    # Some slots - notably a setvar matched by a RegexPattern, which (unlike a
    # UnionPattern) does not consult string_variables - come back from the parse
    # as ground leaves rather than variables. Turn any leaf whose literal is a
    # declared metavariable into the corresponding Var, so a schema like the ∀I
    # deduction `∀x p` keeps `x` schematic (able to bind, and to be tied to the
    # subproof's eigenvariable) instead of fixing it to the literal token "x".
    def walk(node):
        if isinstance(node, Node):
            if node.literal is not None and node.literal in metavariables:
                return Var(node.literal, metavariables[node.literal])
            if node.children:
                return Node(
                    pattern=node.pattern,
                    children={label: walk(child) for label, child in node.children.items()},
                    literal=node.literal,
                    sort=node.sort,
                )
        return node

    return intern(walk(term))


def _parse_fresh_bindings(text: str) -> list[tuple[str, str]]:
    # Parse a `fresh` clause into (name, sort-name) pairs, same shape as a `with`
    # clause: comma-separated names, each group ending in `as <sort>` applies that
    # sort to the names accumulated so far. E.g. "z as setvar" -> [("z","setvar")];
    # "x, y as setvar" -> [("x","setvar"),("y","setvar")]. Sorts are resolved
    # later, against the completed context.
    bindings: list[tuple[str, str]] = []
    pending: list[str] = []
    for part in text.split(","):
        part = part.strip()
        if " as " in part:
            name, sort = part.split(" as ", 1)
            pending.append(name.strip())
            bindings.extend((n, sort.strip()) for n in pending)
            pending = []
        elif part:
            pending.append(part)
    return bindings


def _resolve_sort(sort_name: str, context) -> Pattern:
    # Resolve a `fresh` binding's sort name to a pattern in the completed context.
    pattern = context.variables.get(sort_name)
    if not isinstance(pattern, Pattern):
        raise Exception(f"Definition `fresh` sort '{sort_name}' is not a pattern.")
    return pattern


def _combine_side_conditions(where_strings: list, context):
    # Parse a definition's `where` provisos into a single kernel side-condition
    # (their conjunction), or None when there are none. Each line uses the same
    # closed vocabulary as a rule's side_conditions (see side_condition_syntax).
    if not where_strings:
        return None
    conditions = [parse_side_condition(text, context) for text in where_strings]
    return conditions[0] if len(conditions) == 1 else And(tuple(conditions))


def _theorem_schema(text: str, context: "FormalSystemContext", name: str) -> Pattern:
    # Build one schema pattern for a promoted theorem's statement or premise, and
    # reject a *ground* compound - literal structure but no metavariables.
    # compose_schema_term keys on a metavariable, so such a statement composes no
    # nested term, and its flat projection cannot match a nested proof formula: it
    # would be a theorem that never applies. A statement *with* metavariables
    # projects structurally even when nothing is composed - notably defined
    # notation, whose flat projection does apply (a `sub` alias matches an
    # `a sub b` line) - so those are kept. Supporting ground compound conclusions
    # (Metamath closed theorems like `2 e. RR`) is future work.
    pattern = build_schema_pattern(text, context, name)
    if (
        isinstance(pattern, StringPattern)
        and pattern.schema_term is None
        and pattern.non_variable_locations
        and not pattern.variable_locations
    ):
        raise ValueError(
            f"Statement {text!r} has no metavariables and composes no schema term "
            "(a ground/atomic compound); it is not yet supported - promote it as a rule."
        )
    return pattern


def promote_from_source(
    system: FormalSystem,
    label: str,
    statement: str,
    metavariables: Mapping[str, str],
    premises: Sequence[str] = (),
    distinct: Sequence[str] = (),
    matching: str = "structural",
) -> PromotedTheorem:
    """Build a :class:`PromotedTheorem` from a proved/imported theorem's source.

    The import-facing promotion route. The theorem is given as source text in the
    system's own grammar: its conclusion ``statement``, its hypotheses
    ``premises``, its ``metavariables`` (name -> sort name), and its distinct-
    variable provisos ``distinct`` (each a ``disjoint(...)`` line). A Metamath
    ``$p`` maps here directly - ``$e`` -> ``premises``, ``$f`` -> ``metavariables``,
    ``$d`` -> ``distinct``. The metavariables are re-instantiated at each citation
    by unification and the provisos enforced against that binding (see
    :class:`~website.logical.formal_system.promotion.PromotedTheorem`).

    Unlike generalising a concrete proof line by renaming leaves, this parses the
    statement against the grammar with the metavariables held schematic, so a
    formula metavariable may stand for a *compound* (the usual case).

    ``matching`` sets how a citation is checked, mirroring ``InferenceRule``:
    ``"structural"`` (term unification, the default) or ``"string"`` for a theorem
    proved in a semi-Thue / string-rewriting system (e.g. MIU), which must stay
    string-checked to remain applicable.

    Register the result with :meth:`FormalSystem.promote` to make it citable. The
    theorem is not added to the system's primitive ``inference_rules``.

    Raises :class:`ValueError` if the system has no build context, if a sort name
    is not a declared pattern of the system, or if a conclusion/premise is a
    ground compound (literal structure but no metavariables) - a closed theorem
    such as Metamath's ``2 e. RR``, not yet supported here; promote it as a rule.
    As with an authored rule schema, a statement naming an *undefined* symbol is
    not rejected here - it simply yields a theorem that never applies - so
    validate imported statements upstream.
    """
    if system.build_context is None:
        raise ValueError("Cannot promote a theorem against a system with no build context.")

    # Copy the context so the theorem's metavariables can be set in
    # string_variables without mutating the system's own build context.
    context = copy(system.build_context)
    string_variables: dict[str, Pattern] = {}
    for name, sort_name in metavariables.items():
        sort = system.build_context.variables.get(sort_name)
        if not isinstance(sort, Pattern):
            raise ValueError(
                f"Metavariable {name!r} names sort {sort_name!r}, which is not a "
                "declared pattern of the system."
            )
        string_variables[name] = sort
    context.string_variables = string_variables

    deduction = _theorem_schema(statement, context, label)
    antecedents = tuple(
        _theorem_schema(text, context, f"{label}.premise{index}")
        for index, text in enumerate(premises)
    )
    side_conditions = tuple(parse_side_condition(line, context) for line in distinct)

    return PromotedTheorem(
        label=label,
        deduction=deduction,
        antecedents=antecedents,
        side_conditions=side_conditions,
        variables=dict(string_variables),
        matching=matching,
    )


@dataclass(eq=False)
class FormalSystemContext:

    # Variables in the code
    variables: dict = field(default_factory=dict)

    # String variables for inside patterns
    string_variables: dict = field(default_factory=dict)

    # Definitions created along the way
    definitions: list = field(default_factory=list)

    # Current object at a point in the code
    current_object: object = None

    # Proof context
    proof_context: dict = field(default_factory=dict)

    # External systems for reference
    system_dict: dict = field(default_factory=dict)

    # Error log
    error_log: list = field(default_factory=list)

    def inherit(self, parent):
        # Inherit from parent context

        self.variables.update(parent.variables)
        self.definitions.extend(parent.definitions)
        self.proof_context.update(parent.proof_context)
        self.system_dict.update(parent.system_dict)

        # Don't inherit string_variables or current_object

        # Inherit union patterns
        for pattern in self.variables.values():
            if not isinstance(pattern, UnionPattern):
                continue

            # Pattern is a union pattern. Set the inheritance
            pattern.inherits = deepcopy(pattern)

    def __copy__(self):
        new_context = FormalSystemContext()

        new_context.variables = copy(self.variables)
        new_context.string_variables = copy(self.string_variables)
        new_context.definitions = copy(self.definitions)
        new_context.current_object = self.current_object
        new_context.proof_context = copy(self.proof_context)
        new_context.system_dict = copy(self.system_dict)
        new_context.error_log = copy(self.error_log)

        return new_context


class AbstractSyntaxTree:
    """A node in an abstract syntax tree"""

    def __init__(self, line=None, line_number=0):

        # The line string if it exists
        self.line = line

        # The line number if it exists
        self.line_number = line_number

        # The list of sub-trees
        self.sub_trees = []

        # The parent tree (if it exists)
        self.parent = None

        # The indent level of this line
        self.indent = None
        if self.line is not None:
            self.indent = len(line) - len(line.lstrip())

        # The type of line this is
        self.type = None

        # The error in parsing this line - if any
        self.error = None

    def is_root(self):
        return self.line is None

    def is_leaf(self):
        return len(self.sub_trees) == 0

    def add_lines(self, lines):
        # Parse the given lines into this node

        def add_sub_lines(last_sub_tree, sub_lines):
            # Add the given sub-lines to the last sub tree, if it exists

            if len(sub_lines) == 0:
                return

            real_line = False
            for line in sub_lines:
                if len(line.strip()) > 0:
                    # Non-empty subline exists
                    real_line = True

            if not real_line:
                # All sub-lines are just empty
                return

            if last_sub_tree is None:
                # No last sub tree to add the lines to
                self.error = "Invalid indent"
                return

            # Recursively add the lines
            last_sub_tree.add_lines(sub_lines)

        sub_tree_indent = 0
        if self.indent is not None:
            sub_tree_indent = self.indent + 4

        # Add the lines with the correct indent
        last_sub_tree = None
        sub_lines = []

        for i in range(0, len(lines)):
            line = lines[i]

            if len(line.lstrip()) == 0:
                # No need to worry about blank lines
                sub_lines.append("")
                continue

            sub_tree = AbstractSyntaxTree(line, line_number=i + 1 + self.line_number)

            if sub_tree.indent == sub_tree_indent:

                # Recursively add sub_lines
                add_sub_lines(last_sub_tree, sub_lines)

                # Add the sub tree
                self.sub_trees.append(sub_tree)
                sub_tree.parent = self
                last_sub_tree = sub_tree

                sub_lines = []
                continue

            # Otherwise, add the line to the sub lines stack
            sub_lines.append(line)

        # Add any remaining sub-lines
        add_sub_lines(last_sub_tree, sub_lines)

    def run(self, context=None):
        # Execute this line in the given context

        if context is None:
            # Create a context
            context = FormalSystemContext()

        if self.is_root():
            # Just run the sub trees

            for tree in self.sub_trees:
                tree.run(context)

            return context

        # Otherwise, check what kind of line this is

        # Remove spaces
        stripped = self.line.strip()

        current_object = context.current_object

        # New data to add to inner context
        new_object = None
        new_string_variables = {}

        try:

            if stripped[0] == "#":
                # This is a comment - no need to do anything
                return

            if stripped.startswith("inherit "):
                # Inherit from an existing formal system

                name = stripped[8:]
                if name not in context.system_dict:
                    self.error = f"Could not find formal system with slug: {name}."
                    return

                system = context.system_dict[name]

                # Inherit the system context
                context.inherit(system.build_context)

                # Add inference rules and line types
                if isinstance(current_object, FormalSystem):
                    for ir in system.inference_rules:
                        current_object.add_inference_rule(ir)

                    for lt in system.line_types:
                        current_object.add_line_type(lt)

                    # Add proof context
                    current_object.context.logical.update(deepcopy(system.context.logical))

            elif stripped.startswith("FormalSystem ") and stripped[-1] == ":":
                # Looks like a formal system declaration

                self.type = "FormalSystem"

                name = stripped[13:-1]

                if not self.valid_variable_name(name):
                    self.error = f"Invalid variable name: '{name}'."
                    return

                # Add the formal system to context
                fs = FormalSystem(name=name)
                context.variables[name] = fs

                new_object = fs

            elif stripped == "ProofContext:":
                # Logical proof context definition
                self.type = "ProofContext"
                new_object = current_object.context.logical

            elif stripped.startswith("Abstract "):
                # Create an abstract pattern variable

                self.type = "Abstract"

                names = stripped[9:].split(", ")

                for name in names:
                    if not self.valid_variable_name(name):
                        self.error = f"Invalid variable name: '{name}'."
                        return

                    # Add to context
                    context.variables[name] = AbstractPattern(name=name)

            elif stripped.startswith("Atom ") and ": " in stripped:
                # Inline atom declaration (no regex):
                #   `Atom falsum: ⊥`      -> a constant
                #   `Atom var: p_#`       -> the infinite family p, p_0, p_1, ...
                self.type = "Atom"

                rest = stripped[5:]
                index = rest.index(": ")
                name = rest[:index]
                spec = rest[index + 2:]

                if not self.valid_variable_name(name):
                    self.error = f"Invalid variable name: '{name}'."
                    return

                if spec.endswith("_#"):
                    atom = AtomPattern(name=name, base=spec[:-2])
                else:
                    atom = AtomPattern(name=name, value=spec)

                context.variables[name] = atom
                return

            elif stripped.startswith("Regex ") and stripped[-1] == ":":
                # Create a regex pattern variable

                self.type = "Regex"

                name = stripped[6:-1]

                if not self.valid_variable_name(name):
                    self.error = f"Invalid variable name: '{name}'."
                    return

                # Add to context with placeholder pattern
                pattern = RegexPattern(name=name, pattern="")
                context.variables[name] = pattern

                new_object = pattern

            elif stripped.startswith("Pattern ") and stripped[-1] == ":":
                # String pattern

                self.type = "Pattern"

                name = stripped[8:-1]

                if not self.valid_variable_name(name):
                    self.error = f"Invalid variable name: '{name}'."
                    return

                # Create the pattern
                pattern = StringPattern(name=name, pattern="")
                context.variables[name] = pattern

                new_object = pattern

            elif stripped.startswith("UnionPattern ") and stripped[-1] == ":":
                # Union pattern

                self.type = "UnionPattern"

                name = stripped[13:-1]

                if not self.valid_variable_name(name):
                    self.error = f"Invalid variable name: '{name}'."
                    return

                # Create the union with no patterns to begin with
                union = UnionPattern(name=name, patterns=[])
                context.variables[name] = union

                new_object = union

            elif stripped.startswith("Define ") and " as " in stripped:
                # Definition
                self.type = "Definition"

                remainder = stripped[7:]
                index = remainder.index(" as ")
                higher = remainder[:index]
                lower = remainder[index + 4:]

                # Optional trailing clauses, in source order after the lower form:
                #   Define <higher> as <lower> [fresh <binds>] [where <provisos>] [label <name>]
                # `fresh` declares the defining form's bound variables (so the
                # term checker unfolds capture-avoidingly); `where` carries
                # kernel-vocabulary provisos (see side_condition_syntax); `label`
                # names the definition so a proof can cite it as `[<name>, <line>]`.
                # Peel them off the tail back-to-front so an earlier clause never
                # swallows a later keyword. A lower form must not itself contain
                # these separator words.
                label = None
                if " label " in lower:
                    lower, _, label_text = lower.partition(" label ")
                    label = label_text.strip()

                if " if " in lower:
                    # The legacy string proviso (pseudo-python `Condition`) has been
                    # retired; provisos are now written with `where` and checked
                    # structurally by the kernel.
                    self.error = (
                        "The legacy `if` proviso on definitions is no longer supported; "
                        "use a `where` proviso instead."
                    )
                    return

                where_strings: list[str] = []
                if " where " in lower:
                    lower, _, where_text = lower.partition(" where ")
                    where_strings = [part.strip() for part in where_text.split(";") if part.strip()]

                fresh: list[tuple[str, str]] = []
                if " fresh " in lower:
                    lower, _, fresh_text = lower.partition(" fresh ")
                    fresh = _parse_fresh_bindings(fresh_text)

                if not isinstance(current_object, Pattern):
                    self.error = "Definitions must be created inside a pattern block."
                    return

                # Create the definition - staged for parsing once the pattern block is complete
                context.definitions.append(PendingDefinition(
                    lower=lower,
                    higher=higher,
                    pattern=current_object,
                    variables=dict(context.string_variables),
                    fresh=fresh,
                    where_strings=where_strings,
                    label=label,
                ))

            elif stripped.startswith("LineType ") and stripped[-1] == ":":
                # New linetype

                self.type = "LineType"

                name = stripped[9:-1]

                if not self.valid_variable_name(name):
                    self.error = f"Invalid variable name: '{name}'."
                    return

                # Create the linetype
                new_object = LineType(name=name)

                # Add to formal system
                if type(current_object) is not FormalSystem:
                    raise Exception(f"Cannot add LineType to object of type {type(current_object)!s}.")

                context.variables[name] = new_object

            elif stripped.startswith("InferenceRule ") and stripped[-1] == ":":
                # New InferenceRule

                self.type = "InferenceRule"

                name = stripped[14:-1]

                if not self.valid_variable_name(name):
                    self.error = f"Invalid variable name: '{name}'."
                    return

                # Gather variables
                variables = dict(context.string_variables)

                # Create the rule
                new_object = InferenceRule(name=name, variables=variables)

            elif stripped.startswith("with ") and stripped[-1] == ":":
                # Define string variables

                self.type = "with"

                # Split into parts
                parts = stripped[5:-1].split(", ")

                strings = []
                for part in parts:
                    if " as " in part:
                        # Final string variable and reference

                        final_string, reference = part.split(" as ")
                        strings.append(final_string)

                        if reference not in context.variables:
                            # Can't find reference
                            self.error = f"Could not find pattern with name '{reference}'."
                            return

                        pattern = context.variables[reference]

                        if not isinstance(pattern, Pattern):
                            self.error = f"'{reference}' is not a pattern."
                            return

                        # Add to inner context
                        for s in strings:
                            new_string_variables[s] = pattern

                        # Empty the stack of strings
                        strings = []

                    else:
                        strings.append(part)

            elif stripped in context.variables and type(current_object) is UnionPattern:
                # Get the referenced object

                self.type = "variable"

                obj = context.variables[stripped]

                if type(obj) not in (StringPattern, UnionPattern, RegexPattern, AbstractPattern, AtomPattern):
                    self.error = f"Can't add object of type '{type(obj)!s}' to UnionPattern."
                    return

                # Append the pattern
                current_object.patterns.append(obj)

            elif stripped[-1] == ":" and stripped[:-1] in context.variables:
                # Continue definition of an already defined pattern

                self.type = "PatternContinuation"

                pattern = context.variables[stripped[:-1]]

                if type(pattern) is not UnionPattern:
                    self.error = f"Can't start a block with '{stripped}'."
                    return

                new_object = pattern

            elif stripped[-15:] == ".add_variables:":
                self.type = "add_variables"

                # Get the pattern
                name = stripped[:-15]

                if name not in context.variables:
                    raise Exception(f"Could not find pattern '{name}.")

                # Pattern is a StringPattern or UnionPattern instance
                pattern = context.variables[name]

                # Construct a dictionary of variables to add
                variable_dict = {}
                for sub_tree in self.sub_trees:
                    s = sub_tree.line.strip()
                    if len(s) == 0 or s[0] == "#":
                        continue

                    index = s.find(":")

                    if index == -1:
                        raise Exception(f"Could not parse line '{stripped}'.")

                    name = s[:index]
                    value = s[index + 2:]

                    if value not in context.variables:
                        raise Exception(f"Could not find pattern: '{value}'.")

                    variable_dict[name] = context.variables[value]

                pattern.add_variables(variable_dict)

                return

            elif self.parent.type == "ProofContext":
                # Add the item to proof context

                index = stripped.find(": ")

                if index == -1:
                    raise Exception(f"Could not parse line '{stripped}'.")

                key = stripped[:index]
                value_string = stripped[index + 2:]

                if value_string == "set()":
                    current_object[key] = set()

                elif value_string == "MatchSet()":
                    current_object[key] = MatchSet()

                elif value_string == "dict()":
                    current_object[key] = {}

                else:
                    raise Exception(f"Could not parse value '{value_string}'.")

            elif type(current_object) is StringPattern:
                # Define the pattern
                current_object.set_pattern(stripped)

                # Apply string variables
                current_object.add_variables(context.string_variables)

            elif type(current_object) is UnionPattern:
                # Add a pattern to the union

                if stripped in context.string_variables and isinstance(context.string_variables[stripped], Pattern):
                    # Looks like a reference to another pattern
                    pattern = context.string_variables[stripped]

                else:
                    pattern = StringPattern(name=current_object.name, pattern=stripped)

                    # Add any relevant string variables
                    pattern.add_variables(context.string_variables)

                current_object.patterns.append(pattern)

            elif type(current_object) is RegexPattern:
                # Define the regex pattern
                current_object.pattern = stripped

            elif type(current_object) is LineType:
                # Add an attribute to the line type

                index = stripped.find(":")

                if index == -1:
                    raise Exception(f"Could not parse line '{stripped}'.")

                key = stripped[:index]
                value_string = stripped[index + 2:]

                if key == "pattern":

                    # Get the value
                    if not (value_string in context.variables):
                        raise ValueError(f"Couldn't find {value_string} in variables.")

                    # Update the line type accordingly
                    current_object.pattern = context.variables[value_string]

                elif key == "behaviour":
                    # Update the behaviour
                    current_object.behaviour = value_string

                elif key == "scope":
                    # Update the scope this line opens (orthogonal to behaviour)
                    current_object.scope = value_string

                elif key == "formula":
                    # Which matched sub-field is the logical formula ("self" =
                    # the whole match). Structured replacement for a `formula()`
                    # accessor function.
                    current_object.formula_field = value_string

                elif key == "reference":
                    # Which matched sub-field is the citation reference.
                    current_object.reference_field = value_string

                else:
                    raise Exception(f"Unrecognised parameter for LineType '{key}'.")

            elif self.parent.type == "InferenceRule":
                # Inference rule

                if stripped == "label:":
                    # Add the label
                    label = None
                    for line in self.sub_trees:
                        stripped_line = line.line.strip()
                        if len(stripped_line) > 0 and not stripped_line[0] == "#":
                            label = stripped_line

                    if label is None:
                        raise Exception(f"Could not parse label for '{current_object.name}'.")

                    current_object.label = label
                    return

                if stripped == "antecedents:":
                    # Create the antecedents list

                    for line in self.sub_trees:
                        stripped_line = line.line.strip()

                        if len(stripped_line) > 0 and not stripped_line[0] == "#":
                            # Get the antecedent as a pattern
                            current_object.antecedents.append(
                                build_schema_pattern(stripped_line, context, "antecedent")
                            )

                    return

                elif stripped == "deduction:":
                    # Get the deduction

                    for line in self.sub_trees:
                        stripped_line = line.line.strip()

                        if len(stripped_line) > 0 and not stripped_line[0] == "#":
                            # Get the deduction as a pattern
                            current_object.deduction = build_schema_pattern(
                                stripped_line, context, "deduction"
                            )

                    return

                elif stripped == "subproof:":
                    # A discharge rule consumes a subproof rather than citing
                    # lines: an assumption (or a fresh variable) plus a derived
                    # conclusion. Each sub-key holds a single pattern line.

                    def build_subproof_pattern(text):
                        return build_schema_pattern(text, context, "subproof")

                    assumption_pattern = None
                    conclusion_pattern = None
                    fresh_pattern = None

                    for part in self.sub_trees:
                        header = part.line.strip()
                        if len(header) == 0 or header[0] == "#":
                            continue

                        value = None
                        for sub in part.sub_trees:
                            sub_stripped = sub.line.strip()
                            if len(sub_stripped) > 0 and not sub_stripped[0] == "#":
                                value = sub_stripped

                        if value is None:
                            raise Exception(f"Subproof key '{header}' needs a pattern.")

                        if header == "assume:":
                            assumption_pattern = build_subproof_pattern(value)
                        elif header == "derive:":
                            conclusion_pattern = build_subproof_pattern(value)
                        elif header == "fresh:":
                            fresh_pattern = build_subproof_pattern(value)
                        else:
                            raise Exception(f"Unrecognised subproof key '{header}'.")

                    if conclusion_pattern is None:
                        raise Exception("A subproof rule requires a 'derive:' conclusion.")

                    current_object.subproof_schema = SubproofSchema(
                        conclusion=conclusion_pattern,
                        assumption=assumption_pattern,
                        fresh=fresh_pattern,
                    )
                    return

                elif stripped == "side_conditions:":
                    # Kernel side-conditions: a closed, structural vocabulary
                    # checked against the rule's term binding. Replaces the
                    # legacy condition mini-language for rule provisos. Parsing is
                    # deferred to the formal-system finalisation pass (where the
                    # system's definitions have resolved), so a proviso argument may
                    # use defined notation; here we only collect the raw lines.
                    for line in self.sub_trees:
                        stripped_line = line.line.strip()
                        if len(stripped_line) > 0 and not stripped_line[0] == "#":
                            current_object.pending_side_conditions.append(stripped_line)
                    return

                elif stripped == "allow_extra_antecedents:":
                    # Maybe allow extra antecedents (should be True or False)
                    value = None
                    for line in self.sub_trees:
                        stripped_line = line.line.strip()
                        if stripped_line == "True":
                            value = True
                        elif stripped_line == "False":
                            value = False

                    if value is None:
                        raise Exception(f"Could not parse label for '{current_object.name}'.")

                    current_object.allow_extra_antecedents = value
                    return

                elif stripped == "matching:":
                    # How steps are justified against this rule: "structural"
                    # (term unification, the default) or "string" (associative
                    # matching for a string-rewriting rule; see rules.py).
                    value = None
                    for line in self.sub_trees:
                        stripped_line = line.line.strip()
                        if stripped_line in ("string", "structural"):
                            value = stripped_line

                    if value is None:
                        raise Exception(f"Could not parse 'matching' for '{current_object.name}'.")

                    current_object.matching = value
                    return

                elif stripped == "condition:":
                    # The legacy condition mini-language was removed from rules.
                    # Error the line rather than silently dropping the proviso
                    # (which would be a soundness hazard), and point at the
                    # replacement vocabulary.
                    raise Exception(
                        f"Inference rule '{current_object.name}' uses a 'condition:' block, "
                        "which is no longer supported; use 'side_conditions:' instead."
                    )

            elif type(current_object) in (dict, OrderedDict):
                # Add a key value pair to the dictionary

                index = stripped.find(":")

                if index == -1:
                    # Item can be reference to already defined dictionary
                    if stripped in context.variables and type(context.variables[stripped]) is dict:
                        current_object.update(context.variables[stripped])

                    else:
                        raise Exception(f"Could not parse line '{stripped}'.")

                key = stripped[:index]
                value_string = stripped[index + 2:]

                # Check for strings
                if len(key) >= 2 and (key[0] == key[-1] == "'" or key[0] == key[-1] == '"'):
                    key = key[1:-1]

                if len(value_string) >= 2 and (value_string[0] == value_string[-1] == "'" or
                                               value_string[0] == value_string[-1] == '"'):
                    value_string = value_string[1:-1]

                current_object[key] = value_string

            else:
                # Can't parse line
                self.error = f"Could not parse '{stripped}'."
                return

        except Exception as e:
            # Error running the line
            self.error = str(e)
            return

        # Run any sub trees in a copy of context
        error_log_len = len(context.error_log)
        sub_context = copy(context)

        # Add the new object if it exists
        if new_object is not None:
            sub_context.current_object = new_object

        # Add new string variables
        sub_context.string_variables.update(new_string_variables)

        for tree in self.sub_trees:
            tree.run(sub_context)

            if tree.error is not None:
                context.error_log.append(f"{tree.line_number!s}: {tree.error}")

        # Errors from deeper subtrees accumulate in the copied sub_context; surface
        # them so a malformed nested line (e.g. a bad side-condition) reaches the
        # returned error_log instead of being silently dropped - which would leave
        # a constrained rule unconstrained. Only the entries added below the
        # snapshot are new, so extend rather than reassign.
        context.error_log.extend(sub_context.error_log[error_log_len:])

        # Add inference rules to formal systems
        if isinstance(new_object, InferenceRule) and isinstance(current_object, FormalSystem):
            current_object.add_inference_rule(new_object)

        # Add line types to formal systems
        if isinstance(new_object, LineType) and isinstance(current_object, FormalSystem):
            current_object.add_line_type(new_object)

        # Add definitions to parent context
        context.definitions = sub_context.definitions

        # Add context to formal systems
        if self.type == "FormalSystem":
            new_object.context.variables.update(sub_context.variables)

            # Add in the default definitions
            seen_labels: set[str] = set()
            for defn in context.definitions:

                # A cited definition name must be unambiguous: reject a duplicate
                # label so `[<name>, <line>]` always resolves to one definition.
                if defn.label is not None:
                    if defn.label in seen_labels:
                        context.error_log.append(
                            f"Duplicate definition label '{defn.label}'."
                        )
                        continue
                    seen_labels.add(defn.label)

                # Make a copy of context
                context_copy = copy(new_object.context)

                # Add variables
                context_copy.string_variables.update(defn.variables)

                # Resolve the defining form's bound-variable sorts and any
                # kernel-vocabulary provisos now that the context is complete. A
                # malformed `fresh` sort or `where` proviso is a source error, not
                # a server fault - but this loop runs *outside* run()'s
                # try/except, so catch it here and record a compile error (as the
                # rule side_conditions path does) rather than letting it escape
                # compile() as a 500.
                try:
                    fresh = {
                        name: _resolve_sort(sort, context_copy)
                        for name, sort in defn.fresh
                    }
                    kernel_condition = _combine_side_conditions(defn.where_strings, context_copy)
                except Exception as e:
                    context.error_log.append(f"Definition '{defn.higher}': {e}")
                    continue

                # Get the definition
                result = defn.pattern.add_definition(
                    defn.lower, defn.higher, context_copy,
                    fresh=fresh, kernel_condition=kernel_condition, label=defn.label,
                )

                if result is not None:
                    new_object.context.definitions.add(result)

            # Parse each rule's deferred provisos now that every definition has
            # resolved, so a proviso's term argument may use defined notation. Each
            # rule brings its own metavariables (its `with ... as` binders). A
            # malformed proviso is a source error, not a server fault, and this runs
            # outside run()'s try/except, so record it as a compile error (as the
            # definition `where` path above does) rather than letting it escape.
            for rule in new_object.inference_rules:
                if not rule.pending_side_conditions:
                    continue
                rule_context = copy(new_object.context)
                rule_context.string_variables = {
                    **rule_context.string_variables, **(rule.variables or {})
                }
                try:
                    rule.side_conditions.extend(
                        parse_side_condition(line, rule_context)
                        for line in rule.pending_side_conditions
                    )
                except Exception as e:
                    context.error_log.append(f"Inference rule '{rule.name}': {e}")
                rule.pending_side_conditions = []

            # Set the formal system build context and build the pattern dictionary
            new_object.build_context = sub_context
            new_object.build_pattern_dictionary()

        return context


    @staticmethod
    def valid_variable_name(var):
        # Check if var is a valid variable name
        return var.isidentifier() and var not in {
            "FormalSystem",
            "Abstract",
            "Pattern"
        }

    def __str__(self):
        if self.is_root():
            return "Tree root"

        return f"{self.line_number!s}: {self.line}"
