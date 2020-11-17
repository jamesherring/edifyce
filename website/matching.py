import regex as re
import inspect
from website.formal_system import FormalSystem, LineType, InferenceRule, ProofLine
from website.context import Context


class Match(object):
    # A match for a regex pattern

    def __init__(self, pattern, string, definition_mapping=None, lower_match=None, parent_pattern_match=None):

        # The pattern or union instance
        self.pattern = pattern

        # The matching string (or possibly pattern)
        self.string = string

        # The definition mapping (if any)
        self.definition_mapping = definition_mapping

        # The lower level match (if in a definition)
        self.lower_match = lower_match

        # The parent match (if it exists)
        self.parent_match = None

        # If self.pattern has a parent pattern, link to the corresponding match
        self.parent_pattern_match = parent_pattern_match

        # The sub_matches
        self.sub_matches = dict()

    def add_submatch(self, name, sub):
        self.sub_matches[name] = sub
        sub.parent_match = self

    def get_value(self, context, data_type=None):
        # Get the value of a match

        if self.lower_match is not None:
            # Get the value of the lower level
            return self.lower_match.get_value(context, data_type)

        return self.get_by_path(self.pattern.value_path, context, data_type)

    def get_function_args(self, context, correct_args):
        # Return unlabelled and labelled arguments from a comma separated argument match

        args = self.get_sub_matches()["a"]

        if type(args) is not list:
            # Only one argument - not enough, we need at least a name and a pattern
            raise Exception("At least 2 arguments are required to make a pattern.")

        # Go through the arguments building an arguments dictionary - make sure unlabelled arguments are first
        labelled = False

        unlabelled_args = list()
        labelled_args = dict()

        for arg in args:

            arg_type = list(arg.sub_matches.keys())[0]
            arg_value = arg.get_value(context)

            if arg_type == "labelled_argument":
                labelled = True

                # This is a labelled argument
                label = arg.get_by_path("labelled_argument.label.string()", context)

                if label in labelled_args:
                    # This label has already been included
                    raise Exception("Duplicate argument key: " + label)

                labelled_args[label] = arg_value

            elif labelled is True:
                # There have been labelled arguments and this one is unlabelled
                raise Exception("Labelled arguments must come after unlabelled arguments.")

            else:
                # Valid unlabelled argument
                unlabelled_args.append(arg_value)

            # Take out those arguments taken by the unlabelled args
            correct_args = correct_args[len(unlabelled_args):]

            # Every labelled arg key should be in the remaining correct args
            invalid_keys = [key for key in labelled_args if key not in correct_args]

            if len(invalid_keys) > 0:
                raise Exception("Invalid argument(s): " + str(invalid_keys))

        return unlabelled_args, labelled_args

    def get_by_path(self, path, context, data_type=None, attribute_name=None):
        # Get the submatch in the given path.

        subs = self.get_sub_matches()

        # Optionally override the data type
        if data_type is None:
            data_type = self.pattern.type

        if path is None or path == "":
            return self

        if type(path) is Condition:
            return path.check(self, context)

        path_match = None
        if type(path) is Match:
            path_match = path
            path = path.string

        if path == "string()":
            # Get the string
            return self.string

        if path == "boolean()":
            # Get the boolean value
            assert self.string == "True" or self.string == "False"
            return self.string == "True"

        if path == "empty_list()":
            # Return an empty list
            return []

        if path == "dict()":
            # Return a dictionary
            dct = dict()

            parts = subs["part"]
            if type(parts) is not list:
                parts = [parts]

            for part in parts:
                part_subs = part.get_sub_matches()

                key = part_subs["key"].get_value(context)
                value = part_subs["value"].get_value(context)

                dct[key] = value

            return dct

        if path == "empty_dict()":
            return dict()

        if path == "item()":
            # Return an item according to the data type

            value = self.string

            if data_type == "boolean":
                # String must be True or False
                assert self.string == "True" or self.string == "False"
                value = self.string == "True"

            elif data_type == "list":
                # This is a list of objects
                list_items = self.get_sub_matches()["obj"]

                if type(list_items) is list:
                    value = [item.get_value(context) for item in list_items]

                else:
                    # Singleton list
                    item = list_items
                    value = [item.get_value(context)]

            return value

        if path == "union_value()":
            assert type(self.pattern) is UnionPattern
            # The pattern is a union - get the matching pattern

            for key in subs:
                # Should only be one key
                sub_match = subs[key]

                return sub_match.get_value(context, data_type)

        if path == "value()":
            # Use the pattern value path
            return self.get_value(context, data_type)

        if path == "lookup()":
            # Do a variable lookup
            if self.string not in context.variables:
                # Not a variable
                raise Exception("Could not find variable: " + str(self))

            return context.variables[self.string]

        if path == "system_lookup()":
            # This is a system lookup

            key = self.get_value(context)
            if key not in context.system:
                raise Exception("Could not find system variable: " + str(key))

            return context.system[key]

        if path == "parent()":
            # Look up the parent match
            return self.parent_match

        if path == "non_skip_parent()":
            # Get the non-skipped parent match
            return self.get_non_skip_parent()

        if path == "make_pattern()":
            # Make a string pattern with the value. This match should be for a comma separated arguments

            # Get the correct arguments
            correct_args = list(inspect.signature(StringPattern.__init__).parameters)[1:]
            unlabelled_args, labelled_args = self.get_function_args(context, correct_args)

            return StringPattern(*unlabelled_args, **labelled_args)

        if path == "make_union()":
            # Make a regex union with the string

            # Get the correct arguments
            correct_args = list(inspect.signature(UnionPattern.__init__).parameters)[1:]
            unlabelled_args, labelled_args = self.get_function_args(context, correct_args)

            return UnionPattern(*unlabelled_args, **labelled_args)

        if path == "make_defn()":
            # Make a definition with the higher and lower strings

            # Get the correct arguments
            correct_args = ["higher", "lower"]
            unlabelled_args, labelled_args = self.get_function_args(context, correct_args)

            # Must be two args
            assert len(unlabelled_args) + len(labelled_args) == len(correct_args)

            return Definition(*unlabelled_args, **labelled_args)

        if path == "make_condition()":
            # Make a condition object with the value
            return Condition(condition_match=self.get_sub_matches()["x"])

        if path == "make_match()":
            # Make a match

            # Get the string and pattern
            pattern = self.get_by_path("p.value()", context)
            s = self.get_by_path("s.value()", context)

            return pattern.match(s, context)

        if path == "make_formal_system()":
            # Make a formal system

            # Get the correct arguments
            correct_args = list(inspect.signature(FormalSystem.__init__).parameters)[1:]
            unlabelled_args, labelled_args = self.get_function_args(context, correct_args)

            return FormalSystem(*unlabelled_args, **labelled_args)

        if path == "make_line_type()":
            # Make a line type

            # Get the correct arguments
            correct_args = list(inspect.signature(LineType.__init__).parameters)[1:]
            unlabelled_args, labelled_args = self.get_function_args(context, correct_args)

            return LineType(*unlabelled_args, **labelled_args)

        if path == "make_inference_rule()":
            # Make an inference rule

            # Get the correct arguments
            correct_args = list(inspect.signature(InferenceRule.__init__).parameters)[1:]
            unlabelled_args, labelled_args = self.get_function_args(context, correct_args)

            return InferenceRule(*unlabelled_args, **labelled_args)

        if path == "get_attribute()":
            # Calculate a match attribute

            # Get the match and attribute name
            match = self.get_by_path("match.value()", context)
            attribute = self.get_by_path("attribute.string()", context)

            return match.get_attribute(attribute, context)

        # Instances path
        if path[:10] == "instances(" and path[-1] == ")":
            # Collect a set of instances, possibly meeting some condition

            inner = path[10:-1]

            if ", " in inner:
                index = inner.index(",")
                pattern_name = inner[:index]

                sub_condition = path_match.get_sub_matches()["a"][1].get_value(context)

                return self.get_instances(pattern_name, context, sub_condition, attribute_name)

            # Otherwise, just a pattern name or path
            return self.get_instances(inner, context)

        if self.definition_mapping is not None and path in self.definition_mapping:
            return self.get_by_path(
                path=self.definition_mapping[path],
                context=context,
                data_type=data_type
            )

        if path in subs:
            # Child match
            return subs[path]

        if path in self.pattern.attributes:
            # Attribute
            return self.get_attribute(path, context)

        if "." in path:
            # Dotted path
            index = path.index(".")
            child = path[:index]
            remainder = path[index + 1:]

            if child == "self":
                return self.get_by_path(remainder, context, data_type, attribute_name)

            if self.definition_mapping is not None and child in self.definition_mapping:
                # Use the definition
                key = self.definition_mapping[child]

                if key in subs:
                    sub_match = subs[key]

                elif key in self.sub_matches:
                    sub_match = self.sub_matches[key]

            elif child in subs:
                sub_match = subs[child]

            elif child in self.sub_matches:
                sub_match = self.sub_matches[child]

            else:
                # Otherwise try getting the child by path
                sub_match = self.get_by_path(child, context, data_type, attribute_name)

            if type(sub_match) is list:
                # Need to collect the result as a list
                result = []
                for m in sub_match:
                    sub_result = m.get_by_path(remainder, context, data_type)

                    if type(sub_result) is list:
                        # Extend the results
                        result.extend(sub_result)
                    else:
                        result.append(sub_result)

                return result

            return sub_match.get_by_path(remainder, context, data_type)

        # Couldn't parse the string
        raise Exception("Could not find " + path + " in " + str(self))

    def get_sub_matches(self, include_skipped=False):
        # Get the sub matches - optionally include skipped

        def dict_append(dct, key, value):
            # Append key: value to a dictionary dct, creating a list if necessary to avoid losing items

            if key not in dct:
                # Easy case
                dct[key] = value
                return dct

            # Otherwise key already in dct
            if type(dct[key]) is list:
                # It's already a list

                if type(value) is list:
                    dct[key].extend(value)
                else:
                    dct[key].append(value)
                return dct

            # Otherwise it's not yet a list, make a new list
            if type(value) is list:
                value.append(dct[key])
                dct[key] = value
            else:
                dct[key] = [value, dct[key]]

            return dct

        if include_skipped:
            return self.sub_matches

        # Get the non-skipped patterns, and the sub-patterns of skipped patterns
        subs = {}
        for key, sub_match in self.sub_matches.items():

            if sub_match.pattern.skip_node:
                # This submatch is skipped - get the children
                skipped_subs = sub_match.get_sub_matches(include_skipped)

                for sub_key, skipped_sub_match in skipped_subs.items():
                    subs = dict_append(subs, sub_key, skipped_sub_match)

            else:
                # Don't skip this one
                subs = dict_append(subs, key, sub_match)

        return subs

    def get_instances(self, pattern, context, condition=None, attribute_name=None):
        # Get instances of the pattern in nested sub matches, which meet the specified condition.
        # Optionally specify the attribute we are searching for

        if type(pattern) is str:
            # Need to get the correct pattern
            pattern = context.variables[pattern]

        instances = set()
        negatives = set()

        # If incomplete, it's a variable pattern, that may contain an instance of the given pattern
        complete = not (self.string in context.string_variables and self.pattern.may_contain(pattern))

        if not complete and pattern.match(self.string, context) is not None:
            # Don't consider this incomplete - as we have the whole variable instance
            complete = True

        if self.pattern is pattern:
            # Include self

            if condition is None or condition.check(self, context):
                instances.add(self)

        # Union with any sub matches
        for key, sub_match in self.get_sub_matches().items():
            sub_instances, sub_negatives, sub_complete = sub_match.get_instances(pattern, context, condition, attribute_name)

            instances = instances.union(sub_instances)
            negatives = negatives.union(sub_negatives)

            # The result is only complete if all sub matches return a complete set
            complete = complete and sub_complete

        # Check the negatives
        false_negatives = set()
        for key, sub_match in self.get_sub_matches().items():
            sub_instances, sub_negatives, sub_complete = sub_match.get_instances(pattern, context, condition, attribute_name)

            for neg in negatives:

                keep = False
                for item in sub_negatives:
                    if item.equivalent(neg, context) is True:
                        # Ok to keep
                        keep = True
                        break

                if keep:
                    continue

                if not sub_complete:
                    # Not a negative
                    false_negatives.add(neg)
                    continue

                # Check each item
                for item in sub_instances:
                    if not (item.equivalent(neg, context) is False):
                        # Not a negative
                        false_negatives.add(neg)
                        break

        # Remove the false negatives
        negatives = negatives - false_negatives

        # Check context for extra restrictions
        if attribute_name is not None:
            for r in context.restrictions:
                if r["type"] == "membership" and r["set"] == self.string + "." + attribute_name:
                    # This membership restriction applies

                    if not r["negated"]:
                        # Positive membership
                        instances.add(pattern.match(r["member"], context))

                    else:
                        # Negative membership
                        negatives.add(pattern.match(r["member"], context))

        return instances, negatives, complete

    def get_attribute(self, name, context):
        # Get the attribute value by name.

        # Use the pattern attribute path
        return self.get_by_path(path=self.pattern.get_attribute(name), context=context, attribute_name=name)

    def parent_matches(self):
        # Return a set of all the parent matches

        if self.parent_match is None:
            return set()

        return self.parent_match.parent_matches().union({self.parent_match})

    def has_parent(self, pattern):
        # Return True if match has a parent of the given pattern

        for p in self.parent_matches():
            if p.pattern is pattern:
                return True

        # Otherwise False
        return False

    def find_parent(self, pattern):
        # Find a parent of the given pattern

        if self.parent_match is None:
            return None

        if self.parent_match.pattern is pattern:
            # Found
            return self.parent_match

        return self.parent_match.find_parent(pattern)

    def get_non_skip_parent(self):
        # Get the first parent match that is not hidden
        parent = self.parent_match

        if parent.pattern.skip_node:
            # The parent is skipped, get the next one
            return parent.get_non_skip_parent()

        # Otherwise, the parent is not skipped
        return parent

    def pretty_print(self, include_skipped=False, depth=0):
        # Print the match tree

        if depth > 10:
            return ""

        spaces = " " * depth * 4
        s = spaces + str(self) + ": " + str(self.pattern.name) + "\n"

        subs = self.get_sub_matches(include_skipped)
        for key in subs:
            item = subs[key]

            if type(item) is list:
                # This is a list entry
                s += spaces + "    [\n"

                for sub in item:
                    s += sub.pretty_print(include_skipped, depth + 2)

                s += spaces + "    ]\n"

            else:
                # Simple entry
                s += subs[key].pretty_print(include_skipped, depth + 1)

        return s

    def equivalent(self, other, context):
        # Test whether two matches are equivalent. For variables - use context restrictions where possible.

        # A variable will typically return None when matched against a string or another variable - i.e. they could be
        # equal but it can't be guaranteed or ruled out.

        # Belonging to the same pattern is a requirement
        if self.pattern is not other.pattern:
            return False

        # Test equality of sub_matches
        self_subs = self.get_sub_matches()
        other_subs = other.get_sub_matches()

        if not set(self_subs.keys()) == set(other_subs.keys()):
            # Sub matches don't correspond
            return False

        if len(self_subs) > 0:

            # Keep track of the weakest sub-result - initially assumed to be True
            weakest = True

            for key in self_subs:
                # Check the subs are equivalent
                result = self_subs[key].equivalent(other_subs[key], context)

                if result is False:
                    # Weakest result is False - so we can return this immediately
                    return False

                if result is None:
                    weakest = None

            return weakest

        # Otherwise, no sub_matches. Are we dealing with variables?
        self_var = self.string in context.string_variables
        other_var = other.string in context.string_variables

        # Function to get variable restrictions
        def get_variable_restrictions(var, mapping=None):
            # Get all restrictions on var, including nested restrictions on equivalent variables

            # Keep track of a set of results for all relevant variables
            if mapping is None:
                mapping = dict()

            if var not in mapping:
                mapping[var] = {
                    "positive": {
                        "variables": set()
                    },
                    "negative": {
                        "variables": set(),
                        "values": set()
                    }
                }

            for r in context.restrictions:

                if not r["type"] == "equivalence":
                    # Not an equivalence restriction
                    continue

                if var in r["pair"]:
                    # Restriction applies to var

                    # Get the other item
                    other = None
                    for item in r["pair"]:
                        if not item == var:
                            other = item
                            break

                    # Check if other is a variable
                    if other in context.string_variables:
                        # Other is a variable

                        if other in mapping:
                            # Already mapped
                            continue

                        # Update the mapping with other
                        mapping = get_variable_restrictions(other, mapping)

                        if r["negated"]:
                            # not var == other

                            mapping[var]["negative"]["variables"].add(other)

                            # Check if other has fixed value.
                            if "value" in mapping[other]["positive"]:
                                # This is useful - we know var cannot be equal to this
                                mapping[var]["negative"]["values"].add(mapping[other]["positive"]["value"])

                            # Any equivalent variables also apply to var
                            mapping[var]["positive"]["variables"].update(mapping[other]["positive"]["variables"])

                        else:
                            # var == other
                            mapping[var]["positive"]["variables"].add(other)

                            # Check if other has fixed value
                            if "value" in mapping[other]["positive"]:
                                # This is useful - we know var must be equal to this
                                mapping[var]["positive"]["value"] = mapping[other]["positive"]["value"]

                            # Any negative restrictions on other also apply to var
                            mapping[var]["negative"]["variables"].update(mapping[other]["negative"]["variables"])
                            mapping[var]["negative"]["values"].update(mapping[other]["negative"]["values"])

                    else:
                        # Other is a fixed value
                        if r["negated"]:
                            # not var == item
                            mapping[var]["negative"]["values"].add(other)

                        else:
                            # var == item
                            mapping[var]["positive"]["value"] = other

            return mapping

        if not self_var and not other_var:
            # Neither are variables
            return self.string == other.string

        # Otherwise, at least one variable.
        if self.string == other.string:
            # We can take this as equal
            return True

        # Check the restrictions.
        mapping = None
        if self_var:
            mapping = get_variable_restrictions(self.string, mapping)
            self_map = mapping[self.string]
        else:
            self_map = {
                "positive": {"value": self.string}
            }

        if other_var:
            mapping = get_variable_restrictions(other.string, mapping)
            other_map = mapping[other.string]
        else:
            other_map = {
                "positive": {"value": other.string}
            }

        if "value" in self_map["positive"]:
            # We have a fixed value for self
            self_value = self_map["positive"]["value"]

            if "value" in other_map["positive"]:
                # We have a fixed value for other
                other_value = other_map["positive"]["value"]

                return self_value == other_value

            # No fixed value for other
            if self_value in other_map["negative"]["values"]:
                # Can't be equal
                return False

            # Otherwise, they could be equal, and they could be not equal
            return None

        # No fixed value for self
        if "value" in other_map["positive"]:
            # We have a fixed value for other
            other_value = other_map["positive"]["value"]

            if other_value in self_map["negative"]["values"]:
                # Can't be equal
                return False

            # Otherwise, they could be equal, and they could be not equal
            return None

        # No fixed value for other

        # Both self and other don't have fixed values
        if other.string in self_map["positive"]["variables"]:
            # They are nonetheless the same
            return True

        if other.string in self_map["negative"]["variables"]:
            # They must be different
            return False

        # No apparent relation between self and other
        return None

    def replace_equivalent(self, other, x, y, context):
        # Check if self and other are partially equivalent, with some instances of x replaced with instances of y

        if self.equivalent(other, context):
            return True

        if self.equivalent(x, context) and other.equivalent(y, context):
            return True

        if self.pattern is not other.pattern:
            return False

        self_subs = self.get_sub_matches()
        other_subs = other.get_sub_matches()

        if not len(self_subs) == len(other_subs):
            return False

        if len(self_subs) == 0:
            # These are leaves, not equivalent
            return False

        for key in self_subs:
            if key not in other_subs:
                # Differing sub_matches
                return False

            if not self_subs[key].replace_equivalent(other_subs[key], x, y, context):
                # Sub match not partially equivalent
                return False

        for key in other_subs:
            if key not in self_subs:
                return False

        # Otherwise ok
        return True

    def __str__(self):
        return str(self.string)


