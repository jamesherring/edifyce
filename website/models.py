from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from ordered_model.models import OrderedModel
import string
import random
import regex as re


def id_gen(length=12, chars=string.ascii_lowercase + string.ascii_uppercase + string.digits + "-_"):
    # An id generator to uniquely identify objects
    return "".join(random.SystemRandom().choice(chars) for _ in range(length))


class Profile(models.Model):

    # One-to-one relationship to the user model
    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    created = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated = models.DateTimeField(auto_now=True, blank=True, null=True)

    def get_absolute_url(self):
        # Return the absolute url for the profile
        return "/profile/" + self.user.username + "/"

    def __str__(self):
        return str(self.user)


# Save a profile model whenever a user is created
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)


# Update the profile model whenever a user is updated
@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    profile, created = Profile.objects.get_or_create(user=instance)
    profile.save()


class StringPattern(models.Model):
    """A string pattern defined by a regex string"""

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    slug = models.SlugField(max_length=64)

    safe_slug = models.SlugField(max_length=64, default="")

    # The regex pattern - may be recursive
    pattern = models.CharField(max_length=1024)

    # Whether to 'skip' nodes of this StringPattern when building a Tree. Subtrees are appended to the nearest parent
    # tree that is not skipped.
    skip_node = models.BooleanField(default=False)

    def safe_pattern(self):
        # Make the pattern safe by replacing the labels with ids rather than slugs (which can easily collide with
        # slugs from other patterns. Keep some human-readability by appedind _<slug> on the the end.

        # Use a meta-regex that extracts label names and sub_pattern names from the regex pattern
        meta_regex = r"\(\?P<(?P<label>(?:\w|-)+)>\(\?&(?:\w|-)+\)\)"
        matches = re.finditer(meta_regex, self.pattern)

        # Start with the original pattern
        safe_pattern = self.pattern

        # Get the labels
        labels = self.labels()

        # Loop through every subpattern call
        offset = 0
        for m in matches:

            # Get the label
            label_name = m.groupdict()["label"]
            label = labels.get(slug=label_name)

            # Get the match span
            span = m.span()

            # Build the replacement
            replacement = r"(?P<" + label.safe_slug + r">(?&" + label.dependent.safe_slug + r"))"
            safe_pattern = safe_pattern[:offset + span[0]] + replacement + safe_pattern[offset + span[1]:]

            # Calculate the additional offset
            offset += len(replacement) - (span[1] - span[0])

        return safe_pattern

    def labels(self):
        # Return a queryset of labels
        return Label.objects.filter(string_pattern=self)

    def add_label(self, slug, dependent):
        # Add a label to a dependent stringpattern
        label = Label.objects.get_or_create(
            string_pattern=self,
            slug=slug
        )[0]

        label.dependent = dependent
        label.save()

        return label

    def dependents(self):
        # Get a queryset of the dependent stringpatterns
        return StringPattern.objects.filter(id__in=self.labels().values_list("dependent", flat=True))

    def get_recursive_dependents(self, found=None):
        # Get all dependents, including the recursively defined ones. Optionally include a queryset 'found' of
        # dependents already found.

        if found is None:
            found = set()

        for dependent in self.dependents():
            if dependent not in found:
                # This dependent not already found

                found.add(dependent)
                found = found.union(dependent.get_recursive_dependents(found))

        return found

    def regex_definition(self, context=None, tag_only=False):
        # Get the regex definition tag for this StringPattern. Optionally include context.

        s = r"(?P<" + self.safe_slug + ">"

        if tag_only:
            # Only return the tag part (not the pattern). Include "a^" to match nothing.
            return s + "a^)"

        if context is None:
            # Return with no variables or definitions
            return s + self.safe_pattern() + ")"

        s += self.safe_pattern()

        # Otherwise filter the relevant variables
        if "variables" in context:
            variables = tuple(v for v in context["variables"] if context["variables"][v] == self)

            if len(variables) > 0:
                s += "|" + "|".join(variables)

        if "definitions" in context:
            # Add any definitions
            for d in context["definitions"]:
                if d.string_pattern == self:
                    # This definition applies. Preface the slug with an underscore to avoid collisions inside the RegEx
                    # string
                    s += "|(?P<" + "_" + d.higher_pattern.safe_slug + ">(?&" + d.higher_pattern.safe_slug + "))"

        return s + ")"

    def regex_dependent_definitions(self, context=None):
        # Gets the definitions part of the regex string. Optionally specify context variables.

        # Add all the recursively required dependent patterns
        # dependents = self.get_recursive_dependents()

        # Start with the immediate dependents of the pattern.
        dependents = set(self.dependents())

        # Also record 'sub-dependents' - for including the reference (but not the pattern) in the resulting regex.
        # This allows for valid regex which can be expanded where needed.
        sub_dependents = set()

        if context is not None and "dependents" in context:
            # Add dependent patterns from context
            dependents = dependents.union(context["dependents"])
            for d in dependents:
                sub_dependents = sub_dependents.union(d.dependents())

        for d in dependents:
            sub_dependents = sub_dependents.union(d.dependents())

        # Also get context definitions and their dependents
        if context is not None and "definitions" in context:
            for d in context["definitions"]:
                if d.string_pattern in dependents or d.string_pattern == self:
                    # Add the definition
                    dependents.add(d.higher_pattern)
                    sub_dependents = sub_dependents.union(d.higher_pattern.dependents())

        s = ""
        for d in dependents:

            # Don't need to repeat the pattern itself
            if not d == self:
                s += d.regex_definition(context)

        for d in sub_dependents:
            # Also include tags for the sub dependents
            if (d not in dependents) and (not d == self):
                s += d.regex_definition(context, tag_only=True)

        if len(s) == 0:
            # No need for empty define tag
            return ""

        return "(?(DEFINE)" + s + ")"

    def regex(self, context=None):
        # Get the full regex string. This includes any dependencies and the ^ and $ tokens.
        # Optionally add context variables.
        return self.regex_dependent_definitions(context) + "^" + self.regex_definition(context) + "$"

    def test(self, s, context=None):
        # Test a string s to see if it matches the pattern.
        # Optionally specify context
        return re.match(self.regex(context), s) is not None

    def create_tree(self, s="", node_text=None, tree=None, parent_tree=None, context=None):
        """Apply the pattern to a string s to get a tree. Returns None if the pattern does not match.
        Optionally specify the tree to build on.
        Optionally specify a parent tree to append this to.
        Optionally provide context variables."""

        match = re.match(self.regex(context), s)

        if match is None:
            # There is no match
            return None

        # Otherwise, build the tree

        # Create a new tree node
        if tree is None:
            tree = Tree.objects.create(
                parent_tree=parent_tree,
                string_pattern=self,
                text=node_text
            )
        else:
            if (not tree.parent_tree == parent_tree) or (not tree.text == node_text):
                # Need to update these values
                tree.parent_tree = parent_tree
                tree.text = node_text
                tree.save()

        # Check if this is a variable
        if context is not None and "variables" in context:
            variables = tuple(v for v in context["variables"] if context["variables"][v] == self)
            if s in variables:
                # This is a variable
                tree.variable_name = s
                tree.save()
                return tree

        # Get the labels
        labels = self.labels()

        # Get any sub-trees
        for key, value in match.groupdict().items():
            # Key corresponds to another string pattern name in the dependencies. Value is the matched substring.

            if value is None:
                # Ignore non-matches
                continue

            if key == self.safe_slug:
                # Ignore the whole match (which may lead to infinite recursion)
                continue

            # Check the definitions
            found = False
            if context is not None and "definitions" in context:
                for defn in context["definitions"]:
                    if "_" + defn.higher_pattern.safe_slug == key:
                        # This is a definition instance

                        found = True

                        # Use the higher pattern
                        sub_pattern = defn.higher_pattern

                        # Create the subtree
                        sub_pattern.create_tree(s=s, node_text=s, parent_tree=tree, context=context)

                        break

            if found:
                # We found a matching definition
                continue

            try:
                # get the label with slug matching the key
                label = labels.get(string_pattern=self, safe_slug=key)

                # The label points to the dependent string_pattern
                sub_pattern = label.dependent

                # Create the subtree
                sub_pattern.create_tree(s=value, node_text=value, parent_tree=tree, context=context)

            except Exception as e:
                # There is no subpattern with the given name

                tree.delete()
                raise Exception(str(e))

        return tree

    def set_safe_slug(self):
        # Set a safe slug for this string pattern
        self.safe_slug = ("sp_" + self.id + "_" + self.slug)[:30].replace("-", "_")
        self.save()

    def __str__(self):
        return self.slug


