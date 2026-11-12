"""Legacy Vercel entrypoint — NOT used by the current deployment.

The deployment now uses Vercel Services (see vercel.json): the Django app
in backend/ is detected from manage.py / WSGI_APPLICATION and serves
/api/*, and the React frontend in frontend/ serves everything else.
This file is kept only as a reference for the older single-function
pattern; it is outside both service roots and is ignored at build time.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

from django.core.wsgi import get_wsgi_application  # noqa: E402

app = get_wsgi_application()