class Condition(object):
    # A condition match

    def __init__(self, condition_match):

        # The condition match
        self.condition_match = condition_match

    def get_item(self, s, match, context, condition_context):
        # Get an item s given a match, context and condition context

        if type(s) is str:

            if s == "self":
                return condition_context["origin"]

            if s in condition_context:
                return condition_context[s]

            if s in context.variables:
                return context.variables[s]

            if s[-1] == "]" and "[" in s:
                # Looks like a list index
                initial = s[:s.index("[")]
                index = int(s[s.index("[") + 1:-1])

                initial = self.get_item(initial, match, context, condition_context)

                return initial[index]

            if "." in s:

                index = s.index(".")
                initial = s[:index]
                remainder = s[index + 1:]

                initial = self.get_item(initial, match, context, condition_context)

                if remainder == "indent_lines()":
                    # Proof line function - return with the same signature as get_instances()
                    return set(line.match for line in initial.indent_lines()), set(), True

                if type(initial) is ProofLine:
                    # It's a proof line - get the inference match
                    initial = initial.inference_match

                return initial.get_by_path(remainder, context)

        return match.get_by_path(s, context)

    def check(self, match, context, condition_match=None, condition_context=None):
        # Check if the given match meets the condition

        if condition_match is None:
            # Use the top-level condition match
            condition_match = self.condition_match

        if condition_context is None:
            # Keep at least the origin match
            condition_context = {
                "origin": match
            }

        subs = condition_match.get_sub_matches()

        if "equal" in subs:
            # Test equality

            equal_subs = subs["equal"].get_sub_matches()

            left = self.get_item(equal_subs["left"].string, match, context, condition_context)
            right = self.get_item(equal_subs["right"].string, match, context, condition_context)

            return left.equivalent(right, context)

        if "membership" in subs or "negative_membership" in subs:
            # Test membership

            if "membership" in subs:
                negated = False
                membership_subs = subs["membership"].get_sub_matches()

            else:
                negated = True
                membership_subs = subs["negative_membership"].get_sub_matches()

            item = self.get_item(membership_subs["item"].string, match, context, condition_context)
            instances, negatives, complete = self.get_item(membership_subs["set"].string, match, context, condition_context)

            if type(item) is ProofLine:
                # Get the inference match
                item = item.inference_match

            for inst in instances:
                if item.equivalent(inst, context):
                    # Equivalent
                    return not negated

            for inst in negatives:
                if item.equivalent(inst, context):
                    # Equivalent to a negative
                    return negated

            if complete:
                # Complete and not present
                return negated

            # Otherwise, can't say - return None
            return None

        if "negation" in subs:
            # Negation

            not_subs = subs["negation"].get_sub_matches()
            return not self.check(match, context, condition_match=not_subs["condition"], condition_context=condition_context)

        if "and" in subs:
            # Both conditions

            and_subs = subs["and"].get_sub_matches()

            left = and_subs["left"]
            right = and_subs["right"]

            return self.check(match, context, condition_match=left, condition_context=condition_context) and \
                self.check(match, context, condition_match=right, condition_context=condition_context)

        if "or" in subs:
            # Either sub-condition

            or_subs = subs["or"].get_sub_matches()

            left = or_subs["left"]
            right = or_subs["right"]

            return self.check(match, context, condition_match=left, condition_context=condition_context) or \
                self.check(match, context, condition_match=right, condition_context=condition_context)

        if "function" in subs:
            # Function

            func_subs = subs["function"].get_sub_matches()

            # Get the function name, item, and arguments
            func_name = func_subs["func"].string
            item = self.get_item(func_subs["item"].string, match, context, condition_context)
            args = func_subs["args"].get_sub_matches()

            if func_name == "has_parent":
                # Check if item has a parent

                sub_condition = None

                if "item_and_condition" in args:
                    # We have an argument list - parent pattern and sub-condition

                    iac_subs = args["item_and_condition"].get_sub_matches()

                    parent_pattern = self.get_item(iac_subs["item"].string, match, context, condition_context)
                    sub_condition = Condition(iac_subs["condition"])

                else:

                    assert "item" in args

                    parent_pattern = self.get_item(args["item"].string, match, context, condition_context)

                parent_match = item.find_parent(parent_pattern)

                if parent_match is None:
                    # item doesn't have this parent
                    return False

                if sub_condition is not None:
                    # Check the sub_condition

                    # Add the parent to the context
                    new_condition_context = condition_context.copy()
                    new_condition_context[parent_pattern.name] = parent_match

                    if not sub_condition.check(match, context, condition_context=new_condition_context):
                        # Sub condition fails
                        return False

                # Must be ok
                return True

            elif func_name == "equal_any":

                instances, negs, complete = self.get_item(args["item"].string, match, context, condition_context)

                if not complete:
                    # Can't test against other matches
                    return False

                for inst in instances:
                    if item.equivalent(inst, context):
                        # Equivalent to this instance
                        return True

                # Otherwise not equal to any
                return False

        if "replace_equivalent" in subs:
            # Equivalent up to some instances being replaced with another

            re_subs = subs["replace_equivalent"].get_sub_matches()

            item = self.get_item(re_subs["item"].string, match, context, condition_context)
            other = self.get_item(re_subs["other"].string, match, context, condition_context)
            x = self.get_item(re_subs["x"].string, match, context, condition_context)
            y = self.get_item(re_subs["y"].string, match, context, condition_context)

            return item.replace_equivalent(other, x, y, context)

        if "brackets" in subs:
            # Resolve the inside of the brackets
            inner = subs["brackets"].get_sub_matches()["inner"]
            return self.check(match, context, condition_match=inner, condition_context=condition_context)

        if "item" in subs:
            path = subs["item"].string
            return match.get_by_path(path, context)

        if "each" in subs:
            # Test a condition against each of the items

            each_subs = subs["each"].get_sub_matches()

            items, neg_items, complete = self.get_item(each_subs["items"].string, match, context, condition_context)

            if not complete:
                # No way to verify if the condition applies to other variable items
                return False

            sub_condition = Condition(each_subs["condition"])

            for item in items:

                # Create a new condition context
                new_condition_context = condition_context.copy()
                new_condition_context["instance"] = item

                if not sub_condition.check(item, context, condition_context=new_condition_context):
                    # Doesn't pass the check
                    return False

            # Otherwise ok
            return True

        raise Exception("Could not recognise condition.")


