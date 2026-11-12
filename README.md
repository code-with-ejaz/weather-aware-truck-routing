# Weather-Aware Truck Routing

A React + Django web app that helps a truck driver choose the safest route
based on weather, load weight, and travel time.

Built for the Spotter Full Stack Developer assessment (React + Django).
The Loom walkthrough is a separate step, recorded by the applicant — see
`loom-outline.md` in this repo for the script outline.

## What it does

The user enters an origin, a destination, a departure date/time, and a load
weight. The app:

1. Geocodes both places (Nominatim / OpenStreetMap).
2. Requests up to 3 alternative routes from OSRM.
3. Samples weather every 10, 25, or 50 miles (user-selectable) along each
   route, at the truck's estimated arrival time at each checkpoint
   (Open-Meteo hourly forecast).
4. Classifies each checkpoint's weather risk with the brief's exact
   wind/rain/snow tables, escalated by the load rules.
5. Recommends the best route: fewest No Travel miles, then fewest Severe
   miles, then fewest High miles, then lowest average risk, then shortest
   travel time.
6. Shows all routes, checkpoints, risk levels, ETAs, and route summaries on
   an interactive Leaflet map (OpenStreetMap tiles).
7. Shows a weather heatmap along the trip corridor with a 0–48 hour
   forecast slider.

## Architecture

```
┌─────────────────────────┐      POST /api/routes/      ┌──────────────────────────┐
│ React + Vite frontend   │ ───────────────────────────▶ │ Django 5 (no DRF)      │
│ frontend/               │ ◀─────────────────────────── │ backend/               │
│  Leaflet map + heatmap  │      JSON: routes,          │  routing/views.py      │
│  route cards + table    │      checkpoints, risk,     │  routing/services.py   │
└─────────────────────────┘      heatmap grid           │  routing/risk.py       │
                                                         └──────┬───────┬─────────┘
                                                                │       │
                                        ┌───────────────────────┘       └───────────────────────┐
                                        ▼                                                       ▼
                                 Nominatim + OSRM                                    Open-Meteo forecast API
                                 (geocoding + routing)                               (hourly wind/rain/snow)
```

- **Frontend** (`frontend/`): React 18 + Vite, plain Leaflet for the map,
  `leaflet.heat` for the heatmap. No UI framework; one `App.jsx` plus CSS.
- **Backend** (`backend/`): Django 5, plain JSON views (no DRF needed for
  two endpoints). `routing/risk.py` holds the pure risk/recommendation
  logic (unit-tested); `routing/services.py` holds the upstream API clients
  and trip computation; `routing/views.py` validates input and returns JSON.
- **Production**: Vercel Services (see `vercel.json`): a `backend` service
  rooted at `backend/` (Django, detected from `manage.py` and
  `WSGI_APPLICATION`, serving `/api/*`) and a `frontend` service rooted
  at `frontend/` (Vite build, serving everything else). Locally, Django
  can also serve the built frontend itself (see "Run locally").

## API

### `POST /api/routes/`

Request body (JSON):

```json
{
  "origin": "Dallas, TX",
  "destination": "Houston, TX",
  "departure_datetime": "2026-11-12T13:00:00Z",
  "load_weight_lb": 30000,
  "sample_interval_miles": 25
}
```

- `sample_interval_miles` must be 10, 25, or 50.
- `departure_datetime` is ISO 8601; a naive value is treated as UTC.
- `load_weight_lb` must be between 0 and 200,000.

Response (JSON): `origin` / `destination` (geocoded places), the echoed
inputs, `routes`, `recommended_route_id`, `recommendation_reason`,
`warnings`, and `data_sources`. Each route has:

- `distance_miles`, `duration_minutes`, `duration_seconds`
- `geometry` (GeoJSON LineString, `[lon, lat]` pairs)
- `checkpoints`: `lat`, `lon`, `distance_miles`, `eta` (ISO 8601, UTC),
  `wind_mph`, `rain_in_hr`, `snow_in_hr`, `risk`, `segment_miles`
- `summary`: miles per risk level plus `avg_risk_score`
- `heatmap`: corridor points (`lats`, `lons`) and `risk_grid`
  (risk score 0–4 per point per forecast hour offset 0–48)

Errors: `400` for invalid input, `502` with a plain-language message when
an upstream API (geocoding, routing, weather) fails.

### `GET /api/health/`

Returns `{"status": "ok"}`.

## Risk rules

Exactly as specified in the assessment brief:

| Condition   | Low       | Moderate  | High      | Severe    | No Travel |
|-------------|-----------|-----------|-----------|-----------|-----------|
| Wind        | <25 mph   | 25–34     | 35–44     | 45–54     | ≥55 mph   |
| Rain        | <0.10 in/hr | 0.10–0.25 | 0.25–0.50 | 0.50–1.00 | >1.00     |
| Snow        | <0.5 in/hr  | 0.5–1.0   | 1.0–2.0   | 2.0–3.0   | >3.0      |

