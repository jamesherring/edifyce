from django.shortcuts import render
from django.http import HttpResponse
import json
from .models import *


def indexView(request):
    # Index view

    # formal_systems = FormalSystemModel.objects.all()

    return render(request, "website/index.html", {
        "formal_systems": FormalSystemModel.objects.all()
    })


def formalSystemView(request, system_id, system_slug):
    # View for a formal system

    system = FormalSystemModel.objects.get(id=system_id)

    return render(request, "website/formal_system.html", {
        "system": system
    })


def formalSystemCreateView(request):
    # Form for creating a formal system
    return render(request, "website/formal_system_create.html")


def formalSystemCreateSubmitView(request):
    # Ajax submission to create a formal system

    try:
        system = FormalSystemModel()

        system.name = request.POST.get("name")

        # Get the code
        code = request.POST.get("code", False)

        # Set the system code
        system.set_code(code)

        # Respond
        return HttpResponse(json.dumps({
            "success": True,
            "url": system.get_absolute_url()
        }))

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))


def formalSystemEditView(request, system_id, system_slug):
    # Edit view for a formal system

    system = FormalSystemModel.objects.get(id=system_id)

    return render(request, "website/formal_system_edit.html", {
        "system": system
    })


def formalSystemSaveView(request):
    # Ajax view to save a formal system code

    # try:

    system_id = request.POST.get("system_id", False)
    system = FormalSystemModel.objects.get(id=system_id)

    # Get the new code
    new_code = request.POST.get("code", False)

    # Set the system code
    system.set_code(new_code)

    return HttpResponse(json.dumps({"success": True}))

    # except Exception as e:
    #     return HttpResponse(json.dumps({
    #         "success": False,
    #         "errorMessage": str(e)
    #     }))


def proofView(request, proof_id, proof_slug):
    # View for a proof

    proof = ProofModel.objects.get(id=proof_id)
    proof.refresh()

    return render(request, "website/proof.html", {
        "proof": proof,
        "system": proof.formal_system
    })


def proofCreateView(request, system_id, system_slug):
    # Form for creating a proof

    system = FormalSystemModel.objects.get(id=system_id)

    return render(request, "website/proof_create.html", {
        "system": system
    })


def proofCreateSubmitView(request):
    # Ajax submission to create a proof

    try:
        proof = ProofModel()

        proof.name = request.POST.get("name")

        # Get the formal system
        system_id = request.POST.get("system_id")
        system = FormalSystemModel.objects.get(id=system_id)

        proof.formal_system = system

        # Get the code
        code = request.POST.get("code", False)

        # Set the proof code
        proof.set_code(code)

        # Respond
        return HttpResponse(json.dumps({
            "success": True,
            "url": proof.get_absolute_url()
        }))

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))


def proofEditView(request, proof_id, proof_slug):
    # Edit view for a proof

    proof = ProofModel.objects.get(id=proof_id)
    proof.refresh()

    return render(request, "website/proof_edit.html", {
        "proof": proof,
        "system": proof.formal_system
    })


def proofSaveView(request):
    # Ajax view to save a proof

    # try:

    proof_id = request.POST.get("proof_id", False)
    proof = ProofModel.objects.get(id=proof_id)

    # Get the new code
    new_code = request.POST.get("code", False)

    # Set the proof code
    proof.set_code(new_code)

    return HttpResponse(json.dumps({
        "success": True,
        "validation": proof.proof.validation_data()
    }))

    # except Exception as e:
    #     return HttpResponse(json.dumps({
    #         "success": False,
    #         "errorMessage": str(e)
    #     }))


def proofValidateView(request):
    # Ajax view to validate a proof

    # try:

    # Get the proof system
    system_id = request.POST.get("system_id", False)
    system = FormalSystemModel.objects.get(id=system_id)

    # Get the proof code
    code = request.POST.get("code", False)

    # Parse the code in the system to get a proof
    proof = system.parse(code)

    # Return the results
    return HttpResponse(json.dumps({
        "success": True,
        "validation": proof.validation_data()
    }))

    # except Exception as e:
    #     return HttpResponse(json.dumps({
    #         "success": False,
    #         "errorMessage": str(e)
    #     }))


# def proofEditorView(request, system_slug):
#     # View for editing a proof
#
#     system = FormalSystem.objects.get(slug=system_slug)
#
#     return render(request, "website/proof_editor.html", {
#         "system": system
#     })
#
#
# def updateFormulaDefinition(request):
#     # Ajax view to update a formula definition
#
#     try:
#         fd_id = request.POST.get("formula_definition_id", False)
#         fd = FormulaDefinition.objects.get(id=fd_id)
#
#         pattern = request.POST.get("pattern", False)
#         if pattern:
#             fd.pattern = pattern
#             fd.save()
#
#         return HttpResponse(json.dumps({
#             "success": True,
#             "system_id": fd.system.id,
#             "system_regex": fd.system.formula_regex()
#         }))
#
#     except Exception as e:
#         return HttpResponse(json.dumps({
#             "success": False,
#             "errorMessage": str(e)
#         }))
#
#
# def testFormulaView(request):
#     # Ajax view to test a system formula
#
#     try:
#
#         system_id = request.POST.get("system_id")
#         test_string = request.POST.get("test_string")
#
#         system = FormalSystem.objects.get(id=system_id)
#
#         return HttpResponse(json.dumps({
#             "success": True,
#             "result": system.test_formula(test_string)
#         }))
#
#     except Exception as e:
#         return HttpResponse(json.dumps({
#             "success": False,
#             "errorMessage": str(e)
#         }))
#
#
#
