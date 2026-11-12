"""JSON API views. No DRF: plain Django views, JSON in/out."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .services import UpstreamError, build_trip

ALLOWED_INTERVALS = (10.0, 25.0, 50.0)


@csrf_exempt
@require_http_methods(["POST"])
def routes_view(request):
    """POST /api/routes/ -> routes, checkpoints, risk, recommendation.

    Body: {origin, destination, departure_datetime (ISO 8601),
    load_weight_lb, sample_interval_miles (10, 25 or 50)}.
    """
    try:
        body = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({"error": "Request body must be valid JSON."}, status=400)

    origin = str(body.get("origin") or "").strip()
    destination = str(body.get("destination") or "").strip()
    if not origin or not destination:
        return JsonResponse({"error": "Both 'origin' and 'destination' are required."}, status=400)

    try:
        load_weight_lb = float(body.get("load_weight_lb"))
    except (TypeError, ValueError):
        return JsonResponse({"error": "'load_weight_lb' must be a number."}, status=400)
    if load_weight_lb < 0 or load_weight_lb > 200_000:
        return JsonResponse({"error": "'load_weight_lb' must be between 0 and 200000."}, status=400)

    try:
        interval = float(body.get("sample_interval_miles", 25))
    except (TypeError, ValueError):
        return JsonResponse({"error": "'sample_interval_miles' must be 10, 25 or 50."}, status=400)
    if interval not in ALLOWED_INTERVALS:
        return JsonResponse({"error": "'sample_interval_miles' must be 10, 25 or 50."}, status=400)

    departure_raw = str(body.get("departure_datetime") or "").strip()
    try:
        departure = datetime.fromisoformat(departure_raw.replace("Z", "+00:00"))
    except ValueError:
        return JsonResponse(
            {"error": "'departure_datetime' must be an ISO 8601 date/time."}, status=400
        )
    if departure.tzinfo is None:
        departure = departure.replace(tzinfo=timezone.utc)
    departure = departure.astimezone(timezone.utc)

    try:
        result = build_trip(origin, destination, departure, load_weight_lb, interval)
    except UpstreamError as exc:
        return JsonResponse({"error": str(exc)}, status=502)
    return JsonResponse(result)


@require_http_methods(["GET"])
def health_view(request):
    return JsonResponse({"status": "ok"})