# Save a safe slug whenever a StringPattern is created
@receiver(post_save, sender=StringPattern)
def create_sp_safe_slug(sender, instance, created, **kwargs):
    if created:
        instance.set_safe_slug()


class Tree(models.Model):
    # A tree-like expression in a StringPattern, can be a subtree

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    # The string pattern this belongs to
    string_pattern = models.ForeignKey(StringPattern, on_delete=models.CASCADE)

    # The text (if any) on this node
    text = models.CharField(max_length=62, default="")

    # The parent tree (if it exists)
    parent_tree = models.ForeignKey("Tree", default=None, blank=True, null=True, on_delete=models.CASCADE)

    # Indicates if the tree is a variable - and the variable name if so
    variable_name = models.CharField(max_length=32, default="")

    def is_root(self):
        # Returns a boolean indicating if the tree is a root
        return self.parent_tree is None

    def build(self, root_text="", context=None, force=False):
        # Build out the subtree structure

        if force:
            self.subtrees().delete()

        if self.subtrees().count() == 0:
            self.string_pattern.create_tree(s=self.text, node_text=root_text, tree=self, context=context)

    def is_variable(self):
        # Return a boolean indicating if the tree is a variable
        return not self.variable_name == ""

    def is_leaf(self):
        # A leaf is a tree with no subtrees
        return self.subtrees().count() == 0

    def get_final_subtrees(self):
        # Recursive function to get the subtrees ignoring skipped nodes

        subtrees = Tree.objects.filter(parent_tree=self)

        non_skipped = subtrees.filter(string_pattern__skip_node=False)
        skipped = subtrees.filter(string_pattern__skip_node=True)

        # Add the final subtrees of skipped nodes
        result = non_skipped
        for tree in skipped:
            result = result.union(tree.get_final_subtrees())

        return result

    def subtrees(self, ignore_skipped=True):
        # Get the subtrees. By default ignore 'skipped' nodes, and find their children directly.

        if ignore_skipped:
            return self.get_final_subtrees()

        # Otherwise, return the normal subtrees
        return Tree.objects.filter(parent_tree=self)

    def variables(self):
        # Return a dictionary of variables in the tree

        variables = dict()

        if self.is_variable():
            variables[self.variable_name] = self.string_pattern

        for tree in self.subtrees():
            variables.update(tree.variables())

        return variables

    def variable_count(self):
        # Return the number of variables in this tree
        return len(self.variables())

    def check_identical(self, tree, assert_variable_names=True, mapping=None):
        # Check if this tree is identical to the provided tree. Variable names must optionally also be identical.

        if mapping is None:
            mapping = {}

        # They must be of the same string pattern
        if not self.string_pattern == tree.string_pattern:
            return False, mapping

        # They must both be variables or neither
        if not self.is_variable() == tree.is_variable():
            return False, mapping

        if assert_variable_names:
            # The variable names must be identical
            if not self.variable_name == tree.variable_name:
                return False, mapping
        else:
            # The mapping must be consistent
            if self.variable_name in mapping:
                if not mapping[self.variable_name] == tree.variable_name:
                    return False, mapping

            else:
                # Add the mapping
                mapping[self.variable_name] = tree.variable_name

        # They must have the same number of subtrees
        self_subtrees = self.subtrees()
        tree_subtrees = tree.subtrees()

        if not len(self_subtrees) == len(tree_subtrees):
            return False, mapping

        # The subtrees must be identical
        for s, t in zip(self_subtrees, tree_subtrees):
            result, mapping = s.check_identical(t, assert_variable_names, mapping)

            if not result:
                return False, mapping

        # If leaves and not variables, the text must match
        if len(self_subtrees) == 0 and not self.is_variable():
            if not self.text == tree.text:
                return False, mapping

        # Everything is ok
        return True, mapping

    def check_instance(self, tree, mapping=None):
        # Check if the tree provided is an instance of this tree. Both trees may contain variables, as long as they
        # are mapped consistently. Optionally provide a parent mapping which must be consistent.

        if mapping is None:
            mapping = {}

        if not self.string_pattern == tree.string_pattern:
            # Wrong string pattern
            return False, mapping

        # The tree cannot be a variable if self is not a variable
        if (not self.is_variable()) and (tree.is_variable()):
            return False, mapping

        if self.is_variable():
            # Check variable mapping is consistent
            if self.variable_name in mapping:
                # Check the mapped tree is identical to tree
                if not mapping[self.variable_name].check_identical(tree, assert_variable_names=True)[0]:
                    return False, mapping

            else:
                # Add the mapping
                mapping[self.variable_name] = tree

        if not self.is_variable():
            # Check the number of subtrees is the same
            self_subtrees = self.subtrees()
            tree_subtrees = tree.subtrees()

            if not len(self_subtrees) == len(tree_subtrees):
                return False, mapping

            # The subtrees must match
            for s, t in zip(self_subtrees, tree_subtrees):
                result, mapping = s.check_instance(t, mapping)

                if not result:
                    return False, mapping

            # If leaves, the text must match
            if len(self_subtrees) == 0 and not self.text == tree.text:
                return False

        # Looks ok!
        return True, mapping



    def pretty_print(self, depth=0):
        # Return a pretty string for printing

        s = " " * 4 * depth
        s += self.string_pattern.slug + ":  " + str(self)

        if self.is_variable():
            s += "  *" + self.variable_name

        for subtree in self.subtrees():
            s += "\n" + subtree.pretty_print(depth + 1)

        return s

    def __str__(self):
        # Print the tree text
        return self.text


