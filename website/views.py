from django.shortcuts import render
from django.http import HttpResponse
import json
from .models import *


def indexView(request):
    # Index view

    imp, pv, formula, neg = StringPattern.objects.all()[:4]
    fs = FormalSystem.objects.all()[0]

    # Clear any trees and definitions
    Tree.objects.all().delete()

    # Make an initial context
    context = {
        "variables": {
            "p": pv,
            "q": pv,
            "f": formula,
            "g": formula,
            "h": formula
        },
        "definitions": list(Definition.objects.all()),
        "dependents": []
    }

    # # Create the \land definition
    # lower_pattern = StringPattern.objects.create(
    #     slug="land",
    #     pattern=r"\\neg \((?P<f>(?&formula)) r \\neg (?P<g>(?&formula))\)"
    # )
    # lower_pattern.add_label("f", formula)
    # lower_pattern.add_label("g", formula)
    #
    # higher_pattern = StringPattern.objects.create(
    #     slug="land_higher",
    #     pattern=r"\((?P<f>(?&formula)) \\land (?P<g>(?&formula))\)"
    # )
    # higher_pattern.add_label("f", formula)
    # higher_pattern.add_label("g", formula)
    #
    # d = Definition.objects.create(
    #     string_pattern=formula,
    #     lower_pattern=lower_pattern,
    #     higher_pattern=higher_pattern
    # )
    #
    # context["definitions"].append(d)
    #
    # # Create the harder multiple \land definition
    #
    # # Make an intermediate StringPattern for joining lands
    # land_join = StringPattern.objects.create(
    #     slug="land_join",
    #     pattern=r"(?:(?P<left>(?&formula)) \\land (?P<sub>(?&land_join)))|(?P<f>(?&formula))",
    #     skip_node=True
    # )
    # land_join.add_label("f", formula)
    # land_join.add_label("sub", land_join)
    # land_join.add_label("left", formula)
    #
    # # Make the definition
    # lower_pattern = StringPattern.objects.create(
    #     slug="nested_land",
    #     pattern=r"\((?P<left>(?&formula)) \\land (?P<right>(?&land_join))\)"
    # )
    # lower_pattern.add_label("left", formula)
    # lower_pattern.add_label("right", land_join)
    #
    # higher_pattern = StringPattern.objects.create(
    #     slug="nested_land_higher",
    #     pattern=r"\((?P<inner>(?&land_join))\)"
    # )
    # higher_pattern.add_label("inner", land_join)
    #
    # d2 = Definition.objects.create(
    #     string_pattern=formula,
    #     lower_pattern=lower_pattern,
    #     higher_pattern=higher_pattern
    # )
    #
    # context["definitions"].append(d2)

    land_join = StringPattern.objects.get(slug="land_join")
    context["dependents"] = [formula, imp, neg]

    context["dependents"].extend({fs.formula_join_pattern, fs.formula_set_pattern, fs.proof_line_pattern})

    # tree = fs.parse_proof_line(r"{f, (f r g)} \vdash f", context)
    print(fs.proof_line_pattern.regex(context))
    tree = fs.proof_line_pattern.create_tree(r"{(f r \neg g), f, \neg g} \vdash (f r (g r \neg (\neg f r f)))", context=context)
    print(tree.pretty_print())

    # # Create the \leftrightarrow definition
    # pattern = r"((f r g) \land (g r f))"
    # lower_tree = fs.parse_string(pattern, context)
    #
    # higher_pattern = StringPattern.objects.create(
    #     slug="equivalent",
    #     pattern=r"\((?P<f>(?&formula)) \\leftrightarrow (?P<g>(?&formula))\)"
    # )
    # d2 = Definition.objects.create(
    #     string_pattern=formula,
    #     lower_tree=lower_tree,
    #     higher_pattern=higher_pattern
    # )
    #
    # context["definitions"].append(d2)

    # t1 = fs.parse_string(r"(p_0 \leftrightarrow p_1)", context=context)

    return HttpResponse("")


def formalSystemView(request, system_slug):
    # View for a formal system

    system = FormalSystem.objects.get(slug=system_slug)

    return render(request, "website/formal_system.html", {
        "system": system
    })


def proofEditorView(request, system_slug):
    # View for editing a proof

    system = FormalSystem.objects.get(slug=system_slug)

    return render(request, "website/proof_editor.html", {
        "system": system
    })


def updateFormulaDefinition(request):
    # Ajax view to update a formula definition

    try:
        fd_id = request.POST.get("formula_definition_id", False)
        fd = FormulaDefinition.objects.get(id=fd_id)

        pattern = request.POST.get("pattern", False)
        if pattern:
            fd.pattern = pattern
            fd.save()

        return HttpResponse(json.dumps({
            "success": True,
            "system_id": fd.system.id,
            "system_regex": fd.system.formula_regex()
        }))

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))


def testFormulaView(request):
    # Ajax view to test a system formula

    try:

        system_id = request.POST.get("system_id")
        test_string = request.POST.get("test_string")

        system = FormalSystem.objects.get(id=system_id)

        return HttpResponse(json.dumps({
            "success": True,
            "result": system.test_formula(test_string)
        }))

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))



