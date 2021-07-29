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

    def inherited_system_slugs(self):
        # Return a set of slugs of the chain of systems
        if self.inherits_from is None:
            return set()

        return {self.inherits_from}.union(self.inherits_from.inherited_system_slugs)

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

        return proof

    def __str__(self):
        return self.name


class FolderEntry(OrderedModel):
    # A folder entry (either a proof or a folder)

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    parent_folder = models.ForeignKey("ProofFolder", on_delete=models.CASCADE, blank=True, null=True, related_name="entries")

    # Owner of this item
    owner = models.ForeignKey(Profile, on_delete=models.SET_NULL, blank=True, null=True)

    # The formal system this entry belongs to
    formal_system = models.ForeignKey(FormalSystemModel, on_delete=models.CASCADE)

    # Order with respect to parent folder - and owner and system in case of root level items
    order_with_respect_to = ('parent_folder', 'owner', 'formal_system')


class ProofFolder(models.Model):
    # A model for folders containing folders and proofs

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    # The folder entry
    folder_entry = models.OneToOneField(FolderEntry, on_delete=models.CASCADE)

    name = models.CharField(max_length=256)
    slug = models.CharField(max_length=256)

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

    def __str__(self):
        return self.name


class ProofModel(models.Model):
    # Model for Proofs

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
        self.proof = self.formal_system().parse(self, code)
        self.save()

    def parse_import(self, path, reference_dict=None, parent=None, parent_path=None):
        # Parse an import path on this proof and store it in the reference dictionary.
        # Optionally specify the parent object (formal system or proof folder)
        # Return the target proof (ignore line labels)

        system = self.formal_system()

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
                system = FormalSystemModel.objects.filter(slug=initial, folder_entry__owner=self.owner()).first()

            if system is not None and system.slug in system.inherited_system_slugs():
                # Found it
                reference_dict[total_path] = system

                # Parse the remainder
                self.parse_import(remainder, reference_dict, parent=system, parent_path=initial)

                return

            # Try folder
            # --------------------------------------------------------------------

            # Try proofs
            proof = ProofModel.objects.filter(slug=initial, folder_entry__formal_system=system, published__isnull=False).first()

            if proof is None:
                # Try an unpublished proof belonging to this user
                proof = ProofModel.objects.filter(slug=initial, folder_entry__formal_system=system, folder_entry__owner=self.owner()).first()

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
            # --------------------------------------------------------------------

            # Try to get the proof directly
            proof = ProofModel.objects.filter(slug=initial, folder_entry__formal_system=parent, published__isnull=False).first()

            if proof is None:
                # Try an unpublished proof belonging to this user
                proof = ProofModel.objects.filter(slug=initial, folder_entry__formal_system=parent, folder_entry__owner=self.owner()).first()

            if proof is not None:
                # Found it
                reference_dict[total_path] = proof.proof
                return

            else:
                # Couldn't find it
                reference_dict[total_path] = None
                return

        # Folders

        reference_dict[total_path] = None

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
def save_system(sender, instance, **kwargs):

    if sender in (FormalSystemModel, ProofFolder, ProofModel):
        # It's a model that uses slugs
        instance.slug = slugify(instance.name)
