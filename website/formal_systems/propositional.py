# Propositional Calculus

integer = StringPattern(name="integer", pattern="^(?:0|[1-9][0-9]*)$", is_regex=True, proper_initial_segment="always")

pv = StringPattern(name="variable", pattern="p_{i}", proper_initial_segment="never")
pv.i = integer

ra = StringPattern(name="rightarrow", pattern="(\\alpha \\rightarrow \\beta)", proper_initial_segment="never")
neg = StringPattern(name="negation", pattern="\\neg \\alpha", proper_initial_segment="never")

formula = UnionPattern(name="formula", patterns=[pv, ra, neg])

ra.add_variable("\\alpha", formula)
ra.add_variable("\\beta", formula)

neg.add_variable("\\alpha", formula)

# Dollar formulas - for TeX parsing
dollar_formula = StringPattern(name="dollar_formula", pattern="$formula$", skip_node=True, proper_initial_segment="never")
dollar_formula.formula = formula

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
import_pattern = StringPattern(name="import", pattern="import path as reference")
import_pattern.path = StringPattern(name="import_path", pattern="^[a-zA-Z0-9\._]+$", is_regex=True)
import_pattern.reference = StringPattern(name="ref", pattern="^[a-zA-Z0-9_]+$", is_regex=True)
import_line = LineType(name="import", pattern=import_pattern, behaviour="import")

# Allow empty lines
empty_pattern = StringPattern(name="empty", pattern="^(?>    )*$", is_regex=True)
empty_line = LineType(name="empty", pattern=empty_pattern, behaviour="none")

# Allow comments
comment_pattern = StringPattern(name="comment", pattern="^(?>    )*#.*$", is_regex=True)
comment_line = LineType(name="comment", pattern=comment_pattern, behaviour="none")

# Create references and exports
reference = StringPattern(name="reference", pattern="^[a-zA-Z0-9_, ]+$", is_regex=True)

empty = StringPattern(name="empty", pattern="")
label = StringPattern(name="label", pattern=" label{ref}")
label.ref = reference
label_union = UnionPattern(name="label_union", patterns=[empty, label])

reference_pattern = StringPattern(name="reference_pattern", pattern="Sformula ref{refs}label")
reference_pattern.S = empty_pattern
reference_pattern.refs = reference
reference_pattern.formula = dollar_formula
reference_pattern.label = label_union
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

let_part = StringPattern(name="let_part", pattern="csv be pattern", proper_initial_segment="never")
let_part.csv = csv
let_part.pattern = system["variable_name"]

join_lp = StringPattern(name="join_lp", pattern="j, let_part", skip_node=True)
join_lp.let_part = let_part

cslp = UnionPattern(name="cslp", patterns=[join_lp, let_part], skip_node=True)
join_lp.j = cslp

# Build with line - for introducing variable patterns
let_pattern = StringPattern(name="let", pattern="Slet cslp", proper_initial_segment="never")
let_pattern.S = empty_pattern
let_pattern.cslp = cslp
let_line = LineType(
    name="let",
    pattern=let_pattern,
    behaviour="none",
    add_context_key_path="self.let_part.v",
    add_context_value_path="non_skip_parent().pattern"
)

if_pattern = StringPattern(name="if", pattern="Sif csf:", proper_initial_segment="never")
if_pattern.S = empty_pattern
if_pattern.csf = comma_separated_formula
if_line = LineType(name="if line", pattern=if_pattern, behaviour="indent")

# Definition line
define_pattern = StringPattern(name="define", pattern="Sdefine $higher$ as $lower$")
define_pattern.S = empty_pattern
define_pattern.higher = StringPattern(name="anything", pattern="^.*$", is_regex=True)
define_pattern.lower = formula
define_line = LineType(name="define line", pattern=define_pattern, behaviour="definition")

# Now make the inference rules

# Make modus ponens
mp_0 = formula

mp_1 = StringPattern(name="mp_1", pattern="(\\alpha \\rightarrow \\beta)", parent=formula, proper_initial_segment="never")
mp_1.add_variable("\\alpha", formula)
mp_1.add_variable("\\beta", formula)

c = Condition(
    deduction.formula() == antecedents[1].inf_match().variables("\\beta") and \
    antecedents[0].formula() == antecedents[1].inf_match().variables("\\alpha") and \
    deduction.indent_line() == antecedents[0].indent_line() and \
    deduction.indent_line() == antecedents[1].indent_line()
)
mp = InferenceRule(name="Modus Ponens", label="MP", antecedents=[mp_0, mp_1], deduction=formula, condition=c)

# A formula in the given set can be deduced
c = Condition(deduction.formula() in deduction.indent_lines().shallow_instances(formula))
if_rule = InferenceRule(name="Given", label="IF", antecedents=[], deduction=formula, condition=c)

# Deduction theorem has two directions, requires two inference rules
c = Condition(
    deduction.formula() == antecedents[0].inf_match().variables("\\beta") and \
    deduction.indent_line().match().shallow_instances(formula) == set(antecedents[0].inf_match().variables("\\alpha")) and \
    deduction.indent_line().indent_line() == antecedents[0].indent_line()
)
dt_1 = InferenceRule(name="Deduction Theorem 1", label="DT1", antecedents=[mp_1], deduction=formula, condition=c)

c = Condition(
    deduction.indent_line() == antecedents[0].indent_line().indent_line() and \
    set(deduction.inf_match().variables("\\alpha")) == antecedents[0].indent_line().match().shallow_instances(formula) and \
    deduction.inf_match().variables("\\beta") == antecedents[0].formula()
)
dt_2 = InferenceRule(name="Deduction Theorem 2", label="DT2", antecedents=[formula], deduction=mp_1, condition=c)

# Rewrite an earlier line in the proof
c = Condition(
    deduction.formula() == antecedents[0].formula() and \
    (antecedents[0].is_root() or antecedents[0].indent_line() in deduction.indent_lines())
)
thinning = InferenceRule(name="Thinning", label="T", antecedents=[formula], deduction=formula, condition=c)

# Utilise a defintion
c = Condition(
    deduction.formula().definition_equivalent(antecedents[0].formula()) and \
    deduction.indent_line() == antecedents[0].indent_line()
)
definition = InferenceRule(name="Definition", label="DEF", antecedents=[formula], deduction=formula, condition=c)

# Create the formal system
propositional = FormalSystem(
    name="Propositional Logic",
    axioms=[a1, a2, a3],
    line_types=[import_line, empty_line, comment_line, reference_line, let_line, if_line, define_line],
    inference_rules=[mp, if_rule, dt_1, dt_2, thinning, definition],
    context_variables={"formula": formula}
)
system["formal_system"] = propositional