class Definition(models.Model):
    # A definition for a string_pattern, allowing higher level language to be used unambiguously

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    # The string_pattern this belongs to
    string_pattern = models.ForeignKey(StringPattern, on_delete=models.CASCADE, related_name="def_string_pattern")

    # The lower-level pattern (for interpreting/defining)
    lower_pattern = models.ForeignKey(StringPattern, on_delete=models.CASCADE, related_name="lower")

    # The higher-level pattern (for matching)
    higher_pattern = models.ForeignKey(StringPattern, on_delete=models.CASCADE, related_name="higher")

    def __str__(self):
        return self.string_pattern.slug + ", " + self.higher_pattern.slug


class Label(models.Model):
    # A label for a stringpattern. Provides a link between a label slug and a dependent StringPattern.

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    # The string pattern this label belongs to
    string_pattern = models.ForeignKey(StringPattern, related_name="string_pattern", on_delete=models.CASCADE)

    # The slug text
    slug = models.SlugField(max_length=32)

    # The safe slug text
    safe_slug = models.SlugField(max_length=32, default="")

    # The dependent StringPattern this points to
    dependent = models.ForeignKey(StringPattern, blank=True, null=True, related_name="dependent", on_delete=models.CASCADE)

    def set_safe_slug(self):
        # Set a safe slug for this label
        self.safe_slug = ("l_" + self.id + "_" + self.slug)[:30].replace("-", "_")
        self.save()

    def __str__(self):
        return self.slug


