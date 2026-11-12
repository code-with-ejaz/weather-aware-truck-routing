import { useEffect, useRef, useState } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import 'leaflet.heat'
// Vite does not resolve Leaflet's default marker image URLs from its CSS,
// so the origin/destination pins render as broken images unless the URLs
// are imported and set explicitly.
import markerIconUrl from 'leaflet/dist/images/marker-icon.png'
import markerIconRetinaUrl from 'leaflet/dist/images/marker-icon-2x.png'
import markerShadowUrl from 'leaflet/dist/images/marker-shadow.png'

L.Icon.Default.mergeOptions({
  iconUrl: markerIconUrl,
  iconRetinaUrl: markerIconRetinaUrl,
  shadowUrl: markerShadowUrl,
})

const RISK_COLORS = {
  low: '#22a06b',
  moderate: '#e5c100',
  high: '#f07d00',
  severe: '#d7263d',
  no_travel: '#5b0e1e',
}

const RISK_LABELS = {
  low: 'Low',
  moderate: 'Moderate',
  high: 'High',
  severe: 'Severe',
  no_travel: 'No Travel',
}

function formatEta(iso) {
  const d = new Date(iso)
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit', timeZoneName: 'short',
  })
}

function formatDuration(minutes) {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

export default function App() {
  const [origin, setOrigin] = useState('Dallas, TX')
  const [destination, setDestination] = useState('Houston, TX')
  const [departure, setDeparture] = useState(() => {
    const d = new Date(Date.now() + 60 * 60 * 1000)
    d.setMinutes(0, 0, 0)
    const pad = (n) => String(n).padStart(2, '0')
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:00`
  })
  const [loadWeight, setLoadWeight] = useState(30000)
  const [interval, setInterval] = useState(25)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [trip, setTrip] = useState(null)
  const [selectedRoute, setSelectedRoute] = useState(0)
  const [showHeatmap, setShowHeatmap] = useState(true)
  const [hourOffset, setHourOffset] = useState(0)

  const mapRef = useRef(null)
  const mapInstance = useRef(null)
  const layersRef = useRef(null)

  // Initialise the Leaflet map once.
  useEffect(() => {
    if (mapInstance.current) return
    const map = L.map(mapRef.current).setView([39.5, -98.35], 4)
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(map)
    mapInstance.current = map
    layersRef.current = L.layerGroup().addTo(map)
    return () => {
      map.remove()
      mapInstance.current = null
    }
  }, [])

  // Redraw routes, checkpoints and heatmap whenever the trip, selection,
  // heatmap toggle or forecast offset changes.
  useEffect(() => {
    const map = mapInstance.current
    const layers = layersRef.current
    if (!map || !layers || !trip) return
    layers.clearLayers()

    const bounds = []
    trip.routes.forEach((route) => {
      const isSelected = route.id === selectedRoute
      const isRecommended = route.id === trip.recommended_route_id
      const latlngs = route.geometry.coordinates.map(([lon, lat]) => [lat, lon])
      bounds.push(...latlngs)
      L.polyline(latlngs, {
        color: isRecommended ? '#1d6fd1' : '#8a8f98',
        weight: isSelected ? 6 : 4,
        opacity: isSelected ? 1 : 0.65,
      })
        .addTo(layers)
        .bindPopup(
          `Route ${route.id + 1}${isRecommended ? ' (Recommended)' : ''}<br/>` +
            `${route.distance_miles} mi &middot; ${formatDuration(route.duration_minutes)}`
        )

      if (isSelected) {
        route.checkpoints.forEach((cp) => {
          L.circleMarker([cp.lat, cp.lon], {
            radius: 7,
            color: '#fff',
            weight: 1.5,
            fillColor: RISK_COLORS[cp.risk],
            fillOpacity: 1,
          })
            .addTo(layers)
            .bindPopup(
              `<b>${RISK_LABELS[cp.risk]}</b> at ${cp.distance_miles} mi<br/>` +
                `ETA: ${formatEta(cp.eta)}<br/>` +
                `Wind: ${cp.wind_mph} mph &middot; Rain: ${cp.rain_in_hr} in/hr &middot; Snow: ${cp.snow_in_hr} in/hr`
            )
        })
      }
    })

    // Origin / destination markers.
    const o = trip.origin
    const d = trip.destination
    L.marker([o.lat, o.lon]).addTo(layers).bindPopup(`<b>Origin</b><br/>${o.display_name}`)
    L.marker([d.lat, d.lon]).addTo(layers).bindPopup(`<b>Destination</b><br/>${d.display_name}`)

    // Weather heatmap along the selected route's corridor, for the
    // chosen forecast offset. Intensity rises with risk score (0-4), with
    // a floor so the corridor stays faintly visible when all weather is
    // Low (a weight of 0 renders nothing in leaflet.heat) and the slider
    // visibly changes intensity as forecast risk rises.
    if (showHeatmap) {
      const route = trip.routes[selectedRoute]
      if (route && route.heatmap) {
        const points = route.heatmap.lats.map((lat, i) => {
          const score = route.heatmap.risk_grid[i][hourOffset] ?? 0
          return [lat, route.heatmap.lons[i], 0.18 + 0.82 * (score / 4)]
        })
        L.heatLayer(points, { radius: 28, blur: 20, maxZoom: 10, minOpacity: 0.25 }).addTo(layers)
      }
    }

    if (bounds.length) map.fitBounds(bounds, { padding: [40, 40] })
  }, [trip, selectedRoute, showHeatmap, hourOffset])

  async function onSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    setTrip(null)
    try {
      const departureDate = new Date(departure)
      if (Number.isNaN(departureDate.getTime())) {
        throw new Error('Please choose a valid departure date and time.')
      }
      const res = await fetch('/api/routes/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          origin,
          destination,
          departure_datetime: departureDate.toISOString(),
          load_weight_lb: Number(loadWeight),
          sample_interval_miles: Number(interval),
        }),
      })
      // Read the body as text first: on an error the server may return
      // HTML or an empty body, and parsing that as JSON would leak a
      // raw browser error ("Unexpected end of JSON input") to the user.
      const text = await res.text()
      let data = null
      if (text) {
        try {
          data = JSON.parse(text)
        } catch {
          data = null
        }
      }
      if (!res.ok) {
        throw new Error(
          data?.error ||
            `The routing service could not complete this request (HTTP ${res.status}). Please try again in a moment.`
        )
      }
      if (!data || !Array.isArray(data.routes)) {
        throw new Error('The routing service returned an unexpected response. Please try again in a moment.')
      }
      setTrip(data)
      setSelectedRoute(data.recommended_route_id)
      setHourOffset(0)
    } catch (err) {
      // fetch() throws a TypeError on network failures; show plain
      // language instead of the browser's raw error text.
      if (err instanceof TypeError) {
        setError('Could not reach the routing service. Check your connection and try again.')
      } else {
        setError(err.message || 'Something went wrong. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  const forecastTime = trip
    ? new Date(new Date(trip.departure_datetime).getTime() + hourOffset * 3600 * 1000)
    : null

  return (
    <div className="layout">
      <header>
        <h1>Weather-Aware Truck Routing</h1>
        <p>Pick the safest route for the load, the weather, and the clock.</p>
      </header>

      <form className="form" onSubmit={onSubmit}>
        <label>
          Origin
          <input value={origin} onChange={(e) => setOrigin(e.target.value)} required placeholder="Dallas, TX" />
        </label>
        <label>
          Destination
          <input value={destination} onChange={(e) => setDestination(e.target.value)} required placeholder="Houston, TX" />
        </label>
        <label>
          Departure date / time
          <input type="datetime-local" value={departure} onChange={(e) => setDeparture(e.target.value)} required />
        </label>
        <label>
          Load weight (lb)
          <input type="number" min="0" max="200000" step="500" value={loadWeight} onChange={(e) => setLoadWeight(e.target.value)} required />
        </label>
        <label>
          Weather sample interval
          <select value={interval} onChange={(e) => setInterval(e.target.value)}>
            <option value="10">Every 10 miles</option>
            <option value="25">Every 25 miles</option>
            <option value="50">Every 50 miles</option>
          </select>
        </label>
        <button type="submit" disabled={loading}>
          {loading ? 'Finding routes…' : 'Find safest route'}
        </button>
      </form>

      {error && <div className="error" role="alert">{error}</div>}
      {loading && <div className="loading">Geocoding, routing and fetching hourly weather… this usually takes a few seconds.</div>}

      {trip && trip.warnings.length > 0 && (
        <div className="warnings">
          {trip.warnings.map((w, i) => <p key={i}>⚠️ {w}</p>)}
        </div>
      )}

      <div className="map-wrap">
        <div ref={mapRef} className="map" />
        <div className="legend">
          <strong>Checkpoint risk</strong>
          {Object.entries(RISK_LABELS).map(([key, label]) => (
            <span key={key}><i style={{ background: RISK_COLORS[key] }} />{label}</span>
          ))}
        </div>
      </div>

      {trip && (
        <>
          <div className="heatmap-controls">
            <label>
              <input type="checkbox" checked={showHeatmap} onChange={(e) => setShowHeatmap(e.target.checked)} />
              Show weather heatmap along the corridor
            </label>
            <label className="slider-label">
              Forecast: +{hourOffset}h
              {forecastTime && <> ({formatEta(forecastTime.toISOString())})</>}
              <input
                type="range" min="0" max="48" step="1" value={hourOffset}
                onChange={(e) => setHourOffset(Number(e.target.value))}
                disabled={!showHeatmap}
              />
            </label>
          </div>

          <p className="recommendation">{trip.recommendation_reason}</p>
          <p className="meta">
            Departure {formatEta(trip.departure_datetime)} &middot; Load {Number(trip.load_weight_lb).toLocaleString()} lb &middot;
            Weather sampled every {trip.sample_interval_miles} miles at each checkpoint&apos;s estimated arrival time.
            Sources: {trip.data_sources.geocoding}, {trip.data_sources.routing}, {trip.data_sources.weather}.
          </p>

          <div className="cards">
            {trip.routes.map((route) => (
              <article
                key={route.id}
                className={`card ${route.id === selectedRoute ? 'selected' : ''}`}
                onClick={() => setSelectedRoute(route.id)}
              >
                <h2>
                  Route {route.id + 1}
                  {route.id === trip.recommended_route_id && <span className="badge">Recommended</span>}
                </h2>
                <p className="big">{route.distance_miles} mi &middot; {formatDuration(route.duration_minutes)}</p>
                <dl>
                  <div><dt>Average risk</dt><dd>{route.summary.avg_risk_score.toFixed(2)} / 4</dd></div>
                  <div><dt>No Travel miles</dt><dd>{route.summary.no_travel_miles}</dd></div>
                  <div><dt>Severe miles</dt><dd>{route.summary.severe_miles}</dd></div>
                  <div><dt>High miles</dt><dd>{route.summary.high_miles}</dd></div>
                  <div><dt>Moderate miles</dt><dd>{route.summary.moderate_miles}</dd></div>
                  <div><dt>Low miles</dt><dd>{route.summary.low_miles}</dd></div>
                  <div><dt>Checkpoints</dt><dd>{route.checkpoints.length}</dd></div>
                </dl>
              </article>
            ))}
          </div>

          <h2>Checkpoints — Route {selectedRoute + 1}</h2>
          <div className="table-wrap">
            <table>
              <thead>
                <tr><th>Distance</th><th>ETA</th><th>Wind</th><th>Rain</th><th>Snow</th><th>Risk</th></tr>
              </thead>
              <tbody>
                {trip.routes[selectedRoute].checkpoints.map((cp, i) => (
                  <tr key={i}>
                    <td>{cp.distance_miles} mi</td>
                    <td>{formatEta(cp.eta)}</td>
                    <td>{cp.wind_mph} mph</td>
                    <td>{cp.rain_in_hr} in/hr</td>
                    <td>{cp.snow_in_hr} in/hr</td>
                    <td><span className="risk-pill" style={{ background: RISK_COLORS[cp.risk] }}>{RISK_LABELS[cp.risk]}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}