class Definition(object):
    # A definition object

    def __init__(self, higher, lower):

        self.higher = StringPattern(
            name="higher",
            pattern=higher
        )

        self.lower = StringPattern(
            name="lower",
            pattern=lower
        )

        # The variables - apply both to higher and lower patterns
        self.variables = {}

    def add_variable(self, name, pattern):
        # Add the variable to both higher and lower
        self.variables[name] = pattern
        self.higher.add_variable(name, pattern)
        self.lower.add_variable(name, pattern)

    def apply(self, s, pattern, context):
        # Try to apply the definition to a string s of a given pattern

        # Get the definition dictionary from the pattern
        pattern_defs = pattern.definitions
        pattern_dct = None
        for dct in pattern_defs:
            if dct["definition"] is self:
                # This is the corresponding definition
                pattern_dct = dct
                break

        if pattern_dct is None:
            # No match
            return None

        if not pattern_dct["valid"]:
            # Definition doesn't apply
            return None

        # Try matching against the higher pattern. This automatically considers the variables.
        match = self.higher.match(s, context)

        if match is None:
            # No match
            return None

        # Get the mapping from the definition to the pattern
        mapping = pattern_dct["mapping"]
        new_mapping = {key: mapping.sub_matches[key].string for key in mapping.sub_matches}

        if match.definition_mapping is not None:
            # Chaining definitions
            for key in new_mapping:
                value = new_mapping[key]
                if value in match.definition_mapping:
                    # Chain the value
                    new_mapping[key] = match.definition_mapping[value]

        match.definition_mapping = new_mapping

        # Check the lower level - which may be interpreted to e.g. make a definition
        lower_s = self.lower.pattern
        for var in match.sub_matches:
            lower_s = lower_s.replace(var, match.sub_matches[var].string)

        # Assign the lower match
        match.lower_match = pattern.match(lower_s, context)

        return match

    def applies_to_pattern(self, pattern, context):
        # Check if the definition can apply to the specified pattern in the given context
        return pattern.match(self.lower, context)


