# Predicate Calculus

integer = StringPattern(name="integer", pattern="^(?:0|[1-9][0-9]*)$", is_regex=True)

variable = StringPattern(name="variable", pattern="x_{i}")
variable.i = integer

constant = StringPattern(name="constant", pattern="c_{i}")
constant.i = integer

function = StringPattern(name="function", pattern="f_{i}^{(k)}(cst)")
function.i = integer
function.k = integer

term = UnionPattern(name="term", patterns=[variable, constant, function])

term_join = StringPattern(name="join", pattern="j, t", skip_node=True)
comma_separated_terms = UnionPattern(name="comma_separated_terms", patterns=[term_join, term], skip_node=True)
term_join.j = comma_separated_terms
term_join.t = term

function.cst = comma_separated_terms

predicate = StringPattern(name="predicate", pattern="P_{i}^{(k)}(cst)")
predicate.i = integer
predicate.k = integer
predicate.cst = comma_separated_terms

equal = StringPattern(name="equal", pattern="t_1 = t_2")
equal.t_1 = term
equal.t_2 = term

atomic_formula = UnionPattern(name="atomic_formula", patterns=[predicate, equal])

ra = StringPattern(name="rightarrow", pattern="(\\alpha \\rightarrow \\beta)")
neg = StringPattern(name="negation", pattern="\\neg \\alpha")
forall = StringPattern(name="forall", pattern="\\forall x \\; \\alpha")
replacement = StringPattern(name="replacement", pattern="\\alpha[t/x]")

formula = UnionPattern(name="formula", patterns=[atomic_formula, ra, neg, forall, replacement])

ra.add_variable("\\alpha", formula)
ra.add_variable("\\beta", formula)

neg.add_variable("\\alpha", formula)

forall.x = variable
forall.add_variable("\\alpha", formula)

replacement.add_variable("\\alpha", formula)
replacement.t = term
replacement.x = variable

# Define free variables
variable.add_attribute(name="free", value=Condition(not self.has_parent(forall, forall.x == self)))
formula.add_attribute(name="free_variables", value=instances(variable, Condition(free)))
formula.add_attribute(name="bound_variables", value=instances(variable, Condition(not free)))

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

c = Condition(
    self.alpha.free_variables.each(
        (not instance == self.x) or \
        (not instance.has_parent(forall, forall.x.equal_any(self.t.instances(variable)))))
)
a4 = StringPattern(name="A4", pattern="(\\forall \\; x \\alpha \\rightarrow \\alpha[t/x])", condition=c, parent=formula)

a4.add_variable("\\alpha", formula)
a4.add_variable("t", term, use_location="last")
a4.x = variable

a5 = StringPattern(name="A5", pattern="\\forall x \\; b", condition=Condition(self.x not in self.b.free_variables), parent=formula)
a5.b = formula
a5.x = variable

a6 = StringPattern(name="A6", pattern="\\forall x \\; x = x")
a6.x = variable

a7 = StringPattern(name="A7", pattern="(x = y \\rightarrow (alpha \\rightarrow beta))", condition=Condition(self.alpha.replace_equivalent(self.beta, self.x, self.y)), parent=formula)
a7.alpha = atomic_formula
a7.beta = atomic_formula
a7.x = variable
a7.y = variable

with "x", "y", "z" as variable:
    suppose "y == z"
    print(a7.match("(x = y \\rightarrow (x = x \\rightarrow z = x))"))


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


# Store relevant context variables
context_variables = {
    "variable": variable,
    "constant": constant,
    "function": function,
    "term": term,
    "predicate": predicate,
    "equal": equal,
    "atomic_formula": atomic_formula,
    "formula": formula
}

# Create the formal system
propositional = FormalSystem(
    name="Predicate",
    axioms=[a1, a2, a3],
    inference_rules=[mp],
    context_variables=context_variables
)
system["formal_system"] = propositional
