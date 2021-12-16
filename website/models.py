from django.db import models
from django.contrib import messages
from ordered_model.models import OrderedModel
from django.contrib.auth.models import User
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from picklefield.fields import PickledObjectField
import random
from slugify import slugify
from website.logical.compiler import get_inherited_system, compile
from website.logical.matching import Pattern


def id_gen(length=8, chars="0123456789abcdef"):
    # An id generator to uniquely identify objects
    return "".join(random.SystemRandom().choice(chars) for _ in range(length))


def import_slug(s):
    # Return the import slug for a string s
    return slugify(s).replace("-", "_")


class Profile(models.Model):

    # One-to-one relationship to the user model
    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    # Unique slug
    slug = models.CharField(max_length=64, blank=True, null=True)

    first_name = models.CharField(max_length=64, blank=True, null=True)
    last_name = models.CharField(max_length=64, blank=True, null=True)

    email = models.EmailField(blank=True, null=True)

    created = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated = models.DateTimeField(auto_now=True, blank=True, null=True)

    def get_absolute_url(self):
        # Return the absolute url for the profile
        return "/profile/" + self.slug + "/"

    def name(self):
        # Get the full name
        return self.first_name + " " + self.last_name

    def __str__(self):
        return str(self.user)


# Save a profile model whenever a user is created
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:

        # Create the profile
        Profile.objects.create(
            user=instance,
            first_name=instance.first_name,
            last_name=instance.last_name,
            email=instance.email
        )

        # Set the User username to the email
        instance.username = instance.email
        instance.save()


# Update the profile model whenever a user is updated
@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    profile, created = Profile.objects.get_or_create(user=instance)

    profile.first_name = instance.first_name
    profile.last_name = instance.last_name
    profile.email = instance.email

    profile.save()


class FormalSystemModel(models.Model):
    # Model for Formal Systems

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    name = models.CharField(max_length=256)
    slug = models.CharField(max_length=256)

    # Field pointing to an instance of a FormalSystem class
    formal_system = PickledObjectField(default=None, blank=True, null=True, editable=True)

    # The system source text
    formal_system_text = models.TextField(default="")

    # Formal system this inherits from
    inherits_from = models.ForeignKey("self", on_delete=models.SET_NULL, default=None, blank=True, null=True,
                                      related_name="inherited_by")

    # Owner of this formal system
    owner = models.ForeignKey(Profile, on_delete=models.SET_NULL, blank=True, null=True)

    # Date the system is published
    published = models.DateTimeField(blank=True, null=True)

    # Optional description of the formal system
    description = models.TextField(blank=True, null=True)

    created = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated = models.DateTimeField(auto_now=True, blank=True, null=True)

    def get_absolute_url(self):
        return "/system/view/" + self.id + "/" + self.slug + "/"

    def path_to_file(self):
        # Get the path to the file defining this formal system
        return "website/formal_systems/" + self.id + "/" + self.slug + ".txt"

    def inherited_systems(self):
        # Return a set of slugs of the chain of systems
        if self.inherits_from is None:
            return set()

        return {self.inherits_from}.union(self.inherits_from.inherited_systems())

    def code(self):
        # Get the code for this formal system
        return self.formal_system_text

    def set_code(self, code):
        # Set the system code
        self.formal_system_text = code

        # Get the inherited system slug
        slug = get_inherited_system(code)
        system_dict = dict()

        if slug is not None:
            inherits_from = None
            try:
                inherits_from = FormalSystemModel.objects.get(slug=slug)

            except:
                pass

            if inherits_from is not None:
                if self in inherits_from.inherited_systems():
                    # Circular reference
                    raise Exception("Circular reference in formal system inheritence.")

                self.inherits_from = inherits_from
                system_dict[slug] = self.inherits_from.formal_system

        # Refresh the formal system instance according to the file
        result = compile(code, system_dict=system_dict)

        if "errors" in result:
            # There are errors
            return result

        # Otherwise ok
        self.formal_system = result["system"]
        self.save()

        # Refresh all proofs in the system (no need to cascade)
        proofs = ProofModel.objects.filter(folder_entry__formal_system=self)
        for proof in proofs:
            proof.refresh(refresh_system=False, cascade=None)

        return result

    def refresh(self):
        # Refresh the instance
        self.set_code(self.code())

    def parse(self, proof_model, code):
        # Parse proof code into a proof instance.

        # Find any references to other proofs
        reference_paths = self.formal_system.get_references(code)

        # Build a dictionary of references to other proofs
        reference_dict = dict()
        for path in reference_paths:
            proof_model.parse_import(path, reference_dict)

        # Check the imports are valid
        proof_folder_entry = proof_model.folder_entry
        for key, target in reference_dict.items():

            reference_dict[key] = {
                "target": target
            }

            if target is None:
                reference_dict[key]["errorMessage"] = "Cannot find reference."
                continue

            if isinstance(target, FormalSystemModel):
                # Target is a formal system
                if target not in self.inherited_systems():
                    reference_dict[key]["errorMessage"] = "Cannot reference from a formal system not inherited by " + self.name + "."
                continue

            if proof_folder_entry.comes_before(target.folder_entry):
                # We are referencing a proof that doesn't come first.
                reference_dict[key]["errorMessage"] = "Cannot reference a later proof."
                continue

            if proof_folder_entry == target.folder_entry:
                # Trying to self-reference
                reference_dict[key]["errorMessage"] = "A proof cannot reference itself."
                continue

            if isinstance(target, ProofModel):
                # Use the pickled proof object rather than the django class.
                reference_dict[key]["target"] = target.proof

        # Get the previous proof instance
        previous_proof = proof_model.unsaved_proof if proof_model.unsaved_proof is not None else proof_model.proof

        # Create a proof instance
        proof = self.formal_system.parse(
            code,
            proof_model_id=proof_model.id,
            reference_proofs=reference_dict,
            previous_proof=previous_proof
        )

        return proof

    def proof_count(self):
        return ProofModel.objects.filter(folder_entry__formal_system=self).count()

    def __str__(self):
        return self.name