# Save a safe slug whenever a Label is created
@receiver(post_save, sender=Label)
def create_lab_safe_slug(sender, instance, created, **kwargs):
    if created:
        instance.set_safe_slug()


class FormalSystem(models.Model):
    # A formal system.

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    # The name of the system
    name = models.CharField(max_length=64)

    # The unique slug of the system
    slug = models.SlugField(max_length=64)

    # The string pattern for testing formulae
    formula_pattern = models.ForeignKey(
        StringPattern,
        default=None,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="formula"
    )

    # A constructor pattern, for joining formulae
    formula_join_pattern = models.ForeignKey(
        StringPattern,
        default=None,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="formula_join"
    )

    # The string pattern for a group of comma-separated formulae
    formula_set_pattern = models.ForeignKey(
        StringPattern,
        default=None,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="formula_set"
    )

    # The string pattern for a proof line
    proof_line_pattern = models.ForeignKey(
        StringPattern,
        default=None,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="proof_line"
    )

    def add_formula_definition(self, slug, pattern):
        # Add a formula definition with a unique slug and a pattern

        sp = StringPattern.objects.create(
            slug=slug,
            pattern=pattern
        )

        return FormulaDefinition.objects.create(
            system=self,
            string_pattern=sp
        )

    def formula_definitions(self):
        # Get the formula definitions
        return FormulaDefinition.objects.filter(system=self)

    def definitions(self):
        # Get the definitions in this system
        return Definition.objects.filter(string_pattern=self.string_pattern)

    def required_patterns(self):
        # Get additional StringPatterns used in the system, that are not formula_definitions or definitions

        results = set()
        ignore = {self.formula_pattern}

        for d in self.formula_definitions():
            results = results.union(d.string_pattern.get_recursive_dependents())
            ignore.add(d.string_pattern)

        for d in self.definitions():
            results = results.union(d.lower_pattern.get_recursive_dependents())
            ignore.add(d.lower_pattern)

        return results.difference(ignore)

    def add_definition(self, slug, lower, higher):
        # Add a definition, replacing a 'lower level' tree with a 'higher level' tree.

        d = Definition.objects.create(

        )

    def is_formula(self, s, context=None):
        # Test if the string s is a formula
        return self.formula_pattern.test(s, context)

    def is_proof_line(self, s, context=None):
        # Test if the string s is a proof line
        return self.proof_line_pattern.test(s, context)

    def parse_formula(self, s, context=None):
        # Parse a string to a Tree in the formal system

        if not self.is_formula(s, context):
            # This string is not a formula
            return False

        tree = Tree.objects.get_or_create(
            string_pattern=self.formula_pattern,
            text=s
        )[0]

        tree.build(root_text=s, context=context)

        return tree

    def parse_proof_line(self, s, context=None):
        # Parse a proof line to a Tree in the formal system

        if not self.is_proof_line(s, context):
            # This string is not a proof line
            return False

        tree = Tree.objects.get_or_create(
            string_pattern=self.proof_line_pattern,
            text=s
        )[0]

        tree.build(root_text=s, context=context)

        return tree

    def update_string_patterns(self):
        # Update the string pattern

        # Get a set of slugs, and dependents for each formula definition.
        subpattern_slugs = []
        dependents = {}

        for fd in self.formula_definitions():

            # Get the slug for the formula definition pattern
            fd_slug = fd.string_pattern.safe_slug

            subpattern_slugs.append(fd_slug)

            dependents[fd_slug] = fd.string_pattern

        # Build the pattern - include a option to use variables
        new_formula_pattern = "(?:" + \
                              "|".join("(?P<_" + slug + ">(?&" + slug + "))" for slug in subpattern_slugs) + ")"

        if self.formula_pattern is None:
            # Create a new StringPattern
            formula_pattern = StringPattern(
                slug="formula",
                pattern=new_formula_pattern
            )

        else:
            # Update the old formula pattern
            formula_pattern = self.formula_pattern
            formula_pattern.pattern = new_formula_pattern

        formula_pattern.save()

        # Add the labels - just need the immediate dependents
        for fd_slug in dependents:
            formula_pattern.add_label("_" + fd_slug, dependents[fd_slug])

        self.formula_pattern = formula_pattern

        # Create the formula join pattern

        if self.formula_join_pattern is not None:
            self.formula_join_pattern.delete()

        self.formula_join_pattern = StringPattern.objects.create(
            slug="formula_join",
            pattern="(?:(?P<left>(?&formula)), (?P<sub>(?&formula_join))|(?P<f>(?&formula)))",
            skip_node=True
        )
        self.formula_join_pattern.add_label("left", self.formula_pattern)
        self.formula_join_pattern.add_label("sub", self.formula_join_pattern)
        self.formula_join_pattern.add_label("f", self.formula_pattern)

        # Create the formula set pattern

        if self.formula_set_pattern is not None:
            self.formula_set_pattern.delete()

        self.formula_set_pattern = StringPattern.objects.create(
            slug="formula_set",
            pattern="{(?P<join>(?&formula_join))}"
        )
        self.formula_set_pattern.add_label("join", self.formula_join_pattern)

        # Create the proof line pattern

        if self.proof_line_pattern is not None:
            self.proof_line_pattern.delete()

        self.proof_line_pattern = StringPattern.objects.create(
            slug="proof_line",
            pattern=r"(?:(?P<set>(?&formula_set)) \\vdash (?P<f>(?&formula)))"
        )
        self.proof_line_pattern.add_label("set", self.formula_set_pattern)
        self.proof_line_pattern.add_label("f", self.formula_pattern)

        # Save the formal system
        self.save()

    def __str__(self):
        return self.name


