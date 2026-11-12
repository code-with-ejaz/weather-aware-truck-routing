# Loom walkthrough outline (5–10 minutes)

For Ejaz Ahmad — record this yourself in Loom, in your own voice, showing
the hosted app in the browser. Suggested total: about 7 minutes.

## 0:00–0:45 — Intro (face cam on, then switch to screen)
- Your name, the role (Remote FullStack Engineer, React + Django), and the
  brief in one sentence: a truck driver enters origin, destination,
  departure time and load weight, and the app recommends the safest route.
- Show the hosted app URL and the GitHub repo URL briefly.

## 0:45–2:00 — Demo 1: Dallas, TX → Houston, TX (default values)
- The form is pre-filled. Click "Find safest route".
- While it loads (a few seconds), say what happens: geocoding with
  Nominatim, routing with OSRM, hourly weather with Open-Meteo.
- Point out: the route on the map, the checkpoint markers coloured by
  risk, and the warning that OSRM returned only 1 route for this corridor
  — say honestly that no route was fabricated.
- Click a checkpoint marker: show ETA, wind, rain, snow, risk in the popup.
- Scroll to the route summary card and the checkpoint table.

## 2:00–3:30 — Demo 2: Chicago, IL → St. Louis, MO, 45,000 lb, every 10 miles
- Change the form: heavier load, 10-mile sampling. Submit.
- This corridor returns 2 routes. Show both route cards, the Recommended
  badge, and click the other card to switch the map/checkpoints.
- Explain the recommendation order in one breath: fewest No Travel miles,
  then Severe, then High, then lowest average risk, then shortest time.

## 3:30–4:45 — Heatmap + forecast slider
- Turn the heatmap on (it is on by default) and drag the 0–48h slider.
- Show the heatmap changing along the corridor and the forecast time label
  updating. Explain: each point's colour is the risk score at that
  forecast hour, using the same wind/rain/snow + load rules.
- Mention the load rules with one example: 45–54 mph wind with a load over
  30,000 lb escalates a checkpoint to No Travel.

## 4:45–6:00 — Code walkthrough (GitHub repo, brief)
- Show the repo structure: `frontend/` (React + Vite + Leaflet),
  `backend/routing/risk.py` (the risk tables and ranking — point at the
  boundary tests), `backend/routing/services.py` (Nominatim/OSRM/Open-Meteo
  clients), `backend/routing/tests.py`.
- Mention: 15 unit tests, all passing, covering every boundary of the
  risk tables and the ranking order.
- Mention the honest limitations in the README: OSRM alternatives, hourly
  weather resolution, average-speed ETAs.

## 6:00–7:00 — Close
- Recap: live app, GitHub repo, tests passing, no API keys or paid services.
- Thank the reviewer and say you are happy to walk through any part live.

## Recording tips
- Record at 1080p, browser window maximised, and zoom the page to 110% so
  the map labels are readable.
- Run Demo 1 once before recording so the first (cold-start) API call is
  already warm and the demo feels fast.
- Keep the tab with the hosted app open; do not show any passwords, email,
  or other tabs.
- If a demo call is slow, keep talking through what the app is doing —
  do not stop and restart the recording for a few seconds of loading.
