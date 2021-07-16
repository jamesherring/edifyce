from django.shortcuts import render
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import redirect
import json
from .models import *
import os


def indexView(request):
    # Index view

    return render(request, "website/index.html", {
        "formal_systems": FormalSystemModel.objects.all(),
        "title": "Edifyce"
    })


def viewProfileView(request, profile_slug):
    # View of a users profile

    profile = Profile.objects.get(slug=profile_slug)

    return render(request, "website/profile.html", {
        "title": profile.name(),
        "profile": profile,
        "proofs": ProofModel.objects.filter(owner=profile)[:20]
    })


@login_required
def adminView(request):
    # Admin view with powerful buttons

    if not request.user.is_superuser:
        # User not an admin
        return redirect("website:index")

    return render(request, "website/admin.html", {
        "title": "Admin"
    })


@login_required
def refreshProofsView(request):
    # Admin refresh all proofs

    try:
        if not request.user.is_superuser:
            return HttpResponse(json.dumps({
                "success": False,
                "errorMessage": "Authentication error."
            }))

        proofs = ProofModel.objects.all()

        for proof in proofs:
            proof.refresh(refresh_system=False)

        return HttpResponse(json.dumps({
            "success": True,
            "message": str(len(proofs)) + " proofs refreshed."
        }))

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))


def formalSystemView(request, system_id, system_slug):
    # View for a formal system

    system = FormalSystemModel.objects.get(id=system_id)

    return render(request, "website/formal_system.html", {
        "system": system,
        "title": system.name,
        "proofs": system.proofmodel_set.filter(published__isnull=False)
    })


@login_required
def formalSystemCreateView(request):
    # Form for creating a formal system
    return render(request, "website/formal_system_create.html", {
        "title": "Create Formal System"
    })


@login_required
def formalSystemCreateSubmitView(request):
    # Ajax submission to create a formal system

    try:
        system = FormalSystemModel()

        system.name = request.POST.get("name")
        system.owner = request.user.profile

        # Save the system with the name to set slug
        system.save()

        # Create the folder
        folder_path = system.path_to_file()
        folder_path = folder_path[:folder_path.rfind("/")]
        os.mkdir(folder_path)

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


@login_required
def formalSystemEditView(request, system_id, system_slug):
    # Edit view for a formal system

    system = FormalSystemModel.objects.get(id=system_id)

    if not request.user.profile == system.owner:
        # Redirect
        return redirect(system.get_absolute_url())

    return render(request, "website/formal_system_edit.html", {
        "system": system,
        "title": system.name,
        "editable": True
    })


def formalSystemCodeView(request, system_id, system_slug):
    # View to view (but not edit) the code for a formal system.

    system = FormalSystemModel.objects.get(id=system_id)

    return render(request, "website/formal_system_edit.html", {
        "system": system,
        "title": system.name,
        "editable": False
    })


@login_required
def formalSystemSaveView(request):
    # Ajax view to save a formal system code

    try:

        system_id = request.POST.get("system_id", False)
        system = FormalSystemModel.objects.get(id=system_id)

        if not request.user.profile == system.owner:
            # User is not the owner of this system
            return HttpResponse(json.dumps({
                "success": False,
                "errorMessage": "Authentication error."
            }))

        # Get the new code
        new_code = request.POST.get("code", False)

        # Set the system code
        system.set_code(new_code)

        return HttpResponse(json.dumps({
            "success": True,
            "message": "Saved"
        }))

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))


def proofView(request, proof_id, proof_slug):
    # View for a proof.

    proof = ProofModel.objects.get(id=proof_id)

    # Proof must be published or belong to the user
    if proof.published is not None or (request.user.is_authenticated and request.user.profile == proof.owner):
        return render(request, "website/proof.html", {
            "proof": proof,
            "system": proof.formal_system,
            "title": proof.formal_system.name + " / " + proof.name,
            "editable": proof.published is None and request.user.is_authenticated and
                        request.user.profile == proof.owner
        })

    # Nor authenticated
    return redirect("website:index")


