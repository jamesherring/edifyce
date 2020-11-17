# Propositional Calculus

integer = StringPattern(name="integer", pattern="^(?:0|[1-9][0-9]*)$", is_regex=True)

pv = StringPattern(name="variable", pattern="p_i")
pv.i = integer

ra = StringPattern(name="rightarrow", pattern="(left \\rightarrow notleft)")
neg = StringPattern(name="negation", pattern="\\neg f")

formula = UnionPattern(name="formula", patterns=[pv, ra, neg])

ra.left = formula
ra.notleft = formula
neg.f = formula

a1 = StringPattern(name="A1", pattern="(\\alpha \\rightarrow (beta \\rightarrow \\alpha))")
a1.add_variable("\\alpha", formula)
a1.add_variable("\\beta", formula)

a2 = StringPattern(name="A2", pattern="((alpha \\rightarrow (beta \\rightarrow gamma)) \\rightarrow ((alpha \\rightarrow beta) \\rightarrow (alpha \\rightarrow gamma)))")
a2.alpha = formula
a2.beta = formula
a2.gamma = formula

a3 = StringPattern(name="A3", pattern="((\\neg beta \\rightarrow \\neg alpha) \\rightarrow (alpha \\rightarrow beta))")
a3.alpha = formula
a3.beta = formula

import_pattern = StringPattern(name="import", pattern="^import [a-zA-Z0-9\.]+$", is_regex=True)
import_line = LineType(name="import", pattern=import_pattern, behaviour="import")

empty_pattern = StringPattern(name="empty", pattern="^(?>    )*$", is_regex=True)
empty_line = LineType(name="empty", pattern=empty_pattern, behaviour="none")

comment_pattern = StringPattern(name="comment", pattern="^(?>    )*#.*$", is_regex=True)
comment_line = LineType(name="comment", pattern=comment_pattern, behaviour="none")

reference = StringPattern(name="reference", pattern="^[a-zA-Z0-9 ,]+", is_regex=True)

logical_pattern = StringPattern(name="logical", pattern="S[ref] formula")
logical_pattern.ref = reference
logical_pattern.S = empty_pattern
logical_pattern.formula = formula
logical_line = LineType(name="logical", pattern=logical_pattern, behaviour="logical")

cswp = system["comma_separated_with_parts"]
with_pattern = StringPattern(name="with", pattern="Swith cswp:")
with_pattern.S = empty_pattern
with_pattern.cswp = cswp
with_line = LineType(name="with", pattern=with_pattern, behaviour="indent", add_context_key_path="self.wp.s", add_context_value_path="non_skip_parent().pattern")

# Build comma separated formulae
join = StringPattern(name="join", pattern="j, formula", skip_node=True)
join.formula = formula
comma_separated_formula = UnionPattern(name="csf", patterns=[formula, join])
join.j = comma_separated_formula

if_pattern = StringPattern(name="if", pattern="Sif csf:")
if_pattern.S = empty_pattern
if_pattern.csf = comma_separated_formula
suppose_line = LineType(name="suppose", pattern=if_pattern, behaviour="indent")

mp_1 = StringPattern(name="mp_1", pattern="S[ref] alpha")
mp_1.S = empty_pattern
mp_1.ref = reference
mp_1.alpha = formula

mp_2 = StringPattern(name="mp_2", pattern="S[ref] (alpha \\rightarrow beta)")
mp_2.S = empty_pattern
mp_2.ref = reference
mp_2.alpha = formula
mp_2.beta = formula

mp_result = StringPattern(name="mp_result", pattern="S[ref] beta")
mp_result.S = empty_pattern
mp_result.ref = reference
mp_result.beta = formula

c = Condition(deduction.beta == antecedents[1].beta and antecedents[0].alpha == antecedents[1].alpha)
mp = InferenceRule(name="Modus Ponens", label="MP", antecedents=[mp_1, mp_2], deduction=mp_result, condition=c)

dt_1 = if_pattern
dt_deduction = logical_pattern
c = Condition(deduction.formula in antecedents[0].instances(formula) and antecedents[0] in deduction.indent_lines())
deduce_supposed = InferenceRule(name="Deduction Theorem", label="DT", antecedents=[dt_1], deduction=dt_deduction, condition=c)

line_types = [import_line, empty_line, comment_line, logical_line, with_line, suppose_line]
context_variables = {"formula": formula}
propositional = FormalSystem(name="propositional_logic", axioms=[a1, a2, a3], line_types=line_types, inference_rules=[mp, deduce_supposed], context_variables=context_variables)

system["formal_system"] = propositional