class FormulaDefinition(models.Model):
    # A formula definition in a formal system

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    # The formal system this belongs to
    system = models.ForeignKey(FormalSystem, on_delete=models.CASCADE)

    # The string pattern to use
    string_pattern = models.ForeignKey(StringPattern, on_delete=models.CASCADE)

    def __str__(self):
        return self.system.name + ", " + self.string_pattern.slug


class Axiom(models.Model):
    # An axiom in a formal system. Each axiom is itself a string_pattern, which can be instantiated with any matching
    # instance.

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    # The name of this axiom
    name = models.CharField(max_length=64)

    # The formal system this applies to
    system = models.ForeignKey(FormalSystem, on_delete=models.CASCADE)

    # The string pattern for checking axiom instances
    string_pattern = models.ForeignKey(StringPattern, on_delete=models.CASCADE)

    def regex(self):
        # Return a regex string for testing axioms
        return self.string_pattern.regex()

    def is_axiom(self, t):
        # Test if the tree t is an instance of the axiom.
        # t must also be a formula in the system.
        return (self.system.is_formula(str(t))) and (re.match(self.regex(), s) is not None)


class Rule(models.Model):
    # An inference rule in a formal system

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)
    system = models.ForeignKey(FormalSystem, on_delete=models.CASCADE)

    def conditions(self):
        return RuleCondition.objects.filter(rule=self)

    def apply(self, *trees):
        # Take one or more input trees (hypotheses) and return an output tree (deduction)

        # Check there are the correct number of arguments
        conditions = self.conditions()
        if not len(trees) == len(conditions):
            # rule does not apply
            return False

        # Otherwise, check that every condition matches
        for c, tree in zip(conditions, trees):
            if not c.apply(tree):
                # There is not a match
                return False

        # Otherwise ok
        return True