@login_required
def proofCreateView(request, system_id, system_slug):
    # Form for creating a proof

    system = FormalSystemModel.objects.get(id=system_id)

    return render(request, "website/proof_create.html", {
        "system": system,
        "title": system.name + " / " + "Create Proof"
    })


@login_required
def proofCreateSubmitView(request):
    # Ajax submission to create a proof

    try:
        proof = ProofModel()

        proof.name = request.POST.get("name")
        proof.description = request.POST.get("description")
        proof.owner = request.user.profile

        # Get the formal system
        system_id = request.POST.get("system_id")
        system = FormalSystemModel.objects.get(id=system_id)

        proof.formal_system = system

        # Set code to empty - includes save
        proof.set_code("")

        # Respond
        return HttpResponse(json.dumps({
            "success": True,
            "url": proof.get_absolute_edit_url()
        }))

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))


@login_required
def proofEditView(request, proof_id, proof_slug):
    # Edit view for a proof

    proof = ProofModel.objects.get(id=proof_id)

    if not request.user.profile == proof.owner:
        # Redirect
        return redirect(proof.get_absolute_url())

    proof.refresh()

    return render(request, "website/proof_edit.html", {
        "proof": proof,
        "system": proof.formal_system,
        "title": proof.formal_system.name + " / " + proof.name
    })


@login_required
def proofSaveView(request):
    # Ajax view to save a proof

    try:

        proof_id = request.POST.get("proof_id", False)
        proof = ProofModel.objects.get(id=proof_id)

        if not request.user.profile == proof.owner:
            # User is not the owner of the proof
            return HttpResponse(json.dumps({
                "success": False,
                "errorMessage": "Authentication error."
            }))

        # Get the new code
        new_code = request.POST.get("code", False)

        # Set the proof code
        proof.set_code(new_code)

        return HttpResponse(json.dumps({
            "success": True,
            "message": "Saved",
            "data": proof.proof.data()
        }))

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))


@login_required
def proofValidateView(request):
    # Ajax view to validate a proof

    try:

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

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))


@login_required
def proofPublishView(request):
    # Ajax view to publish a proof

    try:

        proof_id = request.POST.get("proof_id", False)
        proof = ProofModel.objects.get(id=proof_id)

        if not request.user.profile == proof.owner:
            # User is not the owner of the proof
            return HttpResponse(json.dumps({
                "success": False,
                "errorMessage": "Authentication error."
            }))

        if not proof.proof.valid:
            return HttpResponse(json.dumps({
                "success": False,
                "errorMessage": "Cannot publish an invalid proof."
            }))

        proof.published = datetime.datetime.now()

        return HttpResponse(json.dumps({
            "success": True,
            "message": "Proof published!"
        }))

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))


@login_required
def proofDeleteView(request, proof_id, proof_slug):
    # View to submit deletion a proof

    proof = ProofModel.objects.get(id=proof_id)

    if not request.user.profile == proof.owner:
        # User is not the owner of the proof
        return redirect(proof.get_absolute_url())

    return render(request, "website/proof_delete.html", {
        "proof": proof
    })


@login_required
def proofDeleteSubmitView(request, proof_id, proof_slug):
    # View to submit deletion a proof

    proof = ProofModel.objects.get(id=proof_id)

    if not request.user.profile == proof.owner:
        # User is not the owner of the proof
        return redirect(proof.get_absolute_url())

    proof.delete()

    messages.add_message(request, messages.INFO, "Proof deleted.")

    return redirect(request.user.profile)




@login_required
def updateTextView(request, table, field):
    # Ajax view to update a text field

    try:
        assert table in ("proof",)

        target_id = request.POST.get("target_id")
        value = request.POST.get("value")

        profile = request.user.profile

        if table == "proof":
            # Update the proof
            proof = ProofModel.objects.get(id=target_id)

            assert field in ("description",)

            # Set the value
            setattr(proof, field, value)

            proof.save()

        return HttpResponse(json.dumps({"success": True}))

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))
