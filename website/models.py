from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from picklefield.fields import PickledObjectField
import string
import random
from website.matching import LatticeCompiler


def id_gen(length=12, chars=string.ascii_lowercase + string.ascii_uppercase + string.digits + "-_"):
    # An id generator to uniquely identify objects
    return "".join(random.SystemRandom().choice(chars) for _ in range(length))


class Profile(models.Model):

    # One-to-one relationship to the user model
    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE)

    created = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated = models.DateTimeField(auto_now=True, blank=True, null=True)

    def get_absolute_url(self):
        # Return the absolute url for the profile
        return "/profile/" + self.user.username + "/"

    def __str__(self):
        return str(self.user)


# Save a profile model whenever a user is created
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)


# Update the profile model whenever a user is updated
@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    profile, created = Profile.objects.get_or_create(user=instance)
    profile.save()


class FormalSystemModel(models.Model):
    # Model for Formal Systems

    id = models.CharField(default=id_gen, max_length=64, primary_key=True, editable=False)

    name = models.CharField(max_length=64)
    slug = models.CharField(max_length=64, unique=True)

    # Field pointing to an instance of a FormalSystem class
    formal_system = PickledObjectField(default=None, blank=True, null=True)

    created = models.DateTimeField(auto_now_add=True, blank=True, null=True)
    updated = models.DateTimeField(auto_now=True, blank=True, null=True)

    def get_absolute_url(self):
        return "/system/" + self.slug + "/"

    def path_to_file(self):
        # Get the path to the file defining this formal system
        return "website/formal_systems/" + self.slug + ".py"

    def code(self):
        # Get the code for this formal system
        with open(self.path_to_file()) as f:
            return f.read()

    def set_code(self, code):
        # Set the system code

        # Save it to the system file
        with open(self.path_to_file(), "w") as f:
            f.write(code)

        # Refresh the formal system instance according to the file
        compiler = LatticeCompiler()
        self.formal_system = compiler.initiate_formal_system(path_to_file=self.path_to_file())
        self.save()

    def __str__(self):
        return self.name
