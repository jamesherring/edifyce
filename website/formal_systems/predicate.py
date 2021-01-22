# Predicate Calculus

integer = StringPattern(name="integer", pattern="^(?:0|[1-9][0-9]*)$", is_regex=True)

variable = StringPattern(name="variable", pattern="x_{i}")
variable.i = integer

constant = StringPattern(name="constant", pattern="c_{i}")
constant.i = integer

function = StringPattern(name="function", pattern="f_{i}^{(k)}(t)")
function.i = integer
function.k = integer

term = UnionPattern(name="term", patterns=[variable, constant, function])

term_join = StringPattern(name="join", pattern="j, t", skip_node=True)
comma_separated_terms = UnionPattern(name="comma_separated_terms", patterns=[term_join, term], skip_node=True)
term_join.j = comma_separated_terms
term_join.t = term

function.t = comma_separated_terms

predicate = StringPattern(name="predicate", pattern="P_{i}^{(k)}(t)")
predicate.i = integer
predicate.k = integer
predicate.t = comma_separated_terms

equal = StringPattern(name="equal", pattern="t_1 = t_2")
equal.t_1 = term
equal.t_2 = term

atomic_formula = UnionPattern(name="atomic_formula", patterns=[predicate, equal])

ra = StringPattern(name="rightarrow", pattern="(\\alpha \\rightarrow \\beta)")
neg = StringPattern(name="negation", pattern="\\neg \\alpha")
forall = StringPattern(name="forall", pattern="\\forall x \\alpha")
replacement = StringPattern(name="replacement", pattern="\\alpha[t/x]")

respect_brackets = {
    "(": ")"
}

formula = UnionPattern(name="formula", patterns=[atomic_formula, ra, neg, forall, replacement], respect_brackets=respect_brackets)

ra.add_variable("\\alpha", formula)
ra.add_variable("\\beta", formula)

neg.add_variable("\\alpha", formula)

forall.x = variable
forall.add_variable("\\alpha", formula)

replacement.add_variable("\\alpha", formula)
replacement.t = term
replacement.x = variable

# Define free variables
variable.add_attribute(name="free", value=Condition(not has_parent(forall, forall.x == self)))
formula.add_attribute(name="variables", value=instances(variable))
formula.add_attribute(name="free_variables", value=instances(variable, Condition((not instance.parent().pattern() == forall) and free)))
formula.add_attribute(name="bound_variables", value=instances(variable, Condition((not instance.parent().pattern() == forall) and not free)))

c = Condition(
    alpha.free_variables.each(
        (not instance == x) or \
        (not instance.has_parent(forall, forall.x.equal_any(self.instances(variable)))))
)

term.add_attribute(
    name="is_free_for",
    params=["x", "alpha"],
    value=c
)


with "x", "y", "z" as variable, "t1" as term, "A" as formula:
    
    t = term.match("x")
    var = variable.match("y")
    f = formula.match("(\\forall x \\forall y x = y \\rightarrow \\forall y x = y)")
    
    # print(f.free_variables)
    print(t.is_free_for(var, f))
    

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

c = Condition(t.is_free_for(self.x, self.variables("\\alpha")))
a4 = StringPattern(name="A4", pattern="(\\forall x \\alpha \\rightarrow \\alpha[t/x])", condition=c, parent=formula)

a4.add_variable("\\alpha", formula)
a4.add_variable("t", term, use_location="last")
a4.x = variable

c = Condition(self.x not in self.variables("\\alpha").free_variables)
a5 = StringPattern(name="A5", pattern="(\\forall x (\\alpha \\rightarrow \\beta) \\rightarrow (\\alpha \\rightarrow \\forall x \\beta))", condition=c, parent=formula)
a5.add_variable("\\alpha", formula)
a5.add_variable("\\beta", formula)
a5.x = variable

a6 = StringPattern(name="A6", pattern="\\forall x x = x", parent=formula)
a6.x = variable