- A checkpoint's risk is the worst of its wind/rain/snow risks.
- Load rules: wind ≥55 mph → No Travel for any load; wind 45–54 mph with
  load >30,000 lb → No Travel; wind 35–44 mph with load >40,000 lb →
  at least Severe. "More than" is strict: exactly 30,000 / 40,000 lb does
  not escalate.
- Boundary convention: bands are half-open, e.g. wind 34.9 is Moderate and
  35.0 is High; rain 1.00 in/hr is Severe and 1.01 is No Travel (the brief
  says No Travel is strictly ">1.00"). See `backend/routing/risk.py`.

## Recommendation ranking

1. Fewest No Travel miles — see note below.
2. Fewest Severe miles.
3. Fewest High miles.
4. Lowest average risk (mile-weighted mean of risk scores 0–4).
5. Shortest travel time.

**Note on No Travel miles:** the brief's ranking lists Severe miles first
and does not explicitly name No Travel miles. We count `no_travel_miles`
separately in every route summary and rank it before Severe miles, because
a No Travel stretch is strictly worse than a Severe stretch. This is an
explicit, documented choice, and the summary exposes the numbers so a
reviewer can re-rank without it.

**ETA model:** each checkpoint's ETA assumes the truck travels at the
route's average speed (OSRM distance ÷ OSRM duration). This is the simple,
documented model the brief allows; it does not model traffic or stops.
Weather is the Open-Meteo hourly value nearest the ETA.

## Run locally

Two terminals, from the repo root:

```bash
# Terminal 1 — backend (Django API on http://127.0.0.1:8000)
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cd backend && ../.venv/bin/python manage.py runserver

# Terminal 2 — frontend (Vite dev server on http://127.0.0.1:5173, proxies /api)
cd frontend && npm install && npm run dev
```

Single-server alternative: build the frontend once
(`cd frontend && npm install && npm run build`), then Django serves it at
`http://127.0.0.1:8000/` together with the API.

Run the tests:

```bash
cd backend && ../.venv/bin/python manage.py test routing
```

## Deployment

The app is configured for Vercel (free tier, no domain purchase) using
[Vercel Services](https://vercel.com/docs/services), the current pattern
for a Python backend + JavaScript frontend in one project. `vercel.json`
declares two services:

- `backend`, rooted at `backend/`: Vercel detects Django from
  `manage.py` and the `WSGI_APPLICATION` setting, installs the
  dependencies from `backend/requirements.txt` (kept in sync with the
  repo-root `requirements.txt`, which local development uses), and runs
  it as a Vercel Function with `maxDuration` 60 seconds. It receives
  all `/api/*` requests, with the original path intact.
- `frontend`, rooted at `frontend/`: Vite build (`npm run build`,
  output `dist`), with an SPA fallback rewrite to `/index.html`. It
  receives every other request.

Top-level rewrites in `vercel.json` route `/api/(.*)` to the backend
service and everything else to the frontend service. Deploy by linking
this repo to a Vercel project (or `vercel deploy` from the repo root);
no environment variables are required. The live URL is added to the
assessment submission once deployed.

Note: an earlier single-function layout (`api/index.py` + rewrites to
`/api/index.py`) did not work on current Vercel — the project deployed
as a static site and `/api/*` fell through to `index.html`, so the API
returned HTML/405. The Services layout above replaced it; `api/index.py`
remains in the repo only as a documented, unused reference.

## Limitations (honest)

- **Fewer than 3 routes:** the OSRM public demo server returns only the
  alternatives that genuinely exist for a corridor (often 1–2; e.g.
  Dallas→Houston returns 1, Chicago→St. Louis returns 2). The app returns
  what exists and says so in a visible warning; it never fabricates
  routes. A paid routing API (e.g. Valhalla with costing options, or
  Mapbox Directions) would return more alternatives.
- **Hourly weather:** Open-Meteo values are hourly, so checkpoint weather
  is the nearest hour to the ETA, not minute-precise.
- **Forecast horizon:** Open-Meteo covers the next 16 days. Departures
  beyond that, or ETAs outside the returned hours, get no weather data
  rather than invented data.
- **Nominatim rate limit:** the usage policy asks for ≤1 request/second;
  geocoding is throttled accordingly, so a trip takes a few seconds.
- **Serverless cold starts:** on Vercel's free tier the first API call
  after idle can take several seconds (Django import + upstream calls).
- **Average-speed ETAs:** see "ETA model" above.

## Data sources and attribution

- Geocoding: Nominatim (OpenStreetMap data, © OpenStreetMap contributors, ODbL)
- Routing: OSRM public demo server (OpenStreetMap data)
- Weather: Open-Meteo forecast API
- Map tiles: OpenStreetMap via Leaflet

No API keys, no payment, no secrets in this repository.