class FolderEntry(OrderedModel):
    # A folder entry (either a proof or a folder)

    class Meta:
        verbose_name_plural = "Folder entries"

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    parent_folder = models.ForeignKey("ProofFolder", on_delete=models.CASCADE, blank=True, null=True, related_name="entries")

    # Owner of this item
    owner = models.ForeignKey(Profile, on_delete=models.SET_NULL, blank=True, null=True)

    # The formal system this entry belongs to
    formal_system = models.ForeignKey(FormalSystemModel, on_delete=models.CASCADE, related_name="entries")

    # The published entry (if this item is published)
    published = models.ForeignKey("PublishedEntry", on_delete=models.SET_NULL, blank=True, null=True)

    # Order with respect to parent folder - and owner and system and published in case of root level items
    order_with_respect_to = ('parent_folder', 'owner', 'formal_system', 'published')

    def item(self):
        # Return the sub-item (proof folder or proof model) this entry corresponds to

        proofs = ProofModel.objects.filter(folder_entry=self)
        if len(proofs) > 0:
            return proofs[0]

        folders = ProofFolder.objects.filter(folder_entry=self)
        if len(folders) > 0:
            return folders[0]

        raise Exception("Couldn't find a proof or folder corresponding to the folder entry.")

    def parent_folders(self):
        # Get the set of parent folders
        if self.parent_folder is None:
            return []

        return self.parent_folder.folder_entry.parent_folders() + [self.parent_folder]

    def autocomplete_option(self):
        # Return a dictionary option for autocomplete for this entry

        item = self.item()
        slug = import_slug(item.slug)
        return {
            "value": slug,
            "caption": slug,
            "meta": "Folder" if isinstance(item, ProofFolder) else "Proof"
        }

    def datetime_published(self):
        return None if self.published is None else self.published.published

    def comes_before(self, other):
        # Check if this folder entry comes before the other one (for avoiding circular references).

        if self == other:
            # It doesn't come before itself
            return False

        if not self.formal_system == other.formal_system:
            # Formal systems not the same. This one should be in the other's inherited systems.
            return self.formal_system in other.formal_system.inherited_systems()

        # Otherwise formal systems are the same.

        self_item = self.item()
        other_item = other.item()

        self_published = self.datetime_published()
        other_published = other.datetime_published()

        if self_published is not None and other_published is not None:
            # Both are published, just need to verify is self was published first
            return self_published < other_published

        if self_published is not None and other_published is None:
            # self is published, and other is not yet published - so must be ok
            return True

        if self_published is None and other_published is not None:
            # self is not published but other is - so can't come afterwards
            return False

        # Both are not published. They need to have the same author.
        if not self.owner == other.owner:
            return False

        # Check if the parent_folder is the same
        if self.parent_folder == other.parent_folder:
            # Just need to compare order.
            return self.order < other.order

        # Find the common ancestor and compare order
        self_ancestors = self.parent_folders()
        other_ancestors = other.parent_folders()

        if self_item in other_ancestors:
            # self is a folder in the ancestor list of other. We say this comes before other, so ok.
            return True

        if other_item in self_ancestors:
            # other is a folder in the ancestor list of self. So other comes first.
            return False

        # Otherwise these are on branches that separate somewhere.
        i = 0
        max_depth = max(len(self_ancestors), len(other_ancestors))
        while i < max_depth:
            self_parent = self_ancestors[i]
            other_parent = other_ancestors[i]

            if self_parent == other_parent:
                continue

            # Otherwise, we found a difference
            return self_parent.folder_entry.order < other_parent.folder_entry.order

    def validate(self):
        # Check this entry (and any sub-entries) are valid proofs

        item = self.item()

        if item.model_name == "ProofModel":
            # Refresh the proof
            item.refresh(refresh_system=False)
            return item.proof.valid

        # Otherwise it's a folder

        # Get the sub-entries in order
        sub_entries = FolderEntry.objects.filter(parent_folder=item).order_by("order")
        result = True
        for entry in sub_entries:
            result = result and entry.validate()

        return result

    def __str__(self):
        item = self.item()
        return item.model_name + ": " + str(item)


