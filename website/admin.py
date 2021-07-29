from django.contrib import admin
from ordered_model.admin import OrderedModelAdmin
from .models import *

# Register your models here.


# class FolderAdmin(OrderedModelAdmin):
#     list_display = ('name', 'owner', 'formal_system', 'move_up_down_links')


# class ProofAdmin(OrderedModelAdmin):
#     list_display = ('name', 'folder', 'owner', 'formal_system', 'order', 'move_up_down_links')


admin.site.register(FormalSystemModel)

admin.site.register(FolderEntry)

admin.site.register(ProofFolder)
admin.site.register(ProofModel)

admin.site.register(Profile)
