# coding=utf-8

from django.urls import path, include
from .views import *

app_name = "website"
urlpatterns = [

    # Index
    path("", indexView, name="index"),

    # Profile
    path("profile/<profile_slug>/", viewProfileView, name="profile_view"),

    # Admin views
    path("superadmin/", adminView, name="admin"),
    path("ajax/admin/refresh-proofs/", refreshProofsView, name="refresh_proofs"),

    # Formal systems
    path("system/view/<system_id>/<system_slug>/", formalSystemView, name="formal_system"),
    path("system/create/", formalSystemCreateView, name="formal_system_create"),
    path("system/edit/<system_id>/<system_slug>/", formalSystemEditView, name="formal_system_edit"),
    path("system/view_source/<system_id>/<system_slug>/", formalSystemCodeView, name="formal_system_code"),

    path("system/ajax/create/", formalSystemCreateSubmitView, name="formal_system_create_submit"),
    path("system/ajax/save/", formalSystemSaveView, name="formal_system_save"),

    # Folders
    path("folder/view/<folder_id>/<folder_slug>/", folderView, name="folder"),
    path("folder/ajax/create/", folderCreateView, name="folder_create"),
    path("folder/delete/<folder_id>/<folder_slug>/", folderDeleteView, name="folder_delete"),
    path("folder/delete_submit/<folder_id>/<folder_slug>/", folderDeleteSubmitView, name="folder_delete_submit"),

    path("folder/ajax/expand/", folderExpandView, name="folder_expand"),

    # Proofs
    path("proof/view/<proof_id>/<proof_slug>/", proofView, name="proof"),
    path("proof/create/<system_id>/<system_slug>/<folder_id>/", proofCreateView, name="proof_create_in_folder"),
    path("proof/create/<system_id>/<system_slug>/", proofCreateView, name="proof_create"),
    path("proof/edit/<proof_id>/<proof_slug>/", proofEditView, name="proof_edit"),
    path("proof/delete/<proof_id>/<proof_slug>/", proofDeleteView, name="proof_delete"),
    path("proof/delete_submit/<proof_id>/<proof_slug>/", proofDeleteSubmitView, name="proof_delete_submit"),

    path("proof/ajax/create/", proofCreateSubmitView, name="proof_create_submit"),
    path("proof/ajax/save/", proofSaveView, name="proof_save"),
    path("proof/ajax/validate/", proofValidateView, name="proof_validate"),
    path("proof/ajax/autocomplete/", proofAutocompleteView, name="proof_autocomplete"),
    path("proof/ajax/publish/", proofPublishView, name="proof_publish"),

    # Folder entries
    path("folderentry/ajax/move/", folderEntryMoveView, name="folderentry_move"),

    # Update text
    path("ajax/update-text/<table>/<field>/", updateTextView, name="update_text")


]