class Pattern(object):
    # Parent class for StringPattern and UnionPattern

    def __init__(self, name, parent=None, condition=None):

        # The pattern name
        self.name = name

        # The parent pattern (if applicable)
        self.parent = parent

        # The condition for this pattern applying
        self.condition = condition

        # Keep a dictionary of attributes on the pattern
        self.attributes = dict()

    def add_attribute(self, name, value):
        # Add an attribute to this pattern

        # Value can be a path picking on values from submatches
        self.attributes[name] = value

    def get_attribute(self, name):
        # Get the given attribute

        if name in self.attributes:
            return self.attributes[name]

        # Check the parent pattern attributes
        if self.parent is not None:
            return self.parent.get_attribute(name)

        # Otherwise, error
        raise Exception(self.name + " does not have attribute: " + name)

    def meets_condition(self, match, context):
        # Check that a given match meets the condition for this Pattern

        if self.condition is None:
            return match

        if not self.condition.check(match, context):
            return None

        return match

    def may_contain(self, other, ignore=None):
        # Check whether this pattern structure allows the other pattern in it's structure

        # track a set of patterns to ignore, to avoid recursion
        if ignore is None:
            ignore = set()

        if self in ignore:
            # Nothing here
            return False

        ignore.add(self)

        if type(self) is UnionPattern:
            # Check each of the sub-patterns

            for sub_pattern in self.patterns:
                if sub_pattern is other or sub_pattern.may_contain(other, ignore):
                    return True

            # No sub-pattern works
            return False

        assert type(self) is StringPattern

        # Check each of the variables
        for var in self.variables:
            sub_pattern = self.variables[var]

            if sub_pattern.may_contain(other, ignore):
                return True

        # No variable works
        return False


