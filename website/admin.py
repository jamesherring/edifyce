from django.contrib import admin
from ordered_model.admin import OrderedModelAdmin
from .models import *

# Register your models here.


class FolderEntryAdmin(OrderedModelAdmin):
    list_display = ('order', 'parent_folder', 'owner', 'formal_system', 'move_up_down_links')


admin.site.register(FormalSystemModel)

admin.site.register(FolderEntry, FolderEntryAdmin)

admin.site.register(ProofFolder)
admin.site.register(ProofModel)

admin.site.register(PublishedEntry)

admin.site.register(Profile)