class RuleCondition(models.Model):
    # A condition for a Rule

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)
    rule = models.ForeignKey(Rule, on_delete=models.CASCADE)

    # The RegEx pattern to use
    pattern = models.CharField(max_length=256)

    def apply(self, s):
        # Apply the condition to a string s. Return the matching elements

        if type(s) is str:
            # s is a string, not a tree
            result = re.search(self.pattern, s)

            if result is None:
                # No match
                return False

            # Otherwise there is a match
            return True

        else:
            # s is a tree
            pass


class Proof(models.Model):
    # A proof in a formal system

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    # The formal system this proof is in
    system = models.ForeignKey(FormalSystem, on_delete=models.CASCADE)

    # The name of this proof
    name = models.CharField(max_length=128)

    # A description of this proof
    description = models.TextField(default="")

    def __str__(self):
        return self.name.lower().replace("-", "_")


class ProofLine(OrderedModel):
    # A line in a proof

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    # The proof this belongs to
    proof = models.ForeignKey(Proof, on_delete=models.CASCADE)

    # The inference rule used
    rule = models.ForeignKey(Rule, blank=True, null=True, on_delete=models.SET_NULL)

    # Whether the rule is valid
    valid = models.BooleanField(default=None, blank=True, null=True)

    # The tree on this line
    tree = models.ForeignKey(Tree, on_delete=models.CASCADE)

    # The references to earlier lines
    references = models.ManyToManyField("ProofLine")

    def pattern(self):
        # Get the string pattern for testing prooflines
        return self.proof.system.proof_line_pattern

    def validate(self):
        # Validate if the proof line is correct, using the given rule, tree, and line references
        self.valid = self.rule.apply(self.tree, self.references)
        self.save()
        return self.valid

    def __str__(self):
        return str(self.tree)