class StringPattern(Pattern):
    """A string pattern created in compiling lattice"""

    def __init__(self, name, pattern, condition=None, is_regex=False, variables=None, replacements=None,
                 skip_node=False, value_path="", data_type=None, parent=None):

        Pattern.__init__(self, name, parent, condition)

        # The pattern string
        self.pattern = pattern

        # Whether or not the pattern is a regex string
        self.is_regex = is_regex

        # Variables for subpatterns - a dictionary mapping to other StringPatterns or UnionPattern objects
        self.variables = variables
        if self.variables is None:
            self.variables = dict()

        # A dictionary of replacements to perform on matching strings before further parsing
        self.replacements = replacements

        # Optionally skip the node in the tree
        self.skip_node = skip_node

        # Specify the path to value.
        self.value_path = value_path

        # The data type of matching values
        self.type = data_type

        # The definitions that apply - only to a certain context
        self.definitions = None

        # Record the last definition this pattern has seen
        self.definition_context = None

        # Record the variable locations for speed
        self.variable_locations = dict()

        for i in range(0, len(self.pattern)):
            for var, sub_pattern in self.variables.items():
                if self.pattern[i:i + len(var)] == var:
                    # Add the location
                    self.variable_locations[i] = {
                        "label": var,
                        "pattern": sub_pattern
                    }

        # Build the non-variable locations
        self.non_variable_locations = None
        self.get_non_variable_locations()

    def get_non_variable_locations(self):

        var_locations = [index for index in self.variable_locations]

        self.non_variable_locations = dict()
        i = 0
        while i < len(self.pattern):
            if i in self.variable_locations:
                i += len(self.variable_locations[i]["label"])
                continue

            # Otherwise, i will be in non_var_locations

            # Get the next variable location
            var_locations = [j for j in var_locations if j > i]
            if len(var_locations) == 0:
                # There are none left - go until the end
                self.non_variable_locations[i] = self.pattern[i:]
                break

            else:
                end = min(var_locations)
                self.non_variable_locations[i] = self.pattern[i:end]
                i = end

    def make_replacements(self, s):
        # Make replacements on a string s

        if self.replacements is None:
            # No replacements
            return s

        for key, value in self.replacements.items():
            s = s.replace(key, value)

        return s

    def match(self, s, context, pattern_offset=0, pattern_match=None):
        # Match a string s against this pattern with the given context.
        # Optionally offset the pattern string, to start at an index > 0. This is used recursively.

        parent_pattern_match = None
        if self.parent is not None:

            # Create a new context with variables in the string_variables
            new_context = context.get_copy()
            new_context.string_variables.update(self.variables)

            parent_pattern_match = self.parent.match(s, new_context, pattern_match=pattern_match)

        if type(s) is UnionPattern:
            # We'd need every pattern in the union to match self. Would be unusual as unions don't normally intersect

            for sub in s.patterns:
                result = self.match(sub, context)
                if result is None:
                    # No match for this sub pattern
                    return None

            # All sub patterns match
            return Match(
                pattern=self,
                string=s,
                parent_pattern_match=parent_pattern_match
            )

        string_variables = context.string_variables

        if type(s) is StringPattern:
            # Need to ensure this pattern matches.

            if s is self:
                return Match(
                    pattern=self,
                    string=self,
                    parent_pattern_match=parent_pattern_match
                )

            if s.is_regex or self.is_regex:
                # Can't mix with regex
                return None

            # Store the pattern
            pattern_match = s

            # Use the pattern string
            s = s.pattern

        if pattern_match is not None:
            # This is also a pattern match

            # Edit the context string variables to include the pattern
            string_variables = context.string_variables.copy()
            string_variables.update(pattern_match.variables)

        # Create an optimistic match
        m = Match(
            pattern=self,
            string=s,
            parent_pattern_match=parent_pattern_match
        )

        if pattern_offset == 0:

            # Check if the whole string is a variable
            for svar, sub_pattern in string_variables.items():
                if s == svar and self.match(sub_pattern, context):
                    # Match!
                    return self.meets_condition(m, context)

        if self.is_regex:
            # Use the regex match function
            return self.match_regex(s)

        # Rule out a match if the sequence of non-variable characters does not exist in s
        index = 0

        # Build a non-variable mapping - so we know where the possible positions are for each non-variable string
        non_variable_mapping = []

        for part_index, pattern_part in self.non_variable_locations.items():

            if part_index < pattern_offset:
                # Ignore this part
                continue

            # Find the next occurrence of s_part in s, starting from the previous index
            next_index = s[index:].find(pattern_part)

            # Add to non variable mapping
            non_variable_mapping.append([pattern_part, [index + next_index]])

            if next_index == -1:
                return None

            index = index + next_index + 1

        if pattern_offset in self.variable_locations:
            # Add any other legal non variable mappings
            for i in range(0, len(non_variable_mapping)):
                pattern_part, lst = non_variable_mapping[i]
                start_index = lst[0]

                max_index = len(s)
                if i < len(non_variable_mapping) - 1:
                    # There is a next item
                    max_index = non_variable_mapping[i + 1][1][0]

                # Search for further instances of pattern_part in s, and add the index of these to lst
                next_index = start_index + 1
                while next_index < max_index:
                    increment = s[next_index:].find(pattern_part)
                    next_index += increment

                    if increment > -1:
                        lst.append(next_index)
                        next_index += 1
                    else:
                        break

        # Convert to a dictionary
        non_variable_mapping = {item[0]: item[1] for item in non_variable_mapping}

        if pattern_offset == 0:

            # Get the definitions for this pattern
            self.get_definitions(context)

            # Check if there is an applicable definition
            for defn in self.definitions:
                # Try the definition

                if defn["valid"]:
                    result = defn["definition"].apply(s, self, context)

                    if result is not None:
                        return result

        # Get the pattern string, excluding any initial offset
        pattern = self.pattern[pattern_offset:]

        if len(self.variables) == 0:
            # No variables

            if s == pattern:
                # Valid match
                if pattern_offset == 0:
                    return self.meets_condition(m, context)

                return m

            # Otherwise, no match
            return None

        # Otherwise, there are variables. Check the pattern character by character.

        # NB this can't be done with regex - could be multiple matches with the same starting position only one of
        # which is valid

        if len(pattern) == 0 and len(s) == 0:
            # Easy case
            if pattern_offset == 0:
                return self.meets_condition(m, context)

            return m

        if (len(pattern) == 0 and len(s) > 0) or (len(pattern) > 0 and len(s) == 0):
            # No match
            return None

        # Check if this is a variable
        if pattern_offset in self.variable_locations:
            # Looks like a variable

            var = self.variable_locations[pattern_offset]["label"]
            sub_pattern = self.variable_locations[pattern_offset]["pattern"]

            # Check if there is a matching string variable in s
            for string_var, str_pattern in string_variables.items():
                if not s[:len(string_var)] == string_var:
                    continue

                # This looks like a string variable. Check the variable type is the same or part of a union
                if str_pattern is sub_pattern or \
                        (type(sub_pattern) is UnionPattern and str_pattern in sub_pattern.nested_options()):
                    # These refer to the same pattern

                    # Check the remainder of s also matches
                    remainder = s[len(string_var):]

                    remainder_match = self.match(
                        remainder,
                        context,
                        pattern_offset=pattern_offset + len(var),
                        pattern_match=pattern_match
                    )

                    if remainder_match is None:
                        continue

                    # Match! Check for sub_match conflicts

                    if var in remainder_match.sub_matches:
                        remainder_sub = remainder_match.sub_matches[var]
                        if not (remainder_sub.pattern == sub_pattern and remainder_sub.string == string_var):
                            # There's a conflict with this variable later in the string
                            continue

                    # Otherwise, copy the sub_matches to m and return
                    for name, sub in remainder_match.sub_matches.items():
                        m.add_submatch(name, sub)

                    # Add the string variable
                    m.add_submatch(var, sub_pattern.match(string_var, context))

                    if pattern_offset == 0:
                        return self.meets_condition(m, context)

                    return m

            # Check what comes after the variable in the pattern to filter what to do
            next_offset = pattern_offset + len(var)
            if next_offset == len(self.pattern):
                # This is the final part of the pattern
                possible_js = [len(s)]

            elif next_offset in self.variable_locations:
                # There is another variable immediately following this one

                # Loop through the possibilities for the variable in s
                possible_js = range(0, len(s) + 1)

            else:
                # Must be a non-variable string
                assert next_offset in self.non_variable_locations

                pattern_part = self.non_variable_locations[next_offset]

                # Get the possible positions of the pattern part in s
                possible_js = non_variable_mapping[pattern_part]

            # Loop through the possibilities for the variable in s
            for j in possible_js:

                # Get the substring of s
                sub_s = s[:j]

                # Check if the remainder of the string is a match
                remainder_match = self.match(
                    s[j:],
                    context,
                    pattern_offset=pattern_offset + len(var),
                    pattern_match=pattern_match
                )

                if remainder_match is None:
                    j += 1
                    continue

                # The remainder matches

                # Test if this sub_match is valid
                sub_match = sub_pattern.match(sub_s, context, pattern_match=pattern_match)

                if sub_match is None:
                    j += 1
                    continue

                # Match!

                # Check for conflicts with the sub_matches
                if var in remainder_match.sub_matches:
                    remainder_sub = remainder_match.sub_matches[var]
                    if not (remainder_sub.pattern == sub_pattern and remainder_sub.string == sub_s):
                        # There's a conflict with this variable later in the string
                        j += 1
                        continue

                # Otherwise, copy the sub_matches to m and return
                for name, sub in remainder_match.sub_matches.items():
                    m.add_submatch(name, sub)

                # Add the string variable
                m.add_submatch(var, sub_match)

                if pattern_offset == 0:
                    return self.meets_condition(m, context)

                return m

        # Not a variable - check for literal character match
        if pattern_offset not in self.non_variable_locations:
            # No match
            return None

        part = self.non_variable_locations[pattern_offset]

        if part == s[:len(part)]:
            # Skip past the part in s and in the pattern

            remainder_match = self.match(
                s[len(part):],
                context,
                pattern_offset=pattern_offset + len(part),
                pattern_match=pattern_match
            )

            if remainder_match is not None:
                # Success

                # Copy the sub_matches to m and return
                for name, sub in remainder_match.sub_matches.items():
                    m.add_submatch(name, sub)

                if pattern_offset == 0:
                    return self.meets_condition(m, context)

                return m

        # Otherwise, no match
        return None

    def match_regex(self, s):
        # Try to match a string s with the pattern

        for re_match in re.finditer(self.pattern, s, overlapped=True):

            if re_match is None:
                # No match
                continue

            return Match(
                pattern=self,
                string=self.make_replacements(s)
            )

        # No matches
        return None

    def add_variable(self, name, pattern):
        # Add a variable
        self.variables[name] = pattern

        # Update the variable locations
        for i in range(0, len(self.pattern)):
            if self.pattern[i:i + len(name)] == name:
                # Add the location
                self.variable_locations[i] = {
                    "label": name,
                    "pattern": pattern
                }

        self.get_non_variable_locations()

    def get_definitions(self, context):
        # Get the relevant definitions for this pattern

        if self.definitions is not None and context == self.definition_context:
            # Context hasn't changed, and we already have definitions

            # Need to check for any definitions that have new variables
            for dct in self.definitions:
                if dct["variables"] == dct["definition"].variables:
                    # This definition has no new variables
                    continue

                # Update the variables
                dct["variables"] = dct["definition"].variables.copy()

                # Assume it's invalid
                dct["valid"] = False

                # Check if it works
                result = dct["definition"].applies_to_pattern(pattern=self, context=context)

                if result is not None:
                    # It's valid
                    dct["valid"] = True
                    dct["mapping"] = result

            return

        # Otherwise, we need to get the definitions

        # Update the definition context (using a copy)
        self.definition_context = context.get_copy()

        # Get from context definitions that apply to this pattern
        vars = context.variables
        defns = [vars[key] for key in vars if type(vars[key]) is Definition]

        # Assume they are all invalid
        self.definitions = [
            {
                "definition": defn,
                "variables": defn.variables.copy(),
                "valid": False,
                "mapping": None
            } for defn in defns
        ]

        for dct in self.definitions:
            defn = dct["definition"]

            # Check if it works
            result = defn.applies_to_pattern(pattern=self, context=context)

            if result is not None:
                # It's valid
                dct["valid"] = True
                dct["mapping"] = result

    def __str__(self):
        return self.name


