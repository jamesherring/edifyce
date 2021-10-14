import datetime

from django.shortcuts import render
from django.http import HttpResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import redirect
import json
from .models import *
from django.template.loader import render_to_string


def indexView(request):
    # Index view

    return render(request, "website/index.html", {
        "systems": FormalSystemModel.objects.filter(published__isnull=False),
        "title": "Edifyce"
    })


def profileView(request, profile_id, profile_slug):
    # View of a users profile

    profile = Profile.objects.get(id=profile_id)

    # By default - a user cannot see another user's unpublished proofs
    unpublished_viewable = False
    if request.user.is_authenticated and request.user.profile == profile:
        # A user can view their own proofs
        unpublished_viewable = True

    if request.user.is_superuser:
        # An admin can see everything
        unpublished_viewable = True

    # Get the top level entries for this profile
    entries = FolderEntry.objects.filter(parent_folder__isnull=True, owner=profile)

    if not unpublished_viewable:
        # Remove unpublished entries
        entries = entries.filter(published__isnull=False)

    # Get the formal systems used
    systems = FormalSystemModel.objects.filter(entries__in=entries).distinct()

    # Sort the entries by systems
    if unpublished_viewable:
        system_list = [
            {
                "system": system,
                "entries": entries.filter(formal_system=system, published__isnull=False).order_by("order"),
                "unpublished_entries": entries.filter(formal_system=system, published__isnull=True).order_by("order")
            } for system in systems
        ]

    else:
        system_list = [
            {
                "system": system,
                "entries": entries.filter(formal_system=system).order_by("order"),
                "unpublished_entries": FolderEntry.objects.none()
            } for system in systems
        ]

    return render(request, "website/profile.html", {
        "title": profile.name(),
        "profile": profile,
        "system_list": system_list,
        "editable": request.user.is_authenticated and request.user.profile == profile,
        "unpublished_viewable": unpublished_viewable
    })


@login_required
def settingsView(request):
    # View for user settings (also includes admin buttons for admins)
    return render(request, "website/settings.html", {
        "title": "Settings"
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

    # System must be published or belong to the user
    if system.published is not None or (request.user.is_authenticated and request.user.profile == system.owner):

        entries = FolderEntry.objects.filter(parent_folder__isnull=True, formal_system=system, published__isnull=False).order_by("-published__published")

        user_proofs_published = None
        user_proofs_not_published = None
        if request.user.is_authenticated:
            user_proofs = FolderEntry.objects.filter(parent_folder__isnull=True, owner=request.user.profile, formal_system=system)

            user_proofs_published = user_proofs.filter(published__isnull=False)
            user_proofs_not_published = user_proofs.filter(published__isnull=True)

        # Get the formula pattern definition
        formula = None
        if "formula" in system.formal_system.build_context.variables:
            formula = system.formal_system.build_context.variables["formula"]

            if not isinstance(formula, Pattern):
                # Formula needs to be a pattern
                formula = None

        return render(request, "website/formal_system.html", {
            "system": system,
            "title": system.name,
            "entries": entries,
            "user_proofs_published": user_proofs_published,
            "user_proofs_not_published": user_proofs_not_published,
            "formula": formula
        })

    # Not authenticated
    return redirect("website:index")


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
        system.description = request.POST.get("description")
        system.owner = request.user.profile

        # Save the system with the name to set slug
        system.save()

        # Set the system code
        system.set_code("")

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
        result = system.set_code(new_code)

        if "errors" in result:
            return HttpResponse(json.dumps({
                "success": False,
                "errorMessage": "Please fix the following error(s):<br/>" + "<br/>".join(result["errors"])
            }))

        return HttpResponse(json.dumps({
            "success": True,
            "message": "Saved"
        }))

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))


@login_required
def formalSystemPublishView(request):
    # Ajax view to publish a formal system

    try:

        system_id = request.POST.get("system_id", False)
        system = FormalSystemModel.objects.get(id=system_id)

        if not request.user.profile == system.owner:
            # User is not the owner of this system
            return HttpResponse(json.dumps({
                "success": False,
                "errorMessage": "Authentication error."
            }))

        # The system can't be published already
        assert system.published is None

        # Check there is not already a published system with the same slug
        count = FormalSystemModel.objects.filter(published__isnull=False, slug=system.slug).count()
        if count > 0:
            return HttpResponse(json.dumps({
                "success": False,
                "errorMessage": "A formal system with this slug already exists."
            }))

        # Publish the system
        system.published = datetime.datetime.now()
        system.save()

        return HttpResponse(json.dumps({
            "success": True,
        }))

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))


