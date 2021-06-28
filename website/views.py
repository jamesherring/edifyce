from django.shortcuts import render
from django.http import HttpResponse
from django.views.decorators.csrf import requires_csrf_token
import json
from .models import *


def indexView(request):
    # Index view

    return render(request, "website/index.html", {
        "formal_systems": FormalSystemModel.objects.all(),
        "title": "Edifyce"
    })


def formalSystemView(request, system_id, system_slug):
    # View for a formal system

    system = FormalSystemModel.objects.get(id=system_id)

    return render(request, "website/formal_system.html", {
        "system": system,
        "title": system.name
    })


def formalSystemCreateView(request):
    # Form for creating a formal system
    return render(request, "website/formal_system_create.html", {
        "title": "Create Formal System"
    })


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
        "system": system,
        "title": system.name
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
        "system": proof.formal_system,
        "title": proof.formal_system.name + " / " + proof.name
    })


def proofCreateView(request, system_id, system_slug):
    # Form for creating a proof

    system = FormalSystemModel.objects.get(id=system_id)

    return render(request, "website/proof_create.html", {
        "system": system,
        "title": system.name + " / " + "Create Proof"
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
        "system": proof.formal_system,
        "title": proof.formal_system.name + " / " + proof.name
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
        "data": proof.proof.data()
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
        "data": proof.data()
    }))

    # except Exception as e:
    #     return HttpResponse(json.dumps({
    #         "success": False,
    #         "errorMessage": str(e)
    #     }))


# def axiomsEditView(request, system_id, system_slug):
#     # Edit the axioms of the given system
#
#     system = FormalSystemModel.objects.get(id=system_id)
#
#     return render(request, "website/axioms_edit.html", {
#         "system": system
#     })