c = Condition(self.variables("\\alpha").replace_equivalent(self.variables("\\beta"), self.x, self.y))
a7 = StringPattern(name="A7", pattern="(x = y \\rightarrow (\\alpha \\rightarrow \\beta))", condition=c, parent=formula)
a7.add_variable("\\alpha", atomic_formula)
a7.add_variable("\\beta", atomic_formula)
a7.x = variable
a7.y = variable

pre_format = {
    "(?P<char>[^\s])\s\s+": "\\g<char> ",
    "\\$(?P<inner>.*?)\\$": "\\g<inner>",
    "\\\\;": ""
}

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
empty = StringPattern(name="empty", pattern="")
label = StringPattern(name="label", pattern=" label{ref}")
label.ref = StringPattern(name="reference", pattern="^[a-zA-Z0-9_,\.]+$", is_regex=True)
label_union = UnionPattern(name="label_union", patterns=[empty, label])

logical_pattern = StringPattern(name="logical_pattern", pattern="Sformula ref{refs}label", pre_format=pre_format)
logical_pattern.S = empty_pattern
logical_pattern.refs = StringPattern(name="reference", pattern="^[a-zA-Z0-9_,\. ]+$", is_regex=True)
logical_pattern.formula = formula
logical_pattern.label = label_union
logical_line = LineType(name="Reference", pattern=logical_pattern, behaviour="logical")

# Build comma separated formulae
f_join = StringPattern(name="join_formula", pattern="j, formula", skip_node=True)
f_join.formula = formula
comma_separated_formula = UnionPattern(name="csf", patterns=[formula, f_join], skip_node=True)
f_join.j = comma_separated_formula

# Variables for with parts
variable_name = StringPattern(name="variable_name", pattern="^[a-zA-Z0-9\\.\\\\]+$", is_regex=True)

# Build comma separated variables
join = StringPattern(name="join_variable", pattern="j, variable", skip_node=True)
join.variable = variable_name
csv = UnionPattern(name="comma_separated_variables", patterns=[join, variable_name], skip_node=True)
join.j = csv

let_part = StringPattern(name="let_part", pattern="csv be pattern", proper_initial_segment="never")
let_part.csv = csv
let_part.pattern = system["variable_name"]

join_lp = StringPattern(name="join_lp", pattern="j, let_part", skip_node=True)
join_lp.let_part = let_part

cslp = UnionPattern(name="cslp", patterns=[join_lp, let_part], skip_node=True)
join_lp.j = cslp

# Build with line - for introducing variable patterns
let_pattern = StringPattern(name="let", pattern="Slet cslp", proper_initial_segment="never", pre_format=pre_format)
let_pattern.S = empty_pattern
let_pattern.cslp = cslp
let_line = LineType(
    name="let",
    pattern=let_pattern,
    behaviour="none",
    add_context_key_path="instances(variable_name)",
    add_context_value_path="non_skip_parent().pattern"
)

if_pattern = StringPattern(name="if", pattern="Sif csf:", proper_initial_segment="never", pre_format=pre_format)
if_pattern.S = empty_pattern
if_pattern.csf = comma_separated_formula
if_line = LineType(name="if line", pattern=if_pattern, behaviour="indent")

# Add an attribute to get assumptions
if_pattern.add_attribute(name="assumptions", value=shallow_instances(formula))

# Add an attribute to logical lines - to get all the assumptions
logical_line.add_attribute(name="assumptions", value=indent_lines().assumptions)

# Add an if pattern for suppositions - relating to attributes rather than assuming a formula
if_attribute_pattern = StringPattern(name="if_attribute", pattern="Sif supp:", pre_format=pre_format)
if_attribute_pattern.S = empty_pattern
if_attribute_pattern.supp = system["condition_inner"]
if_attribute_line = LineType(
    name="if attribute line",
    pattern=if_attribute_pattern,
    behaviour="indent",
    add_context_type="restrictions",
    add_context_value_path="supp.string()"
)

