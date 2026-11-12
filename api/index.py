"""Vercel serverless entrypoint: exposes the Django WSGI app.

Vercel routes /api/* here (see vercel.json). The React frontend is served
as static files from frontend/dist by Vercel itself; Django only handles
the API in this deployment. Locally, Django can also serve the built
frontend (see backend/config/urls.py).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

app = get_wsgi_application()
