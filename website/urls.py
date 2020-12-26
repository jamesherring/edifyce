# coding=utf-8

from django.urls import path, include
from .views import *

app_name = "website"
urlpatterns = [

    # Index
    path("", indexView, name="index"),

    path("system/<system_slug>/", formalSystemView, name="formal_system"),
    path("edit_system/<system_slug>/", formalSystemEditView, name="formal_system_edit"),
    path("ajax/save_system/", formalSystemSaveView, name="formal_system_save"),

    # path("formal_system/<system_slug>/proof_editor/", proofEditorView, name="proof_editor"),

    # path("formula_definition/update/", updateFormulaDefinition, name="update_formula_definition"),
    # path("formal_system/test_formula/", testFormulaView, name="test_formula")

]