# Definition line
define_pattern = StringPattern(name="define", pattern="Sdefine higher as lower", pre_format=pre_format)
define_pattern.S = empty_pattern
define_pattern.higher = StringPattern(name="anything", pattern="^.*$", is_regex=True)
define_pattern.lower = StringPattern(name="anything", pattern="^.*$", is_regex=True)
define_line = LineType(name="define line", pattern=define_pattern, behaviour="definition")

    
# Make modus ponens
mp_0 = formula

mp_1 = StringPattern(name="mp_1", pattern="(\\alpha \\rightarrow \\beta)", parent=formula, proper_initial_segment="never")
mp_1.add_variable("\\alpha", formula)
mp_1.add_variable("\\beta", formula)

c = Condition(
    deduction.formula() == antecedents[1].inf_match().variables("\\beta") and \
    antecedents[0].formula() == antecedents[1].inf_match().variables("\\alpha") and \
    antecedents[0].assumptions.is_subset(deduction.assumptions) and \
    antecedents[1].assumptions.is_subset(deduction.assumptions)
)
mp = InferenceRule(name="Modus Ponens", label="MP", antecedents=[mp_0, mp_1], deduction=formula, condition=c)


# An assumed formula can be deduced
c = Condition(deduction.formula() in deduction.assumptions)
if_rule = InferenceRule(name="Given", label="IF", antecedents=[], deduction=formula, condition=c)

# Deduction theorem has two directions, requires two inference rules
c = Condition(
    deduction.formula() == antecedents[0].inf_match().variables("\\beta") and \
    deduction.indent_line().match().assumptions == set(antecedents[0].inf_match().variables("\\alpha")) and \
    (deduction.indent_line().indent_line() == None or (deduction.indent_line().indent_line().assumptions == antecedents[0].indent_line().assumptions))
)
dt_1 = InferenceRule(name="Deduction Theorem 1", label="DT1", antecedents=[mp_1], deduction=formula, condition=c)

c = Condition(
    deduction.indent_line() == antecedents[0].indent_line().indent_line() and \
    set(deduction.inf_match().variables("\\alpha")) == antecedents[0].indent_line().match().shallow_instances(formula) and \
    deduction.inf_match().variables("\\beta") == antecedents[0].formula()
)
dt_2 = InferenceRule(name="Deduction Theorem 2", label="DT2", antecedents=[formula], deduction=mp_1, condition=c)

# Thinning rule
c = Condition(
    deduction.formula() == antecedents[0].formula() and \
    antecedents[0].assumptions.is_subset(deduction.assumptions)
)
thinning = InferenceRule(name="Thinning", label="R", antecedents=[formula], deduction=formula, condition=c)

# Utilise a previous theorem
c = Condition(antecedents[0].formula().maps_onto(deduction.formula(), consistent_with=[antecedents[0].assumptions, deduction.assumptions]))
theorem = InferenceRule(name="theorem", label="T", antecedents=[formula], deduction=formula, condition=c)

# Utilise a defintion
c = Condition(
    deduction.formula().definition_equivalent(antecedents[0].formula()) and \
    deduction.indent_line() == antecedents[0].indent_line()
)
definition = InferenceRule(name="Definition", label="DEF", antecedents=[formula], deduction=formula, condition=c)


# Store relevant context variables
context_variables = {
    "variable_name": variable_name,
    "variable": variable,
    "constant": constant,
    "function": function,
    "term": term,
    "predicate": predicate,
    "equal": equal,
    "atomic_formula": atomic_formula,
    "forall": forall,
    "formula": formula
}

# Create the formal system
propositional = FormalSystem(
    name="Predicate",
    line_types=[import_line, empty_line, comment_line, logical_line, let_line, if_line, if_attribute_line, define_line],
    axioms=[a1, a2, a3, a4, a5, a6, a7],
    inference_rules=[mp, if_rule, dt_1, dt_2, thinning, theorem, definition],
    context_variables=context_variables
)
system["formal_system"] = propositional
