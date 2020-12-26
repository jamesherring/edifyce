# Propositional Calculus

integer = StringPattern(name="integer", pattern="^(?:0|[1-9][0-9]*)$", is_regex=True, proper_initial_segment="always")

pv = StringPattern(name="variable", pattern="p_i")
pv.i = integer

ra = StringPattern(name="rightarrow", pattern="(left \\rightarrow east)", proper_initial_segment="never")
neg = StringPattern(name="negation", pattern="\\neg f", proper_initial_segment="never")

formula = UnionPattern(name="formula", patterns=[pv, ra, neg])

ra.left = formula
ra.east = formula
neg.f = formula

# Dollar formulas - for TeX parsing
dollar_formula = StringPattern(name="dollar_formula", pattern="$f$", skip_node=True, proper_initial_segment="never")
dollar_formula.f = formula

# Dollar formula or a formula
any_formula = UnionPattern(name="formula", patterns=[formula, dollar_formula], skip_node=True)

a1 = StringPattern(
    name="A1",
    pattern="(\\alpha \\rightarrow (\\beta \\rightarrow \\alpha))",
    parent=formula,
    proper_initial_segment="never"
)
a1.add_variable("\\alpha", formula)
a1.add_variable("\\beta", formula)

a2 = StringPattern(
    name="A2",
    pattern="((\\alpha \\rightarrow (\\beta \\rightarrow \\gamma)) \\rightarrow ((\\alpha \\rightarrow \\beta) \\rightarrow (\\alpha \\rightarrow \\gamma)))",
    parent=formula,
    proper_initial_segment="never"
)
a2.add_variable("\\alpha", formula)
a2.add_variable("\\beta", formula)
a2.add_variable("\\gamma", formula)

a3 = StringPattern(
    name="A3",
    pattern="((\\neg \\beta \\rightarrow \\neg \\alpha) \\rightarrow (\\alpha \\rightarrow \\beta))",
    parent=formula,
    proper_initial_segment="never"
)
a3.add_variable("\\alpha", formula)
a3.add_variable("\\beta", formula)

# Make the import line
import_pattern = StringPattern(name="import", pattern="^import [a-zA-Z0-9\.]+$", is_regex=True)
import_line = LineType(name="import", pattern=import_pattern, behaviour="import")

# Allow empty lines
empty_pattern = StringPattern(name="empty", pattern="^(?>    )*$", is_regex=True)
empty_line = LineType(name="empty", pattern=empty_pattern, behaviour="none")

# Allow comments
comment_pattern = StringPattern(name="comment", pattern="^(?>    )*#.*$", is_regex=True)
comment_line = LineType(name="comment", pattern=comment_pattern, behaviour="none")

# Create references
reference = StringPattern(name="reference", pattern="^[a-zA-Z0-9 ,]+$", is_regex=True)

reference_pattern = StringPattern(name="reference_pattern", pattern="S[ref] formula", proper_initial_segment="never")
reference_pattern.S = empty_pattern
reference_pattern.ref = reference
reference_pattern.formula = any_formula
reference_line = LineType(name="Reference", pattern=reference_pattern, behaviour="logical")

# Build comma separated formulae
f_join = StringPattern(name="join_formula", pattern="j, formula", skip_node=True)
f_join.formula = any_formula
comma_separated_formula = UnionPattern(name="csf", patterns=[any_formula, f_join], skip_node=True)
f_join.j = comma_separated_formula

# Variables for with parts
variable = StringPattern(name="formula_variable_name", pattern="^[a-zA-Z0-9\\.\\\\]+$", is_regex=True)
dollar_variable = StringPattern(name="dollar_variable", pattern="$v$", skip_node=True, proper_initial_segment="never")
dollar_variable.v = variable

# Build comma separated variables
join = StringPattern(name="join_variable", pattern="j, variable", skip_node=True)
join.variable = dollar_variable
csv = UnionPattern(name="comma_separated_variables", patterns=[join, dollar_variable], skip_node=True)
join.j = csv

with_part = StringPattern(name="with_part", pattern="csv as pattern", proper_initial_segment="never")
with_part.csv = csv
with_part.pattern = system["variable_name"]

join_wp = StringPattern(name="join_wp", pattern="j, with_part", skip_node=True)
join_wp.with_part = with_part

cswp = UnionPattern(name="cswp", patterns=[join_wp, with_part], skip_node=True)
join_wp.j = cswp

# Build with line - for introducing variable patterns
with_pattern = StringPattern(name="with", pattern="Swith cswp:", proper_initial_segment="never")
with_pattern.S = empty_pattern
with_pattern.cswp = cswp
with_line = LineType(
    name="with",
    pattern=with_pattern,
    behaviour="indent",
    add_context_key_path="self.with_part.v",
    add_context_value_path="non_skip_parent().pattern"
)

if_pattern = StringPattern(name="if", pattern="Sif csf:", proper_initial_segment="never")
if_pattern.S = empty_pattern
if_pattern.csf = comma_separated_formula
if_line = LineType(name="if line", pattern=if_pattern, behaviour="indent")

# Now make the inference rules

# Make modus ponens
mp_0 = formula

mp_1 = StringPattern(name="mp_1", pattern="(alpha \\rightarrow beta)", parent=formula, proper_initial_segment="never")
mp_1.alpha = formula
mp_1.beta = formula

c = Condition(
    deduction.formula() == antecedents[1].inf_match().beta and \
    antecedents[0].formula() == antecedents[1].inf_match().alpha and \
    deduction.indent_line() == antecedents[0].indent_line() and \
    deduction.indent_line() == antecedents[1].indent_line()
)
mp = InferenceRule(name="Modus Ponens", label="MP", antecedents=[mp_0, mp_1], deduction=formula, condition=c)

# A formula in the given set can be deduced
c = Condition(deduction.formula() in deduction.indent_lines().shallow_instances(formula))
if_rule = InferenceRule(name="If", label="IF", antecedents=[], deduction=formula, condition=c)

# Deduction theorem has two directions, requires two inference rules
c = Condition(
    deduction.formula() == antecedents[0].inf_match().beta and \
    deduction.indent_line().match().shallow_instances(formula) == set(antecedents[0].inf_match().alpha) and \
    deduction.indent_line().indent_line() == antecedents[0].indent_line()
)
dt_1 = InferenceRule(name="Deduction Theorem 1", label="DT1", antecedents=[mp_1], deduction=formula, condition=c)

c = Condition(
    deduction.indent_line() == antecedents[0].indent_line().indent_line() and \
    set(deduction.inf_match().alpha) == antecedents[0].indent_line().match().shallow_instances(formula) and \
    deduction.inf_match().beta == antecedents[0].formula()
)
dt_2 = InferenceRule(name="Deduction Theorem 2", label="DT2", antecedents=[formula], deduction=mp_1, condition=c)

# Rewrite an earlier line in the proof
c = Condition(
    deduction.formula() == antecedents[0].formula() and \
    (antecedents[0].is_root() or antecedents[0].indent_line() in deduction.indent_lines())
)
thinning = InferenceRule(name="Thinning", label="T", antecedents=[formula], deduction=formula, condition=c)

# Create the formal system
propositional = FormalSystem(
    name="Propositional Logic",
    axioms=[a1, a2, a3],
    line_types=[import_line, empty_line, comment_line, reference_line, with_line, if_line],
    inference_rules=[mp, if_rule, dt_1, dt_2, thinning],
    context_variables={"formula": formula}
)
system["formal_system"] = propositional
