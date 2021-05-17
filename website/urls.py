# coding=utf-8

from django.urls import path, include
from .views import *

app_name = "website"
urlpatterns = [

    # Index
    path("", indexView, name="index"),

    # Formal systems
    path("system/view/<system_id>/<system_slug>/", formalSystemView, name="formal_system"),
    path("system/create/", formalSystemCreateView, name="formal_system_create"),
    path("system/edit/<system_id>/<system_slug>/", formalSystemEditView, name="formal_system_edit"),

    path("system/ajax/create/", formalSystemCreateSubmitView, name="formal_system_create_submit"),
    path("system/ajax/save/", formalSystemSaveView, name="formal_system_save"),

    # Proofs
    path("proof/view/<proof_id>/<proof_slug>/", proofView, name="proof"),
    path("proof/create/<system_id>/<system_slug>", proofCreateView, name="proof_create"),
    path("proof/edit/<proof_id>/<proof_slug>/", proofEditView, name="proof_edit"),

    path("proof/ajax/create/", proofCreateSubmitView, name="proof_create_submit"),
    path("proof/ajax/save/", proofSaveView, name="proof_save"),
    path("proof/ajax/validate/", proofValidateView, name="proof_validate"),

    # Axioms
    # path("axioms/edit/<system_id>/<system_slug>/", axiomsEditView, name="axioms_edit")

]