def formalSystemPattern(request, system_id, system_slug, pattern_id):
    # View the structure of a pattern in a formal system

    system = FormalSystemModel.objects.get(id=system_id)

    if pattern_id not in system.formal_system.pattern_dictionary:
        # Redirect
        return redirect(system.get_absolute_url())

    pattern = system.formal_system.pattern_dictionary[pattern_id]

    return render(request, "website/formal_system_pattern.html", {
        "system": system,
        "pattern": pattern
    })


def folderView(request, folder_id, folder_slug):
    # View for a folder

    folder = ProofFolder.objects.get(id=folder_id)

    if folder.datetime_published() is not None or (request.user.is_authenticated and request.user.profile == folder.owner()):
        return render(request, "website/folder.html", {
            "folder": folder,
            "system": folder.formal_system(),
            "title": folder.name,
            "editable": request.user.is_authenticated and folder.owner() == request.user.profile
        })

    # Not authenticated
    return redirect("website:index")


def folderExpandView(request):
    # Ajax view to expand a folder - returns html table rows

    try:
        entry_id = request.POST.get("entry_id")

        entry = FolderEntry.objects.get(id=entry_id)
        folder = entry.prooffolder

        # Check the entry belongs to the owner or is published
        if (not (request.user.is_authenticated and entry.owner == request.user.profile)) and folder.datetime_published() is None:
            return HttpResponse(json.dumps({
                "success": False,
                "errorMessage": "Authentication error."
            }))

        return HttpResponse(json.dumps({
            "success": True,
            "html": render_to_string("website/folder_list.html", {
                "entries": folder.entries.all()
            })
        }))

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))


@login_required
def folderCreateView(request):
    # Ajax view to create a folder

    try:
        folder = ProofFolder()
        entry = FolderEntry()

        folder.name = request.POST.get("name")
        folder.folder_entry = entry

        entry.owner = request.user.profile

        # Parent folder (if any)
        parent_id = request.POST.get("parent_id", None)

        if parent_id is not None:
            entry.parent_folder = ProofFolder.objects.get(id=parent_id)

        # System
        system_id = request.POST.get("system_id")
        entry.formal_system = FormalSystemModel.objects.get(id=system_id)

        entry.save()
        folder.save()

        return HttpResponse(json.dumps({
            "success": True,
            "folder_url": folder.get_absolute_url()
        }))

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))


@login_required
def folderDeleteView(request, folder_id, folder_slug):
    folder = ProofFolder.objects.get(id=folder_id)

    if (not request.user.profile == folder.owner()) or (folder.datetime_published() is not None):
        # User is not the owner of the proof, or the folder is published
        return redirect(folder.get_absolute_url())

    return render(request, "website/folder_delete.html", {
        "folder": folder
    })


@login_required
def folderDeleteSubmitView(request, folder_id, folder_slug):
    # View to submit deletion of a folder

    folder = ProofFolder.objects.get(id=folder_id)

    if (not request.user.profile == folder.owner()) or (folder.datetime_published() is not None):
        # User is not the owner of the proof, or the folder is published
        return redirect(folder.get_absolute_url())

    # Delete the folder entry, which cascades to delete the folder.
    folder.folder_entry.delete()

    messages.add_message(request, messages.INFO, "Folder deleted.")

    return redirect(request.user.profile)


def proofView(request, proof_id, proof_slug):
    # View for a proof.

    proof = ProofModel.objects.get(id=proof_id)

    # Proof must be published or belong to the user
    if proof.datetime_published() is not None or (request.user.is_authenticated and request.user.profile == proof.owner()):
        return render(request, "website/proof.html", {
            "proof": proof,
            "system": proof.formal_system(),
            "title": proof.formal_system().name + " / " + proof.name,
            "editable": proof.datetime_published() is None and request.user.is_authenticated and
                        request.user.profile == proof.owner()
        })

    # Not authenticated
    return redirect("website:index")


@login_required
def proofCreateView(request, system_id, system_slug, folder_id=None):
    # Form for creating a proof

    system = FormalSystemModel.objects.get(id=system_id)
    folder = ProofFolder.objects.get(id=folder_id) if folder_id is not None else None

    return render(request, "website/proof_create.html", {
        "system": system,
        "folder": folder,
        "title": system.name + " / " + "Create Proof"
    })


