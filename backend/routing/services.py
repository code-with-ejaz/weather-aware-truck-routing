"""External API clients and trip computation.

Free, no-key APIs only:
- Geocoding: Nominatim (OpenStreetMap). One request per place name, with a
  proper User-Agent identifying the app and a contact email, per the
  Nominatim usage policy.
- Routing: OSRM public demo server, alternatives=true. It usually returns
  1-3 routes; when it returns fewer than 3 we return what exists and say so
  (see ``warnings`` in the API response). We never fabricate routes.
- Weather: Open-Meteo forecast API, hourly values, wind in mph and
  precipitation in inches. One batched request for all (deduplicated)
  checkpoint/corridor points, so a trip costs one weather call per batch
  of up to 100 locations.

Speed/ETA model: OSRM gives total distance and duration per route. We
assume the truck travels at the route's average speed (distance/duration)
and compute each checkpoint's ETA as departure + distance/speed. This is
the simple, documented model the brief allows ("estimated arrival time");
it does not model traffic or stops.
"""

from __future__ import annotations

import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import requests

from .risk import checkpoint_risk, summarize_route

USER_AGENT = "weather-aware-truck-routing/1.0 (contact: ejazniazi88@gmail.com)"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/{coords}"
OPENMETEO_URL = "https://api.open-meteo.com/v1/forecast"
REQUEST_TIMEOUT = 15  # seconds per upstream call
EARTH_RADIUS_MILES = 3958.8
METERS_PER_MILE = 1609.344

# Nominatim usage policy asks for at most 1 request/second. The two
# geocode calls for a trip run with a small stagger; a module-level
# timestamp throttle keeps bursts polite across requests in one process.
_last_nominatim_call = 0.0


class UpstreamError(Exception):
    """An upstream API failed or returned unusable data."""


def _throttle_nominatim() -> None:
    global _last_nominatim_call
    now = time.monotonic()
    wait = 1.0 - (now - _last_nominatim_call)
    if wait > 0:
        time.sleep(wait)
    _last_nominatim_call = time.monotonic()