class UnionPattern(Pattern):
    # A union of patterns

    def __init__(self, name, patterns, condition=None, skip_node=False, value_path="union_value()", data_type=None, parent=None):

        Pattern.__init__(self, name, parent, condition)

        # The list of patterns
        self.patterns = patterns

        # The value path
        self.value_path = value_path

        # The data type
        self.type = data_type

        # Skip the node in matches
        self.skip_node = skip_node

    def match(self, s, context, pattern_match=None):
        # Match s against one of the patterns

        if type(s) is StringPattern:
            # This could match the union pattern.

            if s is self:
                return Match(
                    pattern=self,
                    string=self
                )

        if s in context.string_variables:
            pattern = context.string_variables[s]

            if pattern is self:
                return Match(
                    pattern=self,
                    string=s
                )

        # Create an optimistic match object
        union_match = Match(
            pattern=self,
            string=s
        )

        for pattern in self.patterns:

            match = None

            try:
                match = pattern.match(s, context, pattern_match=pattern_match)

            except Exception as e:
                # No match here
                pass

            if match is not None:
                # Looks like a successful match

                # Check the condition
                if self.meets_condition(match, context) is not None:
                    # Success!
                    union_match.add_submatch(pattern.name, match)
                    return union_match

        # No match
        return None

    def nested_options(self, found=None):
        # Get a set of all string patterns in this union - and any sub-unions

        if found is None:
            # Start with an empty set
            found = set()

        for p in self.patterns:
            if type(p) is UnionPattern and p not in found:
                found = found.union(p.nested_options())

            found.add(p)

        return found

    def __str__(self):
        return self.name


