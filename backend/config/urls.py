"""Root URL config: API under /api/, built React app for everything else."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, HttpResponse, Http404
from django.urls import include, path, re_path

DIST_DIR = settings.REPO_ROOT / "frontend" / "dist"


def _serve_dist_file(relative: str) -> FileResponse:
    target = (DIST_DIR / relative).resolve()
    if DIST_DIR.resolve() not in target.parents and target != DIST_DIR.resolve():
        raise Http404
    if not target.is_file():
        raise Http404
    content_type, _ = mimetypes.guess_type(str(target))
    return FileResponse(target.open("rb"), content_type=content_type or "application/octet-stream")


def index_view(request):
    """Serve the built React app, or a helpful message before it is built."""
    index = DIST_DIR / "index.html"
    if index.is_file():
        return _serve_dist_file("index.html")
    return HttpResponse(
        "Frontend not built yet. Run: cd frontend && npm install && npm run build "
        "(or run the Vite dev server on port 5173). API: POST /api/routes/",
        content_type="text/plain",
    )


def asset_view(request, asset_path: str):
    return _serve_dist_file(f"assets/{asset_path}")


urlpatterns = [
    path("api/", include("routing.urls")),
    re_path(r"^assets/(?P<asset_path>.+)$", asset_view),
    re_path(r"^.*$", index_view),
]