def geocode(place: str) -> dict:
    """Geocode a place name to lat/lon via Nominatim."""
    _throttle_nominatim()
    try:
        resp = requests.get(
            NOMINATIM_URL,
            params={"q": place, "format": "json", "limit": 1},
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise UpstreamError(f"Geocoding failed for {place!r}: {exc}") from exc
    results = resp.json()
    if not results:
        raise UpstreamError(f"Could not find a location for {place!r}. Try a city and state, e.g. 'Dallas, TX'.")
    return {
        "lat": float(results[0]["lat"]),
        "lon": float(results[0]["lon"]),
        "display_name": results[0]["display_name"],
    }


def get_routes(origin: dict, destination: dict) -> list[dict]:
    """Fetch up to 3 alternative routes from OSRM (driving profile)."""
    coords = f"{origin['lon']},{origin['lat']};{destination['lon']},{destination['lat']}"
    try:
        resp = requests.get(
            OSRM_URL.format(coords=coords),
            params={
                "overview": "full",
                "geometries": "geojson",
                "alternatives": "true",
                "steps": "false",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise UpstreamError(f"Routing request failed: {exc}") from exc
    data = resp.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise UpstreamError(f"Routing failed: {data.get('message', 'no routes returned')}")
    routes = []
    for route in data["routes"][:3]:
        routes.append(
            {
                "distance_meters": float(route["distance"]),
                "duration_seconds": float(route["duration"]),
                # GeoJSON coordinates: [lon, lat] pairs.
                "coordinates": [(float(c[0]), float(c[1])) for c in route["geometry"]["coordinates"]],
            }
        )
    return routes


def haversine_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in miles between two points."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_MILES * math.asin(math.sqrt(a))


def sample_along_route(coordinates: list[tuple[float, float]], interval_miles: float) -> list[dict]:
    """Sample points every ``interval_miles`` along a route polyline.

    Returns points with lat/lon and cumulative road distance in miles,
    including the origin (distance 0) and the destination. Distances are
    computed from the polyline geometry (haversine between vertices),
    which closely matches the OSRM route distance.
    """
    # Cumulative distance at each vertex.
    cumulative = [0.0]
    for i in range(1, len(coordinates)):
        lon1, lat1 = coordinates[i - 1]
        lon2, lat2 = coordinates[i]
        cumulative.append(cumulative[-1] + haversine_miles(lat1, lon1, lat2, lon2))
    total = cumulative[-1]

    targets = [0.0]
    d = interval_miles
    while d < total:
        targets.append(d)
        d += interval_miles
    if total > 0:
        targets.append(total)

    points = []
    seg = 0
    for target in targets:
        while seg < len(cumulative) - 2 and cumulative[seg + 1] < target:
            seg += 1
        # Interpolate between vertex seg and seg+1.
        d0, d1 = cumulative[seg], cumulative[seg + 1]
        lon1, lat1 = coordinates[seg]
        lon2, lat2 = coordinates[seg + 1]
        frac = 0.0 if d1 == d0 else (target - d0) / (d1 - d0)
        frac = max(0.0, min(1.0, frac))
        points.append(
            {
                "lat": lat1 + (lat2 - lat1) * frac,
                "lon": lon1 + (lon2 - lon1) * frac,
                "distance_miles": round(target, 2),
            }
        )
    return points


def fetch_weather(points: list[dict], start: datetime, end: datetime) -> dict[tuple[float, float], dict]:
    """Fetch hourly weather for many points in batched Open-Meteo calls.

    Returns {(lat, lon): {"times": [...datetimes...], "wind": [...],
    "rain": [...], "snow": [...]}} keyed by the rounded coordinates used
    in the request. Rain uses the ``rain`` variable when present and
    falls back to ``precipitation``; snow uses ``snowfall``.
    """
    unique: dict[tuple[float, float], None] = {}
    for p in points:
        unique[(round(p["lat"], 3), round(p["lon"], 3))] = None
    coords = list(unique)
    if not coords:
        return {}

    # Open-Meteo needs whole forecast days; cover [start, end] plus margin.
    days = max(1, min(16, (end.date() - start.date()).days + 2))
    result: dict[tuple[float, float], dict] = {}
    for i in range(0, len(coords), 100):
        batch = coords[i : i + 100]
        params = {
            "latitude": ",".join(str(c[0]) for c in batch),
            "longitude": ",".join(str(c[1]) for c in batch),
            "hourly": "wind_speed_10m,precipitation,rain,snowfall",
            "wind_speed_unit": "mph",
            "precipitation_unit": "inch",
            "timezone": "UTC",
            "forecast_days": days,
        }
        try:
            resp = requests.get(
                OPENMETEO_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise UpstreamError(f"Weather request failed: {exc}") from exc
        payload = resp.json()
        items = payload if isinstance(payload, list) else [payload]
        for item, key in zip(items, batch):
            hourly = item.get("hourly", {})
            times = [
                datetime.fromisoformat(t).replace(tzinfo=timezone.utc) for t in hourly.get("time", [])
            ]
            rain = hourly.get("rain") or hourly.get("precipitation") or []
            result[key] = {
                "times": times,
                "wind": hourly.get("wind_speed_10m") or [],
                "rain": rain,
                "snow": hourly.get("snowfall") or [],
            }
    return result


def weather_at(weather: dict, when: datetime) -> dict | None:
    """Hourly weather nearest to ``when`` (UTC), or None if uncovered."""
    times = weather["times"]
    if not times:
        return None
    # Nearest hourly slot; if the ETA is outside the forecast range by
    # more than 1 hour, report no data rather than inventing weather.
    nearest = min(range(len(times)), key=lambda i: abs((times[i] - when).total_seconds()))
    if abs((times[nearest] - when).total_seconds()) > 3600:
        return None
    def _val(series: list, idx: int) -> float:
        v = series[idx] if idx < len(series) else None
        return float(v) if v is not None else 0.0
    return {
        "wind_mph": round(_val(weather["wind"], nearest), 1),
        "rain_in_hr": round(_val(weather["rain"], nearest), 3),
        "snow_in_hr": round(_val(weather["snow"], nearest), 3),
        "forecast_time": times[nearest].isoformat(),
    }


def build_trip(
    origin_text: str,
    destination_text: str,
    departure: datetime,
    load_weight_lb: float,
    sample_interval_miles: float,
) -> dict:
    """Compute the full trip: routes, checkpoints, risk, heatmap data."""
    warnings: list[str] = []

    # Geocode both ends (parallel; Nominatim throttle keeps us polite).
    with ThreadPoolExecutor(max_workers=2) as pool:
        origin_f = pool.submit(geocode, origin_text)
        destination_f = pool.submit(geocode, destination_text)
        origin = origin_f.result()
        destination = destination_f.result()

    raw_routes = get_routes(origin, destination)
    if len(raw_routes) < 3:
        warnings.append(
            f"Routing API returned {len(raw_routes)} route(s) instead of 3 for this "
            "origin/destination. Only real routes are shown; none were fabricated."
        )

    # Sample checkpoints (user interval) and heatmap points (5 miles) for
    # every route, then fetch weather once for all deduplicated points.
    per_route_points = []
    all_points: list[dict] = []
    for route in raw_routes:
        checkpoints = sample_along_route(route["coordinates"], sample_interval_miles)
        heat_points = sample_along_route(route["coordinates"], 5.0)
        per_route_points.append((checkpoints, heat_points))
        all_points.extend(checkpoints)
        all_points.extend(heat_points)

    # Weather horizon: departure through departure+48h (heatmap slider),
    # and at least through the longest trip ETA.
    longest = max(r["duration_seconds"] for r in raw_routes)
    weather_end = max(departure + timedelta(hours=48), departure + timedelta(seconds=longest))
    weather = fetch_weather(all_points, departure, weather_end)

    routes_out = []
    for idx, route in enumerate(raw_routes):
        checkpoints, heat_points = per_route_points[idx]
        distance_miles = route["distance_meters"] / METERS_PER_MILE
        duration = route["duration_seconds"]
        avg_speed_mph = distance_miles / (duration / 3600) if duration > 0 else 0.0

        cps = []
        for j, cp in enumerate(checkpoints):
            eta = departure + timedelta(hours=cp["distance_miles"] / avg_speed_mph) if avg_speed_mph else departure
            key = (round(cp["lat"], 3), round(cp["lon"], 3))
            w = weather_at(weather[key], eta) if key in weather else None
            if w is None:
                warnings.append(f"Weather unavailable for a checkpoint on route {idx + 1}; risk shown as low.")
                w = {"wind_mph": 0.0, "rain_in_hr": 0.0, "snow_in_hr": 0.0, "forecast_time": None}
            risk = checkpoint_risk(w["wind_mph"], w["rain_in_hr"], w["snow_in_hr"], load_weight_lb)
            # Segment miles: distance to the next checkpoint (or destination).
            if j + 1 < len(checkpoints):
                seg = checkpoints[j + 1]["distance_miles"] - cp["distance_miles"]
            else:
                seg = 0.0
            cps.append(
                {
                    "lat": round(cp["lat"], 5),
                    "lon": round(cp["lon"], 5),
                    "distance_miles": cp["distance_miles"],
                    "eta": eta.isoformat(),
                    "wind_mph": w["wind_mph"],
                    "rain_in_hr": w["rain_in_hr"],
                    "snow_in_hr": w["snow_in_hr"],
                    "risk": risk,
                    "segment_miles": round(seg, 2),
                }
            )
        summary = summarize_route(cps)

        # Heatmap: for each corridor point, risk score at each 0-48h offset.
        heat_lats, heat_lons, heat_grid = [], [], []
        for hp in heat_points:
            key = (round(hp["lat"], 3), round(hp["lon"], 3))
            series = []
            for offset in range(49):
                when = departure + timedelta(hours=offset)
                w = weather_at(weather[key], when) if key in weather else None
                if w is None:
                    series.append(0)
                else:
                    series.append(
                        {"low": 0, "moderate": 1, "high": 2, "severe": 3, "no_travel": 4}[
                            checkpoint_risk(w["wind_mph"], w["rain_in_hr"], w["snow_in_hr"], load_weight_lb)
                        ]
                    )
            heat_lats.append(round(hp["lat"], 5))
            heat_lons.append(round(hp["lon"], 5))
            heat_grid.append(series)

        routes_out.append(
            {
                "id": idx,
                "distance_miles": round(distance_miles, 1),
                "duration_minutes": round(duration / 60),
                "duration_seconds": round(duration),
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lon, lat] for lon, lat in route["coordinates"]],
                },
                "checkpoints": cps,
                "summary": summary,
                "heatmap": {"lats": heat_lats, "lons": heat_lons, "risk_grid": heat_grid},
            }
        )

    # Recommendation per the brief's order (see risk.py docstring).
    from .risk import recommend_route, recommendation_reason

    best_idx = recommend_route(routes_out)
    reason = recommendation_reason(
        routes_out[best_idx], [r for i, r in enumerate(routes_out) if i != best_idx]
    )

    return {
        "origin": origin,
        "destination": destination,
        "departure_datetime": departure.isoformat(),
        "load_weight_lb": load_weight_lb,
        "sample_interval_miles": sample_interval_miles,
        "routes": routes_out,
        "recommended_route_id": best_idx,
        "recommendation_reason": reason,
        "warnings": sorted(set(warnings)),
        "data_sources": {
            "geocoding": "Nominatim (OpenStreetMap)",
            "routing": "OSRM public demo server",
            "weather": "Open-Meteo forecast API (hourly)",
            "map_tiles": "OpenStreetMap via Leaflet",
        },
    }