class PublishedEntry(models.Model):
    # A published entry

    class Meta:
        verbose_name_plural = "Published entries"

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    # The date published
    published = models.DateTimeField(auto_now_add=True, blank=True, null=True)

    # The corresponding root entry
    folder_entry = models.OneToOneField(FolderEntry, on_delete=models.CASCADE)

    def formal_system(self):
        return self.folder_entry.formal_system

    def owner(self):
        return self.folder_entry.owner

    def __str__(self):
        return str(self.folder_entry)


class ProofFolder(models.Model):
    # A model for folders containing folders and proofs

    model_name = "ProofFolder"

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    # The folder entry
    folder_entry = models.OneToOneField(FolderEntry, on_delete=models.CASCADE)

    name = models.CharField(max_length=256)
    slug = models.CharField(max_length=256)

    created = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated = models.DateTimeField(auto_now=True, blank=True, null=True)

    def get_absolute_url(self):
        return "/folder/view/" + self.id + "/" + self.slug + "/"

    def items(self):
        # Return an ordered queryset of entries in the folder
        return FolderEntry.objects.filter(parent_folder=self).order_by("order")

    def parent_folder(self):
        return self.folder_entry.parent_folder

    def formal_system(self):
        return self.folder_entry.formal_system

    def owner(self):
        return self.folder_entry.owner

    def datetime_published(self):
        return self.folder_entry.datetime_published()

    def is_root(self):
        return self.parent_folder() is None

    def sub_folders(self):
        # Get sub folders in this folder
        return ProofFolder.objects.filter(folder_entry__parent_folder=self)

    def nested_sub_folders(self):
        # Get all nested folders in layers

        folders = self.sub_folders()
        last_layer = folders

        while len(last_layer) > 0:
            # Get the next layer of folders
            new_folders = ProofFolder.objects.filter(folder_entry__parent_folder__in=last_layer)

            # Add to the queryset
            folders = folders | new_folders

            # Go to the next layer
            last_layer = new_folders

        return folders

    def proofs(self):
        # Get proofs belonging directly to this folder
        return ProofModel.objects.filter(folder_entry__parent_folder=self)

    def nested_proofs(self):
        # Get proofs belonging to this folder including those nested in sub-folders
        return self.proofs() | ProofModel.objects.filter(folder_entry__parent_folder__in=self.nested_sub_folders())

    def publishable(self):
        # Check if the folder is publishable

        # The folder has to not already be published
        if self.folder_entry.published is not None:
            return False

        # It has to be root level
        if not self.is_root():
            return False

        # The formal system has to be published
        if self.formal_system().published is None:
            return False

        # All the proofs inside have to be valid
        nested_proofs = self.nested_proofs()
        for proof in nested_proofs:
            if not proof.proof.valid:
                return False

        # All the references outside of the folder must be published
        references = ProofModel.objects.none()
        for proof in nested_proofs:
            references = references | proof.references.all()

        references = references.distinct()

        for proof in references:
            if (not self.contains(proof.folder_entry)) and (proof.datetime_published() is None):
                # External reference is not published
                return False

        # Otherwise ok
        return True

    def contains(self, entry):
        # Check if the folder contains this folder entry
        return self in entry.parent_folders()

    def get_reference(self, ref, context):
        # Get a reference. Optionally specify the proof model making the reference, to exclude any entries after it.

        initial = ref
        remainder = None

        importing_proof_entry = None
        if context.proof_model_id is not None:
            importing_proof_entry = ProofModel.objects.get(id=context.proof_model_id).folder_entry

        if "." in ref:
            index = ref.find(".")
            initial = ref[:index]
            remainder = ref[index + 1:]

        # Try folder
        folder = self.sub_folders().filter(slug=initial).first()
        if folder is not None:

            # Check the importing proof comes later
            if importing_proof_entry is not None and not folder.folder_entry.comes_before(importing_proof_entry):
                raise Exception("Cannot import a later folder.")

            if remainder is None:
                return folder

            return folder.get_reference(remainder, context)

        # Try proof
        proof = self.proofs().filter(slug=initial).first()
        if proof is not None:

            # Check the importing proof comes later
            if importing_proof_entry is not None and not proof.folder_entry.comes_before(importing_proof_entry):
                raise Exception("Cannot import a later proof.")

            if remainder is None:
                return proof

            return proof.proof.get_reference(remainder, context)

        # No luck
        raise Exception("Could not parse reference: " + ref)

    def __str__(self):
        return self.name


