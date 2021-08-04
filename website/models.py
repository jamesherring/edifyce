from django.db import models
from ordered_model.models import OrderedModel
from django.contrib.auth.models import User
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from picklefield.fields import PickledObjectField
import random
from slugify import slugify
from website.logical.compiler import get_inherited_system, compile


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
    formal_system_text =  models.TextField(default="")

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

        return {self.inherits_from}.union(self.inherits_from.inherited_systems)

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
            try:
                self.inherits_from = FormalSystemModel.objects.get(slug=slug)
                system_dict[slug] = self.inherits_from.formal_system
            except:
                pass

        # Refresh the formal system instance according to the file
        self.formal_system = compile(code, system_dict=system_dict)

        self.save()

    def refresh(self):
        # Refresh the instance
        self.set_code(self.code())

    def parse(self, proof_model, code):
        # Parse proof code into a proof instance

        # Find any references to other proofs
        reference_paths = self.formal_system.get_references(code)

        # Build a dictionary of references to other proofs
        reference_dict = dict()
        for path in reference_paths:
            proof_model.parse_import(path, reference_dict)

        # Create a proof instance
        proof = self.formal_system.parse(code, reference_proofs=reference_dict)

        return proof, reference_dict

    def __str__(self):
        return self.name


class FolderEntry(OrderedModel):
    # A folder entry (either a proof or a folder)

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    parent_folder = models.ForeignKey("ProofFolder", on_delete=models.CASCADE, blank=True, null=True, related_name="entries")

    # Owner of this item
    owner = models.ForeignKey(Profile, on_delete=models.SET_NULL, blank=True, null=True)

    # The formal system this entry belongs to
    formal_system = models.ForeignKey(FormalSystemModel, on_delete=models.CASCADE, related_name="entries")

    # Order with respect to parent folder - and owner and system in case of root level items
    order_with_respect_to = ('parent_folder', 'owner', 'formal_system')

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
            return set()

        return {self.parent_folder}.union(self.parent_folder.folder_entry.parent_folders())

    def autocomplete_option(self):
        # Return a dictionary option for autocomplete for this entry

        item = self.item()
        slug = import_slug(item.slug)
        return {
            "value": slug,
            "caption": slug,
            "meta": "Folder" if isinstance(item, ProofFolder) else "Proof"
        }