class LatticeCompiler(object):

    def __init__(self):

        # Build a dictionary for inbuilt system functions

        variable_name = StringPattern(
            name="variable_name",
            pattern=r"^[a-zA-Z_][[:alnum:]_]*$",
            is_regex=True,
            value_path="lookup()"
        )

        # Booleans
        boolean = UnionPattern(
            name="boolean",
            patterns=[
                StringPattern(
                    name="True",
                    pattern="True",
                    data_type="boolean",
                    value_path="item()"
                ),
                StringPattern(
                    name="False",
                    pattern="False",
                    data_type="boolean",
                    value_path="item()"
                ),
                StringPattern(
                    name="variable_boolean",
                    pattern="var",
                    variables={"var": variable_name},
                    value_path="var.lookup()"
                )
            ]
        )

        # String replacements for escaped characters in raw strings
        string_replacements = {
            "\\\"": "\"",
            "\\'": "'",
            "\\\\": "\\"
        }

        double_quotes_inner = StringPattern(
            name="double_quotes_inner",
            pattern=r"^(?:[^\"\\]|\\.)*$",
            is_regex=True,
            replacements=string_replacements,
            data_type="string"
        )
        single_quotes_inner = StringPattern(
            name="single_quotes_inner",
            pattern=r"^(?:[^\'\\]|\\.)*$",
            is_regex=True,
            replacements=string_replacements,
            data_type="string"
        )

        string = UnionPattern(
            name="string",
            patterns=[
                StringPattern(
                    name="double_quotes",
                    pattern='"value"',
                    variables={"value": double_quotes_inner},
                    value_path="value.item()"
                ),
                StringPattern(
                    name="single_quotes",
                    pattern="'value'",
                    variables={"value": single_quotes_inner},
                    value_path="value.item()"
                ),
                StringPattern(
                    name="variable_string",
                    pattern="var",
                    variables={"var": variable_name},
                    value_path="var.lookup()"
                )
            ]
        )

        # Comma separated strings
        css = UnionPattern(
            name="comma_separated_string",
            patterns=[
                StringPattern(
                    name="single",
                    pattern="s",
                    variables={"s": string},
                    skip_node=True
                ),
                StringPattern(
                    name="join",
                    pattern="j, s",
                    variables={"s": string},
                    skip_node=True
                )
            ],
            skip_node=True
        )
        css.patterns[1].add_variable("j", css)

        # Object - any kind of item. More added later
        obj = UnionPattern(
            name="object",
            patterns=[
                boolean,
                string,
                variable_name
            ]
        )

        # Comma separated object
        cso = UnionPattern(
            name="comma_separated_object",
            patterns=[
                StringPattern(
                    name="single",
                    pattern="obj",
                    variables={"obj": obj},
                    skip_node=True
                ),
                StringPattern(
                    name="join",
                    pattern="j, obj",
                    variables={"obj": obj},
                    skip_node=True
                )
            ],
            skip_node=True
        )
        cso.patterns[1].add_variable("j", cso)

        # List
        lst = UnionPattern(
            name="list",
            patterns=[
                StringPattern(
                    name="empty_list",
                    pattern="[]",
                    value_path="empty_list()",
                    data_type="list"
                ),
                StringPattern(
                    name="literal_list",
                    pattern="[cso]",
                    variables={"cso": cso},
                    value_path="item()",
                    data_type="list"
                ),
                StringPattern(
                    name="variable_list",
                    pattern="var",
                    variables={"var": variable_name}
                )
            ]
        )

        # Lists are objects too
        obj.patterns.append(lst)

        # Dictionaries
        dictionary_part = StringPattern(
            name="dictionary_part",
            pattern="key: value",
            variables={"key": string, "value": obj}
        )

        csdp = UnionPattern(
            name="comma_separated_dictionary_parts",
            patterns=[
                StringPattern(
                    name="single",
                    pattern="part",
                    variables={"part": dictionary_part},
                    skip_node=True
                ),
                StringPattern(
                    name="join",
                    pattern="j, part",
                    variables={"part": dictionary_part},
                    skip_node=True
                )
            ],
            skip_node=True
        )
        csdp.patterns[1].add_variable("j", csdp)

        dct = UnionPattern(
            name="dictionary_union",
            patterns=[
                StringPattern(
                    name="empty_dictionary",
                    pattern="{}",
                    value_path="empty_dict()"
                ),
                StringPattern(
                    name="dictionary",
                    pattern="{csdp}",
                    variables={"csdp": csdp},
                    value_path="dict()"
                ),
                StringPattern(
                    name="variable_dictionary",
                    pattern="var",
                    variables={"var": variable_name}
                )

            ],
        )

        # Dictionary is an object
        obj.patterns.append(dct)

        # Function arguments
        arg = UnionPattern(
            name="argument",
            patterns=[
                StringPattern(
                    name="labelled_argument",
                    pattern="label=obj",
                    variables={"label": variable_name, "obj": obj},
                    value_path="obj.value()"
                ),
                StringPattern(
                    name="unlabelled_argument",
                    pattern="obj",
                    variables={"obj": obj},
                    value_path="obj.value()"
                )
            ]
        )

        # Comma separated arguments
        csa = UnionPattern(
            name="comma_separated_arguments",
            patterns=[
                StringPattern(
                    name="single",
                    pattern="a",
                    variables={"a": arg},
                    skip_node=True
                ),
                StringPattern(
                    name="join",
                    pattern="j, a",
                    variables={"a": arg},
                    skip_node=True
                )
            ],
            skip_node=True
        )
        csa.patterns[1].add_variable("j", csa)

        # string pattern
        string_pattern = UnionPattern(
            name="string_pattern",
            patterns=[
                StringPattern(
                    name="string_pattern",
                    pattern="StringPattern(csa)",
                    variables={"csa": csa},
                    value_path="csa.make_pattern()"
                ),
                StringPattern(
                    name="variable_string_pattern",
                    pattern="var",
                    variables={"var": variable_name},
                    value_path="var.lookup()"
                )
            ]
        )

        # Union pattern
        union_pattern = UnionPattern(
            name="union_pattern",
            patterns=[
                StringPattern(
                    name="union_pattern",
                    pattern="UnionPattern(csa)",
                    variables={"csa": csa},
                    value_path="csa.make_union()"
                ),
                StringPattern(
                    name="variable_union_pattern",
                    pattern="var",
                    variables={"var": variable_name},
                    value_path="var.lookup()"
                )
            ]
        )

        # String or union pattern
        pattern = UnionPattern(
            name="pattern",
            patterns=[string_pattern, union_pattern]
        )

        # Patterns are objects
        obj.patterns.append(pattern)

        # Definitions
        defn = StringPattern(
            name="definition",
            pattern="define(csa)",
            variables={
                "csa": csa
            },
            value_path="make_defn()"
        )

        # Definitions are objects
        obj.patterns.append(defn)

        # Build string definition patterns - 'with'
        with_part = StringPattern(
            name="with_part",
            pattern="css as pattern",
            variables={
                "css": css,
                "pattern": string_pattern
            }
        )

        # Comma separated with parts
        cswp = UnionPattern(
            name="comma_separated_with_parts",
            patterns=[
                StringPattern(
                    name="single",
                    pattern="wp",
                    variables={"wp": with_part},
                    skip_node=True
                ),
                StringPattern(
                    name="join",
                    pattern="j, wp",
                    variables={"wp": with_part},
                    skip_node=True
                )
            ],
            skip_node=True
        )
        cswp.patterns[1].add_variable("j", cswp)

        # Leading spaces - must be a multiple of 4
        spaces = StringPattern(
            name="spaces",
            pattern=r"^(?:\s\s\s\s)*$",
            is_regex=True
        )

        # Define lines for indenting blocks
        indenting = StringPattern(
            name="indenting",
            pattern="^ *[^ #].*:$",
            is_regex=True
        )

        # System lookup pattern
        system_lookup = StringPattern(
            name="system_lookup",
            pattern="system[key]",
            variables={"key": string},
            value_path="key.system_lookup()"
        )
        # System lookups are objects
        obj.patterns.append(system_lookup)

        # System assignment
        system_assignment = StringPattern(
            name="system_assignment",
            pattern="system[key] = value",
            variables={
                "key": string,
                "value": obj
            },
            value_path="system_assignment()"
        )

        # Matches
        match = UnionPattern(
            name="match",
            patterns=[
                StringPattern(
                    name="match",
                    pattern="p.match(s)",
                    variables={
                        "p": pattern,
                        "s": string
                    },
                    value_path="make_match()"
                ),
                StringPattern(
                    name="variable_match",
                    pattern="var",
                    variables={"var": variable_name},
                    value_path="var.lookup()"
                )
            ]
        )

        # Matches are objects
        obj.patterns.append(match)

        # Pattern attributes
        pattern_attribute = StringPattern(
            name="pattern_attribute",
            pattern="match.attribute",
            variables={
                "match": match,
                "attribute": variable_name
            },
            value_path="get_attribute()"
        )
        obj.patterns.append(pattern_attribute)

        # Conditions for matching

        # Items
        simple_item = StringPattern(name="simple_item", pattern="^[a-zA-Z_\.][[:alnum:]_\.\[\]]*$", is_regex=True)
        pattern_or_item = UnionPattern(
            name="pattern_or_item",
            patterns=[pattern]
        )
        instances = StringPattern(
            name="instances",
            pattern="item.instances(pattern)",
            variables={
                "pattern": pattern_or_item
            }
        )

        item = UnionPattern(
            name="item",
            patterns=[simple_item, instances]
        )
        pattern_or_item.patterns.append(item)

        instances.add_variable("item", item)

        # Atomic conditions
        equal = StringPattern(
            name="equal",
            pattern="left == right",
            variables={
                "left": item,
                "right": item
            }
        )

        membership = StringPattern(
            name="membership",
            pattern="item in set",
            variables={
                "item": item,
                "set": item
            }
        )
        negative_membership = StringPattern(
            name="negative_membership",
            pattern="item not in set",
            variables={
                "item": item,
                "set": item
            }
        )

        item_and_condition = StringPattern(
            name="item_and_condition",
            pattern="item, condition",
            variables={"item": item}
        )

        condition_args = UnionPattern(
            name="condition_args",
            patterns=[
                StringPattern(name="empty", pattern=""),
                item,
                item_and_condition
            ]
        )

        function = StringPattern(
            name="function",
            pattern="item.func(args)",
            variables={
                "item": item,
                "args": condition_args,
                "func": StringPattern(name="function_name", pattern="^(has_parent|equal_any|instances|indent_lines)$", is_regex=True)
            }
        )

        # Function can also be an item
        item.patterns.append(function)

        each = StringPattern(
            name="each",
            pattern="each(items, condition)",
            variables={
                "items": item
            }
        )

        replace_equivalent = StringPattern(
            name="replace_equivalent",
            pattern="item.replace_equivalent(other, x, y)",
            variables={
                "item": item,
                "other": item,
                "x": item,
                "y": item
            }
        )

        # Molecular conditions
        negation = StringPattern(name="negation", pattern="not condition")
        logical_and = StringPattern(name="and", pattern="left and right")
        logical_or = StringPattern(name="or", pattern="left or right")
        brackets = StringPattern(name="brackets", pattern="(inner)")

        condition = UnionPattern(
            name="condition",
             patterns=[
                 item,
                 equal,
                 membership,
                 negative_membership,
                 function,
                 each,
                 replace_equivalent,
                 negation,
                 logical_and,
                 logical_or,
                 brackets
             ]
        )

        item_and_condition.add_variable("condition", condition)
        function.add_variable("condition", condition)
        each.add_variable("condition", condition)
        negation.add_variable("condition", condition)
        logical_and.add_variable("left", condition)
        logical_and.add_variable("right", condition)
        logical_or.add_variable("left", condition)
        logical_or.add_variable("right", condition)
        brackets.add_variable("inner", condition)

        # Condition object
        condition_object = UnionPattern(
            name="condition_union",
            patterns=[
                StringPattern(
                    name="condition",
                    pattern="Condition(x)",
                    variables={"x": condition},
                    value_path="make_condition()"
                ),
                StringPattern(
                    name="variable_pattern",
                    pattern="var",
                    variables={"var": variable_name},
                    value_path="var.lookup()"
                )
            ]
        )

        obj.patterns.append(condition_object)

        # Attributes
        attribute = UnionPattern(
            name="attribute_union",
            patterns=[
                item,
                StringPattern(
                    name="instances",
                    pattern="instances(args)",
                    variables={
                        "args": csa
                    }
                ),
                StringPattern(
                    name="variable_attribute",
                    pattern="var",
                    variables={"var": variable_name},
                    value_path="var.lookup()"
                )
            ]
        )
        obj.patterns.append(attribute)

        # Formal systems
        fs = UnionPattern(
            name="formal_system_union",
            patterns=[
                StringPattern(
                    name="formal_system",
                    pattern="FormalSystem(args)",
                    variables={"args": csa},
                    value_path="make_formal_system()"
                ),
                StringPattern(
                    name="variable_formal_system",
                    pattern="var",
                    variables={"var": variable_name},
                    value_path="var.lookup()"
                )
            ]
        )
        # Formal system is an object
        obj.patterns.append(fs)

        # Line types
        line_type = UnionPattern(
            name="line_type_union",
            patterns=[
                StringPattern(
                    name="line_type",
                    pattern="LineType(args)",
                    variables={"args": csa},
                    value_path="make_line_type()"
                ),
                StringPattern(
                    name="variable_line_type",
                    pattern="var",
                    variables={"var": variable_name},
                    value_path="var.lookup()"
                )
            ]
        )
        # Line type is an object
        obj.patterns.append(line_type)

        # Inference rules
        inference_rule = UnionPattern(
            name="inference_rule",
            patterns=[
                StringPattern(
                    name="inference_rule",
                    pattern="InferenceRule(args)",
                    variables={"args": csa},
                    value_path="make_inference_rule()"
                ),
                StringPattern(
                    name="variable_inference_rule",
                    pattern="var",
                    variables={"var": variable_name},
                    value_path="var.lookup()"
                )
            ]
        )
        # Inference rules are object
        obj.patterns.append(inference_rule)

        # Build the system dictionary
        self.system = {
            "boolean": boolean,
            "string": string,
            "list": lst,
            "variable_name": variable_name,
            "pattern": pattern,
            "union_pattern": union_pattern,
            "definition": defn,
            "object": obj,
            "indenting_lines": indenting,
            "comma_separated_arguments": csa,
            "comma_separated_with_parts": cswp,
            "spaces": spaces,
            "condition": condition_object,
            "attribute": attribute,
            "formal_system": fs,
            "line_type": line_type,
            "inference_rule": inference_rule
        }

        self.line_options = {
            "empty": StringPattern(
                name="empty",
                pattern="^ *$",
                is_regex=True
            ),

            "comment": StringPattern(
                name="comment",
                pattern=r"^ *#.*$",
                is_regex=True
            ),

            "print": StringPattern(
                name="print",
                pattern="Sprint(obj)",
                variables={
                    "S": spaces,
                    "obj": self.system["object"]
                }
            ),

            "assignment": StringPattern(
                name="assignment",
                pattern="Svar = obj",
                variables={
                    "S": spaces,
                    "var": self.system["variable_name"],
                    "obj": self.system["object"]
                }
            ),

            "system_assignment": StringPattern(
                name="system_assignment",
                pattern="Ssystem[var] = obj",
                variables={
                    "S": spaces,
                    "var": self.system["string"],
                    "obj": self.system["object"]
                }
            ),

            "sub_pattern_assignment": StringPattern(
                name="sub_pattern_assignment",
                pattern="Spattern.label = sub",
                variables={
                    "S": spaces,
                    "pattern": UnionPattern(
                        name="pattern_or_defn",
                        patterns=[self.system["variable_name"]]
                    ),
                    "label": self.system["variable_name"],
                    "sub": self.system["pattern"]
                }
            ),

            "sub_pattern_dict_assignment": StringPattern(
                name="sub_pattern_dict_assignment",
                pattern="Spattern.add_variable(label, sub)",
                variables={
                    "S": spaces,
                    "pattern": self.system["pattern"],
                    "label": self.system["string"],
                    "sub": self.system["pattern"]
                }
            ),

            "add_pattern_attribute": StringPattern(
                name="add_pattern_attribute",
                pattern="Spattern.add_attribute(csa)",
                variables={
                    "S": self.system["spaces"],
                    "pattern": self.system["variable_name"],
                    "csa": self.system["comma_separated_arguments"]
                }
            ),

            "set_pattern_condition": StringPattern(
                name="set_pattern_condition",
                pattern="Spattern.set_condition(x)",
                variables={
                    "S": self.system["spaces"],
                    "pattern": self.system["variable_name"],
                    "x": self.system["condition"]
                }
            ),

            "string_variable_definition": StringPattern(
                name="string_variable_definition",
                pattern="Swith cswp:",
                variables={
                    "S": spaces,
                    "cswp": cswp
                }
            ),

            "string_variable_restriction": StringPattern(
                name="string_variable_restriction",
                pattern="Ssuppose R",
                variables={
                    "S": spaces,
                    "R": string
                }
            )
        }

    @staticmethod
    def parse_match(key, match, context):

        if key == "print":
            # Print something

            # Get the object
            obj = match.get_by_path("obj.value()", context)
            print(obj)

        elif key == "assignment":
            # Make the assignment

            # Get the variable name
            variable = match.get_by_path("var.string()", context)

            # Get the assigned value
            value = match.get_by_path("obj.value()", context)

            context.variables[variable] = value

        elif key == "system_assignment":
            # Make an assignment to the system context variable

            # Get the variable name
            variable = match.get_by_path("var.value()", context)

            # Get the assigned value
            value = match.get_by_path("obj.value()", context)

            context.system[variable] = value

        elif key in ("sub_pattern_assignment", "sub_pattern_dict_assignment"):
            # Sub assignment

            # Get the pattern (or definition) instance
            pattern_instance = match.get_by_path("pattern.value()", context)

            # Get the label
            if key == "sub_pattern_assignment":
                label = match.get_by_path("label.string()", context)
            else:
                label = match.get_by_path("label.value()", context)

            # Get the sub pattern
            sub_pattern = match.get_by_path("sub.value()", context)

            # Add the sub_match
            pattern_instance.add_variable(label, sub_pattern)

        elif key == "add_pattern_attribute":
            # Add pattern attribute

            pattern = match.get_by_path("pattern.value()", context)

            # Get the arguments
            args = match.get_by_path("csa.a", context)

            # Handle cases regardless of labelling
            arg_dict = {}
            next_label = "name"
            for arg in args:
                a = arg.get_sub_matches()
                if "labelled_argument" in a:
                    la = a["labelled_argument"]
                    subs = la.get_sub_matches()
                    arg_dict[subs["label"].string] = subs["obj"].get_value(context)

                elif "unlabelled_argument" in a:
                    arg_dict[next_label] = a["unlabelled_argument"].get_value(context)

                    if next_label == "name":
                        next_label = "value"

            # Add the attribute to the pattern
            pattern.add_attribute(**arg_dict)

        elif key == "set_pattern_condition":
            # Set the condition

            subs = match.get_sub_matches()
            pattern = subs["pattern"].get_value(context)
            condition = subs["x"].get_value(context)

            pattern.condition = condition

        elif key == "string_variable_definition":
            # A new string variable

            # Get each of the pattern parts
            parts = match.get_by_path("wp", context)

            if type(parts) is not list:
                # Encourage the parts to be a list
                parts = [parts]

            for part in parts:

                # Get the pattern and the strings
                pattern_instance = part.get_by_path("pattern.value()", context)
                strings = part.get_by_path("s", context)

                if type(strings) is not list:
                    # Encourage the strings to be a list
                    strings = [strings]

                for string in strings:
                    s = string.get_by_path("value()", context)

                    # Add to the pattern instance
                    context.string_variables[s] = pattern_instance

        elif key == "string_variable_restriction":
            # Restriction for a string variable

            # Get the restriction
            restriction = match.get_by_path("R.value()", context)

            # Add the restriction to context
            context.add_restriction(restriction)

    def parse(self, code, context=None, line_number_offset=0):
        # Parse the code

        # Maintain context variables
        if context is None:
            context = Context()
            context.system = self.system

        # Split into lines
        lines = code.split("\n")

        i = 0
        while i < len(lines):
            line = lines[i]
            line_number = line_number_offset + i + 1

            valid = False

            # Check the inbuilt language options
            for key, option in self.line_options.items():

                # Try to make the match
                match = option.match(line, context)

                if match is None:
                    continue

                # There is a match
                valid = True

                # Check if this is an indenting block
                indenting = self.system["indenting_lines"]
                if indenting.match(line, context):
                    # Indenting
                    spaces = len(line) - len(line.lstrip())

                    # Find the next line with this number of leading spaces
                    j = i + 1
                    while j < len(lines):
                        block_line = lines[j]

                        if len(block_line) - len(block_line.lstrip()) == spaces and len(block_line.lstrip()) > 0:
                            # This is the outdenting line
                            break

                        j += 1

                    # Copy the context for a new scope
                    new_context = context.get_copy()

                    # Parse this line in the new scope
                    self.parse_match(key, match, new_context)

                    # Compile the block
                    block = "\n".join(lines[i + 1:j])
                    self.parse(block, new_context, line_number_offset=i + 1)

                    # Continue from after the block
                    i = j - 1
                    break

                self.parse_match(key, match, context)

                # Found a match
                break

            if not valid:
                # Couldn't parse this line
                raise Exception("Could not parse line " + str(line_number) + ": " + line)

            i += 1

        return context


if __name__ == "__main__":
    lc = LatticeCompiler()

    with open("propositional.py") as f:
        context = lc.parse(f.read())

    if "formal_system" in context.system:
        system = context.system["formal_system"]

        with open("proof.txt") as f:
            system.parse(f.read())