class ProofModel(models.Model):
    # Model for Proofs

    model_name = "ProofModel"

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    # The folder entry
    folder_entry = models.OneToOneField(FolderEntry, on_delete=models.CASCADE)

    name = models.CharField(max_length=256)
    slug = models.CharField(max_length=256)

    # Optional description of the proof
    description = models.TextField(blank=True, null=True)

    # Field pointing to an instance of a Proof class
    proof = PickledObjectField(default=None, blank=True, null=True, editable=True)

    # An unsaved instance of the Proof class - used to save processing the same edits in validate calls
    unsaved_proof = PickledObjectField(default=None, blank=True, null=True, editable=True)

    # Proof text
    proof_text = models.TextField(default="")

    # References to other proofs
    references = models.ManyToManyField("self", symmetrical=False, related_name="dependants")

    created = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated = models.DateTimeField(auto_now=True, blank=True, null=True)

    def get_absolute_url(self):
        return "/proof/view/" + self.id + "/" + self.slug + "/"

    def get_absolute_edit_url(self):
        return "/proof/edit/" + self.id + "/" + self.slug + "/"

    def path_to_file(self):
        # Get the path to the file defining this proof
        return "website/proofs/" + self.id + ".txt"

    def code(self):
        # Get the code for this proof
        return self.proof_text

    def set_code(self, code, validity_changed=None, cascade="default"):
        # Set the proof code. Optionally keep a set of proofs whose validity changes.
        # Choose a cascade option out of:
        #   cascade == None - don't refresh any dependants
        #   cascade == "all" - refresh all immediate dependants
        #   cascade == "default" - refresh dependants only if validity has changed

        previous_validity = self.proof.valid if self.proof is not None else True

        self.proof_text = code

        # Refresh the proof instance according to the file
        self.proof = self.formal_system().parse(self, code)
        self.proof.model_id = self.id

        # Clear the unsaved proof
        self.unsaved_proof = None

        # Get the proofs used
        references = self.proof.proofs_used

        # Reverse these to get the model instances
        id_list = [p.model_id for p in references]
        models = ProofModel.objects.filter(id__in=id_list)

        # Clear the many-to-many relationship and add the referenced models
        self.references.clear()
        self.references.add(*models)

        self.save()

        if (cascade == "all") or (cascade == "default" and not (self.proof.valid == previous_validity)):
            if validity_changed is not None:
                validity_changed.add(self)

            # Validity has changed - refresh the dependant proofs
            for p in self.dependants.all():
                p.refresh(refresh_system=False, validity_changed=validity_changed, cascade=cascade)

    def parse_import(self, path, reference_dict=None, parent=None, parent_path=None):
        # Parse an import path on this proof and store it in the reference dictionary.
        # Optionally specify the parent object (formal system or proof folder)

        if path is None:
            return

        self_system = self.formal_system()
        self_parent_folder = self.parent_folder()
        owner = self.owner()

        if reference_dict is None:
            reference_dict = dict()

        if "." in path:
            # Path has multiple parts
            index = path.find(".")
            initial = path[:index]
            remainder = path[index + 1:]

        else:
            initial = path
            remainder = None

        # Get the path up to this part and no further
        total_path = initial if parent is None else parent_path + "." + initial

        # Find the initial part
        if parent is None:
            # Try system
            system = FormalSystemModel.objects.filter(slug=initial, published__isnull=False).first()

            if system is None:
                # Try an unpublished system belonging to this user
                system = FormalSystemModel.objects.filter(slug=initial, owner=owner).first()

            if system is not None and (system == self_system or system in self_system.inherited_systems()):
                # Found it
                reference_dict[total_path] = system

                # Parse the remainder
                self.parse_import(remainder, reference_dict, parent=system, parent_path=total_path)

                return

            # Try folder
            for folder in self.folder_entry.parent_folders():
                if folder.slug == initial:
                    # Found it
                    reference_dict[total_path] = folder

                    # Parse the remainder
                    self.parse_import(remainder, reference_dict, parent=folder, parent_path=total_path)

                    return

            # Try proofs

            # Try an earlier proof in the same folder
            proof = ProofModel.objects.filter(slug=initial, folder_entry__parent_folder=self_parent_folder,
                                              folder_entry__order__lt=self.folder_entry.order).first()

            if proof is None:
                # Try a published root-level proof
                proof = ProofModel.objects.filter(slug=initial, folder_entry__formal_system=self_system,
                                                  folder_entry__parent_folder=None, folder_entry__published__isnull=False).first()

            if proof is None:
                # Try an unpublished root-level proof belonging to this user
                proof = ProofModel.objects.filter(slug=initial, folder_entry__formal_system=self_system,
                                                  folder_entry__parent_folder=None, folder_entry__owner=owner).first()

            if proof is not None:
                # Found it
                reference_dict[total_path] = proof
                return

            else:
                # Couldn't find it
                reference_dict[total_path] = None
                return

        # Parent exists
        if isinstance(parent, FormalSystemModel):
            # Parent is a formal system

            # Try folder
            folder = ProofFolder.objects.filter(slug=initial, folder_entry__formal_system=parent,
                                                folder_entry__parent_folder=None, folder_entry__published__isnull=False).first()

            if folder is None:
                # Try an unpublished folder belonging to this user
                folder = ProofFolder.objects.filter(slug=initial, folder_entry__formal_system=parent,
                                                    folder_entry__parent_folder=None, folder_entry__owner=owner).first()

            if folder is not None:
                # Found it
                reference_dict[total_path] = folder

                # Parse the remainder
                self.parse_import(remainder, reference_dict, parent=folder, parent_path=total_path)

                return

            # Try to get the proof directly
            proof = ProofModel.objects.filter(slug=initial, folder_entry__formal_system=parent,
                                              folder_entry__published__isnull=False).first()

            if proof is None:
                # Try an unpublished proof belonging to this user
                proof = ProofModel.objects.filter(slug=initial, folder_entry__formal_system=parent, folder_entry__owner=owner).first()

            if proof is not None:
                # Found it
                reference_dict[total_path] = proof
                return

        # Folders
        if isinstance(parent, ProofFolder):
            # Parent is a folder

            # Try folder
            folder = ProofFolder.objects.filter(slug=initial, folder_entry__parent_folder=parent,
                                                folder_entry__published__isnull=False).first()

            if folder is None:
                # Try an unpublished folder belonging to this user
                folder = ProofFolder.objects.filter(slug=initial, folder_entry__parent_folder=parent,
                                                    folder_entry__owner=owner).first()

            if folder is not None:
                # Found it
                reference_dict[total_path] = folder

                # Parse the remainder
                self.parse_import(remainder, reference_dict, parent=folder, parent_path=total_path)

                return

            # Try to get the proof directly
            proof = ProofModel.objects.filter(slug=initial, folder_entry__parent_folder=parent,
                                              folder_entry__published__isnull=False).first()

            if proof is None:
                # Try an unpublished proof belonging to this user
                proof = ProofModel.objects.filter(slug=initial, folder_entry__parent_folder=parent,
                                                  folder_entry__owner=owner).first()

            if proof is not None:
                # Found it
                reference_dict[total_path] = proof
                return

            else:
                # Couldn't find it
                reference_dict[total_path] = None
                return

        reference_dict[total_path] = None

    def autocomplete_suggestions(self, path=None):
        # Get autocomplete suggestions on the given path (optional).

        options = []

        if path is None:
            # Return the top level reference options - previous entries in the same folder and formal systems

            # Get the parent folder if it exists
            parent_folder = self.parent_folder()

            if parent_folder is not None:

                # Add to the options
                options.append(parent_folder.folder_entry.autocomplete_option())

                previous_entries = parent_folder.entries.filter(order__lt=self.folder_entry.order)

                options.extend(entry.autocomplete_option() for entry in previous_entries)

                # Include any higher-level folders
                while parent_folder.parent_folder() is not None:
                    parent_folder = parent_folder.parent_folder()
                    options.append(parent_folder.folder_entry.autocomplete_option())

        else:
            # Use the given path to return results in the given file or folder

            # Try to parse the import
            reference_dict = {}
            self.parse_import(path, reference_dict)

            if path in reference_dict:
                target = reference_dict[path]
                if isinstance(target, ProofFolder):
                    # We have a folder.

                    # Find the appropriate order in the folder (so we don't offer later proofs as reference)
                    if self.parent_folder() == target:
                        # Simple case
                        entries = target.entries.filter(order__lt=self.folder_entry.order)

                    else:

                        # Otherwise, target is a higher level folder
                        parent_folders = self.folder_entry.parent_folders()

                        if target not in parent_folders:
                            # Include the entire list
                            entries = target.entries.all()

                        else:
                            key_entry = parent_folders[parent_folders.index(target) + 1].folder_entry
                            entries = target.entries.filter(order__lte=key_entry.order)

                    return [entry.autocomplete_option() for entry in entries]

                elif isinstance(target, ProofModel):
                    # We have a proof.

                    # Get the labelled items in the proof
                    labelled_items = target.proof.reference_context

                    return [{
                        "value": key,
                        "caption": key,
                        "meta": "ProofLine"
                    } for key in labelled_items.keys()]

        # Add system context patterns
        patterns = self.formal_system().formal_system.context.variables
        for key, value in patterns.items():
            if isinstance(value, Pattern):
                options.append({
                    "value": key,
                    "caption": key,
                    "meta": value.pattern_type
                })

        return options

    def refresh(self, refresh_system=True, validity_changed=None, cascade="default"):
        # Set a new instance of the proof. Optionally keep a set of proofs whose validity changes.
        if refresh_system:
            self.formal_system().refresh()

        # Clear the unsaved proof and the proof objects.
        self.unsaved_proof = None
        self.proof = None

        self.set_code(self.code(), validity_changed, cascade)

    def parent_folder(self):
        return self.folder_entry.parent_folder

    def formal_system(self):
        return self.folder_entry.formal_system

    def owner(self):
        return self.folder_entry.owner

    def datetime_published(self):
        return self.folder_entry.datetime_published()

    def publishable(self):
        # Is this proof publishable?

        # First, the proof has to be not published already
        if self.datetime_published() is not None:
            return False

        # It has to be root level
        if self.parent_folder() is not None:
            return False

        # It has to be valid
        if not self.proof.valid:
            return False

        # The formal system has to be published
        if self.formal_system().published is None:
            return False

        # Referenced proofs have to be published
        for proof in self.references.all():
            if proof.datetime_published() is None:
                return False

        # Otherwise it's publishable
        return True

    def __str__(self):
        return self.name


# Update model slugs whenever it is saved
@receiver(pre_save)
def save_slug(sender, instance, **kwargs):

    if sender in (FormalSystemModel, ProofFolder, ProofModel):
        # It's a model that uses slugs
        instance.slug = import_slug(instance.name)


# Check for slug conflicts whenever a new folder entry is saved
@receiver(pre_save)
def check_for_slug_conflicts(sender, instance, **kwargs):
    # Filter for other entries in the same folder

    if sender not in (ProofFolder, ProofModel):
        return

    entry = instance.folder_entry

    other_entries = FolderEntry.objects.filter(
        parent_folder=entry.parent_folder,
        owner=entry.owner,
        formal_system=entry.formal_system,
        published=entry.published
    )

    for other_entry in other_entries:
        if other_entry == entry:
            continue

        other_entry_item = other_entry.item()
        if other_entry_item.slug == instance.slug:
            entry.delete()
            instance.delete()
            raise Exception("Could not save item - " + instance.name +
                            " has a slug that collides with another entry in this folder.")