class ProofFolder(models.Model):
    # A model for folders containing folders and proofs

    model_name = "ProofFolder"

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    # The folder entry
    folder_entry = models.OneToOneField(FolderEntry, on_delete=models.CASCADE)

    name = models.CharField(max_length=256)
    slug = models.CharField(max_length=256)

    # Date the folder is published
    published = models.DateTimeField(blank=True, null=True)

    created = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated = models.DateTimeField(auto_now=True, blank=True, null=True)

    def get_absolute_url(self):
        return "/folder/view/" + self.id + "/" + self.slug + "/"

    def parent_folder(self):
        return self.folder_entry.parent_folder

    def formal_system(self):
        return self.folder_entry.formal_system

    def owner(self):
        return self.folder_entry.owner

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

    def get_reference(self, ref, context):
        # Get a reference

        initial = ref
        remainder = None

        if "." in ref:
            index = ref.find(".")
            initial = ref[:index]
            remainder = ref[index + 1:]

        # Try folder
        folder = self.sub_folders().filter(slug=initial).first()
        if folder is not None:
            if remainder is None:
                return folder

            return folder.get_reference(remainder, context)

        # Try proof
        proof = self.proofs().filter(slug=initial).first()
        if proof is not None:
            if remainder is None:
                return proof

            return proof.proof.get_reference(remainder, context)

        # No luck
        return None

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

    # Proof text
    proof_text = models.TextField(default="")

    # References to other proofs
    references = models.ManyToManyField("self", symmetrical=False)

    # Date the proof is published
    published = models.DateTimeField(blank=True, null=True)

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

    def set_code(self, code):
        # Set the proof code

        self.proof_text = code

        # Refresh the proof instance according to the file
        self.proof, references = self.formal_system().parse(self, code)

        self.save()

    def parse_import(self, path, reference_dict=None, parent=None, parent_path=None):
        # Parse an import path on this proof and store it in the reference dictionary.
        # Optionally specify the parent object (formal system or proof folder)
        # Return the target proof (ignore line labels)

        if path is None:
            return

        self_system = self.formal_system()
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
                self.parse_import(remainder, reference_dict, parent=system, parent_path=initial)

                return

            # Try folder
            for folder in self.folder_entry.parent_folders():
                if folder.slug == initial:
                    # Found it
                    reference_dict[total_path] = folder

                    # Parse the remainder
                    self.parse_import(remainder, reference_dict, parent=folder, parent_path=initial)

                    return

            # Try proofs
            proof = ProofModel.objects.filter(slug=initial, folder_entry__formal_system=system, published__isnull=False).first()

            if proof is None:
                # Try an unpublished proof belonging to this user
                proof = ProofModel.objects.filter(slug=initial, folder_entry__formal_system=system, folder_entry__owner=owner).first()

            if proof is not None:
                # Found it
                reference_dict[total_path] = proof.proof
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
                                                folder_entry__parent_folder=None, published__isnull=False).first()

            if folder is None:
                # Try an unpublished folder belonging to this user
                folder = ProofFolder.objects.filter(slug=initial, folder_entry__formal_system=parent,
                                                    folder_entry__parent_folder=None, folder_entry__owner=owner).first()

            if folder is not None:
                # Found it
                reference_dict[total_path] = folder

                # Parse the remainder
                self.parse_import(remainder, reference_dict, parent=folder, parent_path=initial)

                return

            # Try to get the proof directly
            proof = ProofModel.objects.filter(slug=initial, folder_entry__formal_system=parent, published__isnull=False).first()

            if proof is None:
                # Try an unpublished proof belonging to this user
                proof = ProofModel.objects.filter(slug=initial, folder_entry__formal_system=parent, folder_entry__owner=owner).first()

            if proof is not None:
                # Found it
                reference_dict[total_path] = proof.proof
                return

        # Folders
        if isinstance(parent, ProofFolder):
            # Parent is a folder

            # Try folder
            folder = ProofFolder.objects.filter(slug=initial, folder_entry__parent_folder=parent,
                                                published__isnull=False).first()

            if folder is None:
                # Try an unpublished folder belonging to this user
                folder = ProofFolder.objects.filter(slug=initial, folder_entry__parent_folder=parent,
                                                    folder_entry__owner=owner).first()

            if folder is not None:
                # Found it
                reference_dict[total_path] = folder

                # Parse the remainder
                self.parse_import(remainder, reference_dict, parent=folder, parent_path=initial)

                return

            # Try to get the proof directly
            proof = ProofModel.objects.filter(slug=initial, folder_entry__parent_folder=parent,
                                              published__isnull=False).first()

            if proof is None:
                # Try an unpublished proof belonging to this user
                proof = ProofModel.objects.filter(slug=initial, folder_entry__parent_folder=parent,
                                                  folder_entry__owner=owner).first()

            if proof is not None:
                # Found it
                reference_dict[total_path] = proof.proof
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

        return options

    def refresh(self, refresh_system=True):
        # Set a new instance of the proof
        if refresh_system:
            self.formal_system().refresh()
        self.set_code(self.code())

    def parent_folder(self):
        return self.folder_entry.parent_folder

    def formal_system(self):
        return self.folder_entry.formal_system

    def owner(self):
        return self.folder_entry.owner

    def __str__(self):
        return self.name


# Update model slugs whenever it is saved
@receiver(pre_save)
def save_slug(sender, instance, **kwargs):

    if sender in (FormalSystemModel, ProofFolder, ProofModel):
        # It's a model that uses slugs
        instance.slug = import_slug(instance.name)
