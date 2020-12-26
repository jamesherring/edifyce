# Predicate Calculus

integer = StringPattern(name="integer", pattern="^(?:0|[1-9][0-9]*)$", is_regex=True)

variable = StringPattern(name="variable", pattern="x_i")
variable.i = integer

constant = StringPattern(name="constant", pattern="c_i")
constant.i = integer

fns = StringPattern(name="function", pattern="f_i^{(k)}(cst)")
fns.i = integer
fns.k = integer

term = UnionPattern(name="term", patterns=[variable, constant, fns])

term_join = StringPattern(name="join", pattern="j, t", skip_node=True)
comma_separated_terms = UnionPattern(name="comma_separated_terms", patterns=[term_join, term], skip_node=True)
term_join.j = comma_separated_terms
term_join.t = term

fns.cst = comma_separated_terms

predicate = StringPattern(name="predicate", pattern="P_i^{(k)}(cst)")
predicate.i = integer
predicate.k = integer
predicate.cst = comma_separated_terms

equal = StringPattern(name="equal", pattern="t_1 = t_2")
equal.t_1 = term
equal.t_2 = term

atomic_formula = UnionPattern(name="atomic_formula", patterns=[predicate, equal])

ra = StringPattern(name="rightarrow", pattern="(left \\rightarrow right)")
neg = StringPattern(name="negation", pattern="\\neg f")
forall = StringPattern(name="forall", pattern="\\forall x sub")
replacement = StringPattern(name="replacement", pattern="alpha[t/x]")

formula = UnionPattern(name="formula", patterns=[atomic_formula, ra, neg, forall, replacement])

ra.left = formula
ra.right = formula

neg.f = formula

forall.x = variable
forall.sub = formula

replacement.alpha = formula
replacement.t = term
replacement.x = variable

# Define free variables
variable.add_attribute(name="free", value=Condition(not self.has_parent(forall, forall.x == self)))
formula.add_attribute(name="free_variables", value=instances(variable, Condition(free)))
formula.add_attribute(name="bound_variables", value=instances(variable, Condition(not free)))

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

a4 = StringPattern(name="A4", pattern="(\\forall x alpha \\rightarrow alpha[term/x])", condition=Condition(each(self.alpha.free_variables, (not instance == self.x) or (not instance.has_parent(forall, forall.x.equal_any(self.term.instances(variable)))))), parent=formula)

a4.alpha = formula
a4.term = term
a4.x = variable

a5 = StringPattern(name="A5", pattern="\\forall x b", condition=Condition(self.x not in self.b.free_variables), parent=formula)
a5.b = formula
a5.x = variable

a6 = StringPattern(name="A6", pattern="\\forall x x = x")
a6.x = variable

a7 = StringPattern(name="A7", pattern="(x = y \\rightarrow (alpha \\rightarrow beta))", condition=Condition(self.alpha.replace_equivalent(self.beta, self.x, self.y)), parent=formula)
a7.alpha = atomic_formula
a7.beta = atomic_formula
a7.x = variable
a7.y = variable

with "x", "y", "z" as variable:
    suppose "y == z"
    print(a7.match("(x = y \\rightarrow (x = x \\rightarrow z = x))"))