@login_required
def proofCreateSubmitView(request):
    # Ajax submission to create a proof

    try:
        proof = ProofModel()
        entry = FolderEntry()

        proof.name = request.POST.get("name")
        proof.description = request.POST.get("description")
        proof.folder_entry = entry

        entry.owner = request.user.profile

        # Get the formal system
        system_id = request.POST.get("system_id")
        entry.formal_system = FormalSystemModel.objects.get(id=system_id)

        # Get the folder (if any)
        folder_id = request.POST.get("folder_id", None)
        if folder_id:
            entry.parent_folder = ProofFolder.objects.get(id=folder_id)

        entry.save()

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

    if (not request.user.profile == proof.owner()) or (proof.datetime_published() is not None):
        # User is not the owner of the proof, or the proof is published
        return redirect(proof.get_absolute_url())

    proof.refresh()

    return render(request, "website/proof_edit.html", {
        "proof": proof,
        "root_autocomplete": proof.autocomplete_suggestions(),
        "system": proof.formal_system(),
        "title": proof.formal_system().name + " / " + proof.name
    })


@login_required
def proofSaveView(request):
    # Ajax view to save a proof

    try:

        proof_id = request.POST.get("proof_id", False)
        proof = ProofModel.objects.get(id=proof_id)

        if (not request.user.profile == proof.owner()) or (proof.datetime_published() is not None):
            # User is not the owner of the proof, or the proof is published
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

        # Get the proof
        proof_id = request.POST.get("proof_id", False)
        proof = ProofModel.objects.get(id=proof_id)
        system = proof.formal_system()

        # Get the proof code
        code = request.POST.get("code", False)

        # Parse the code in the system
        proof = system.parse(proof, code)

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
def proofAutocompleteView(request):
    # Ajax view to get autocomplete suggestions on a given path

    try:

        # Get the proof
        proof_id = request.POST.get("proof_id", False)
        proof = ProofModel.objects.get(id=proof_id)

        # Get the autocomplete path
        path = request.POST.get("path", False)

        # Return the results
        return HttpResponse(json.dumps({
            "success": True,
            "suggestions": proof.autocomplete_suggestions(path=path)
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

    if (not request.user.profile == proof.owner()) or (proof.datetime_published() is not None):
        # User is not the owner of the proof, or the proof is published
        return redirect(proof.get_absolute_url())

    return render(request, "website/proof_delete.html", {
        "proof": proof
    })


@login_required
def proofDeleteSubmitView(request, proof_id, proof_slug):
    # View to submit deletion a proof

    proof = ProofModel.objects.get(id=proof_id)

    if (not request.user.profile == proof.owner()) or (proof.datetime_published() is not None):
        # User is not the owner of the proof, or the proof is published
        return redirect(proof.get_absolute_url())

    # Delete the folder entry, which cascades to delete the proof
    proof.folder_entry.delete()

    messages.add_message(request, messages.INFO, "Proof deleted.")

    return redirect(request.user.profile)


@login_required
def publishView(request):
    # Ajax view to publish an entry

    try:

        entry_id = request.POST.get("entry_id")
        entry = FolderEntry.objects.get(id=entry_id)

        if not request.user.profile == entry.owner:
            # User is not the owner
            return HttpResponse(json.dumps({
                "success": False,
                "errorMessage": "Authentication error."
            }))

        item = entry.item()

        # Check if the item is publishable
        if not item.publishable():
            # This can't be published
            return HttpResponse(json.dumps({
                "success": False,
                "errorMessage": "This item is not ready to be published."
            }))

        # Check there is not already a published entry with the same slug
        proof_count = ProofModel.objects.filter(
            folder_entry__formal_system=entry.formal_system,
            folder_entry__parent_folder__isnull=True,
            folder_entry__published__isnull=False,
            slug=item.slug
        ).count()

        folder_count = ProofFolder.objects.filter(
            folder_entry__formal_system=entry.formal_system,
            folder_entry__parent_folder__isnull=True,
            folder_entry__published__isnull=False,
            slug=item.slug
        ).count()

        if proof_count + folder_count > 0:
            return HttpResponse(json.dumps({
                "success": False,
                "errorMessage": "A published entry with this slug already exists."
            }))

        # Create a new published entry instance
        publication = PublishedEntry()
        publication.folder_entry = entry
        publication.save()

        # Associate the root entry with the publication
        entry.published = publication
        entry.save()

        if item.model_name == "ProofFolder":
            # We need to associate all sub folders and proofs with this publication

            for folder in item.nested_sub_folders():
                folder.folder_entry.published = publication
                folder.folder_entry.save()

            for proof in item.nested_proofs():
                proof.folder_entry.published = publication
                proof.folder_entry.save()

        return HttpResponse(json.dumps({
            "success": True,
            "message": "Published!"
        }))

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))


@login_required
def folderEntryMoveView(request):
    # Ajax request to move a folder entry

    try:
        # The id of the entry to move
        entry_id = request.POST.get("entry_id")
        entry = FolderEntry.objects.get(id=entry_id)

        # The id of the parent entry
        target_parent_id = request.POST.get("target_parent_id")
        if target_parent_id == "root":
            # Move to the root position (no parent)
            target_parent = None
        else:
            target_parent = FolderEntry.objects.get(id=target_parent_id).item()

        # The index (position) to move to.
        index = request.POST.get("index")

        # Check the entry belongs to the owner
        if not entry.owner == request.user.profile:
            return HttpResponse(json.dumps({
                "success": False,
                "errorMessage": "Authentication error."
            }))

        # Check the direction of travel so we know which entries to refresh
        if target_parent is None:

            # Get the root parent folder for entry
            entry_parent = entry
            while entry_parent.parent_folder is not None:
                entry_parent = entry_parent.parent_folder.folder_entry

        if not entry.parent_folder == target_parent:
            # Put the entry at the end of its group
            entry.bottom()

            # Get the max order of the new group
            max_order = FolderEntry.objects.filter(parent_folder=target_parent, formal_system=entry.formal_system, owner=entry.owner).get_max_order()

            # Update the parent
            entry.parent_folder = target_parent

            # Put at the end of the new group by default
            entry.order = max_order + 1 if max_order is not None else 0

            entry.save()

        if index == "last":
            # Move to the bottom
            entry.bottom()

        else:
            # Set the new index
            entry.to(int(index))

        # Keep a set of proofs whose validity has changed as a result of the move
        validity_changed = set()

        # Refresh the dependant proofs
        item = entry.item()
        if item.model_name == "ProofModel":
            # This is one proof being moved
            for p in item.dependants.all():
                p.refresh(refresh_system=False, validity_changed=validity_changed)

            item.refresh(refresh_system=False, validity_changed=validity_changed)

        else:
            # It's a folder. Get a queryset of all proofs and dependants
            proofs = item.nested_proofs()

            dependants = ProofModel.objects.none()
            for p in proofs:
                dependants = dependants | p.dependants.all()

            # Add the proofs
            proofs_and_dependants = (proofs | dependants).distinct()

            for p in proofs_and_dependants:
                p.refresh(refresh_system=False, validity_changed=validity_changed)

        # Return a list of the corresponding entry ids for those proofs whose validity has changed - and their new
        # indicator
        validity_data = [{
            "entry_id": p.folder_entry.id,
            "indicator": p.proof.indicator()
        } for p in validity_changed]

        return HttpResponse(json.dumps({
            "success": True,
            "validity_data": validity_data
        }))

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))


@login_required
def updateTextView(request, table, field):
    # Ajax view to update a text field

    try:
        assert table in ("proof", "folder")

        target_id = request.POST.get("target_id")
        value = request.POST.get("value")

        profile = request.user.profile

        if table == "proof":
            # Update the proof
            proof = ProofModel.objects.get(id=target_id)

            assert field in ("name", "description")

            # Check the proof belongs to the user
            if not proof.owner() == profile:
                return HttpResponse(json.dumps({
                    "success": False,
                    "errorMessage": "Authentication error."
                }))

            # Set the value
            setattr(proof, field, value)

            proof.save()

        elif table == "folder":
            # Update the proof folder

            folder = ProofFolder.objects.get(id=target_id)

            assert field in ("name",)

            # Check the folder belongs to the user
            if not folder.owner() == profile:
                return HttpResponse(json.dumps({
                    "success": False,
                    "errorMessage": "Authentication error."
                }))

            setattr(folder, field, value)

            folder.save()

        return HttpResponse(json.dumps({"success": True}))

    except Exception as e:
        return HttpResponse(json.dumps({
            "success": False,
            "errorMessage": str(e)
        }))
