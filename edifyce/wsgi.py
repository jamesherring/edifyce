"""
WSGI config for edifyce project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/3.0/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'edifyce.settings')

# Assume we are in the local environment
os.environ.setdefault('ENVIRONMENT', 'local')

application = get_wsgi_application()
