# Propositional Calculus

integer = StringPattern(name="integer", pattern="^(?:0|[1-9][0-9]*)$", is_regex=True)

pv = StringPattern(name="variable", pattern="p_i")
pv.i = integer

ra = StringPattern(name="rightarrow", pattern="(left \\rightarrow right)")
neg = StringPattern(name="negation", pattern="\\neg f")

formula = UnionPattern(name="formula", patterns=[pv, ra, neg])

ra.left = formula
ra.right = formula
neg.f = formula

a1 = StringPattern(name="A1", pattern="(alpha \\rightarrow (beta \\rightarrow alpha))")
a1.alpha = formula
a1.beta = formula

a2 = StringPattern(name="A2", pattern="((alpha \\rightarrow (beta \\rightarrow gamma)) \\rightarrow ((alpha \\rightarrow beta) \\rightarrow (alpha \\rightarrow gamma)))")
a2.alpha = formula
a2.beta = formula
a2.gamma = formula

a3 = StringPattern(name="A3", pattern="((\\neg beta \\rightarrow \\neg alpha) \\rightarrow (alpha \\rightarrow beta))")
a3.alpha = formula
a3.beta = formula

mp_1 = StringPattern(name="mp_1", pattern="alpha")
mp_1.alpha = formula

mp_2 = StringPattern(name="mp_2", pattern="(alpha \\rightarrow beta)")
mp_2.alpha = formula
mp_2.beta = formula

mp_result = StringPattern(name="mp_result", pattern="beta")
mp_result.beta = formula

mp = InferenceRule(name="Modus Ponens", label="MP", antecedents=[mp_1, mp_2], deduction=mp_result)

import_pattern = StringPattern(name="import", pattern="^import [a-zA-Z0-9\.]+$", is_regex=True)
import_line = LineType(name="import", pattern=import_pattern, behaviour="import")

empty_pattern = StringPattern(name="empty", pattern="^(?>    )*$", is_regex=True)
empty_line = LineType(name="empty", pattern=empty_pattern, behaviour="none")

comment_pattern = StringPattern(name="comment", pattern="^(?>    )*#.*$", is_regex=True)
comment_line = LineType(name="comment", pattern=comment_pattern, behaviour="none")

logical_pattern = StringPattern(name="logical", pattern="S[ref] formula")
logical_pattern.ref = StringPattern(name="reference", pattern="^[a-zA-Z0-9 ,]+", is_regex=True)
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

suppose_pattern = StringPattern(name="suppose", pattern="Ssuppose csf:")
suppose_pattern.S = empty_pattern
suppose_pattern.csf = comma_separated_formula
suppose_line = LineType(name="suppose", pattern=suppose_pattern, behaviour="indent")

ds_1 = suppose_pattern
ds_deduction = formula
deduce_supposed = InferenceRule(name="deduce supposed", label="S", antecedents=[ds_1], deduction=ds_deduction)
# Maybe need a condition on ds_1 and ds_deduction - ds_deduction.formula in ds_1.formula

system = FormalSystem(name="propositional_logic", axioms=[a1, a2, a3], line_types=[import_line, empty_line, comment_line, logical_line, with_line, suppose_line], inference_rules=[mp])
