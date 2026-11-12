"""Weather risk classification and route recommendation.

Implements EXACTLY the rules from the Spotter assessment brief
(fs-assessment-spotter.pdf):

    Wind (mph):  <25 Low | 25-34 Moderate | 35-44 High | 45-54 Severe | >=55 No Travel
    Rain (in/hr): <0.10 Low | 0.10-0.25 Moderate | 0.25-0.50 High | 0.50-1.00 Severe | >1.00 No Travel
    Snow (in/hr): <0.5 Low | 0.5-1.0 Moderate | 1.0-2.0 High | 2.0-3.0 Severe | >3.0 No Travel

Boundary convention: the brief writes ranges such as "25-34" and "35-44".
We treat each band as half-open [lower, next-lower), except the top band of
rain/snow, which is closed at 1.00 / 3.0 because the brief says No Travel is
strictly ">1.00" / ">3.0". So e.g. wind 34.9 is Moderate, 35.0 is High;
rain 1.00 is Severe, 1.01 is No Travel. This is documented here and in the
README so the choice is explicit, not hidden.

A checkpoint's risk is the worst (highest) of its wind/rain/snow risks,
then the load rules escalate it:

    - wind >= 55 mph            -> No Travel for any load
    - wind 45-54 mph + load > 30,000 lb -> No Travel
    - wind 35-44 mph + load > 40,000 lb -> at least Severe

Route recommendation order from the brief:
    1. fewest Severe miles
    2. fewest High miles
    3. lowest average risk
    4. shortest travel time

NOTE ON NO TRAVEL MILES: the brief's ranking does not explicitly name
No Travel miles. We count no_travel_miles separately and rank it FIRST
(before Severe miles), because a No Travel stretch is strictly worse than
a Severe stretch. This is an explicit, documented extension of the brief's
order, not a silent change: no_travel_miles is reported separately in every
route summary so a reviewer can re-rank without it if they prefer.
"""

from __future__ import annotations

LOW = "low"
MODERATE = "moderate"
HIGH = "high"
SEVERE = "severe"
NO_TRAVEL = "no_travel"

RISK_ORDER = [LOW, MODERATE, HIGH, SEVERE, NO_TRAVEL]
RISK_SCORE = {LOW: 0, MODERATE: 1, HIGH: 2, SEVERE: 3, NO_TRAVEL: 4}


def classify_wind(wind_mph: float) -> str:
    """Classify wind speed (mph) per the brief's table."""
    if wind_mph >= 55:
        return NO_TRAVEL
    if wind_mph >= 45:
        return SEVERE
    if wind_mph >= 35:
        return HIGH
    if wind_mph >= 25:
        return MODERATE
    return LOW


def classify_rain(rain_in_hr: float) -> str:
    """Classify rain rate (inches/hour) per the brief's table."""
    if rain_in_hr > 1.00:
        return NO_TRAVEL
    if rain_in_hr >= 0.50:
        return SEVERE
    if rain_in_hr >= 0.25:
        return HIGH
    if rain_in_hr >= 0.10:
        return MODERATE
    return LOW


def classify_snow(snow_in_hr: float) -> str:
    """Classify snowfall rate (inches/hour) per the brief's table."""
    if snow_in_hr > 3.0:
        return NO_TRAVEL
    if snow_in_hr >= 2.0:
        return SEVERE
    if snow_in_hr >= 1.0:
        return HIGH
    if snow_in_hr >= 0.5:
        return MODERATE
    return LOW


def checkpoint_risk(
    wind_mph: float, rain_in_hr: float, snow_in_hr: float, load_weight_lb: float
) -> str:
    """Worst of wind/rain/snow risk, escalated by the load rules.

    Load rules (from the brief):
    - wind >= 55 mph -> No Travel for any load (already the wind result).
    - wind 45-54 mph and load > 30,000 lb -> No Travel.
    - wind 35-44 mph and load > 40,000 lb -> at least Severe.
    """
    worst = max(
        (classify_wind(wind_mph), classify_rain(rain_in_hr), classify_snow(snow_in_hr)),
        key=lambda level: RISK_SCORE[level],
    )
    if 45 <= wind_mph < 55 and load_weight_lb > 30_000:
        return NO_TRAVEL
    if 35 <= wind_mph < 45 and load_weight_lb > 40_000:
        if RISK_SCORE[worst] < RISK_SCORE[SEVERE]:
            return SEVERE
    return worst


def risk_score(level: str) -> int:
    return RISK_SCORE[level]


def summarize_route(checkpoints: list[dict]) -> dict:
    """Aggregate per-risk-level miles and average risk for one route.

    Each checkpoint dict must carry ``risk`` and ``segment_miles``: the
    miles of road that checkpoint represents (distance to the next
    checkpoint, or to the destination for the last one). Miles are
    attributed to the checkpoint at the START of each segment, which is
    the honest, simple model: weather sampled at a point describes the
    road ahead until the next sample.
    """
    miles = {level: 0.0 for level in RISK_ORDER}
    weighted = 0.0
    total = 0.0
    for cp in checkpoints:
        seg = float(cp.get("segment_miles", 0.0))
        level = cp["risk"]
        miles[level] += seg
        weighted += RISK_SCORE[level] * seg
        total += seg
    return {
        "low_miles": round(miles[LOW], 2),
        "moderate_miles": round(miles[MODERATE], 2),
        "high_miles": round(miles[HIGH], 2),
        "severe_miles": round(miles[SEVERE], 2),
        "no_travel_miles": round(miles[NO_TRAVEL], 2),
        "avg_risk_score": round(weighted / total, 3) if total > 0 else 0.0,
        "total_miles": round(total, 2),
    }


def recommendation_key(route_summary: dict, duration_seconds: float) -> tuple:
    """Sort key implementing the brief's recommendation order.

    (no_travel_miles, severe_miles, high_miles, avg_risk_score, duration).
    Lower is better on every component. No Travel miles first is the
    documented extension described in the module docstring.
    """
    return (
        route_summary["no_travel_miles"],
        route_summary["severe_miles"],
        route_summary["high_miles"],
        route_summary["avg_risk_score"],
        duration_seconds,
    )


def recommend_route(routes: list[dict]) -> int:
    """Return the index of the recommended route, per the ranking rules.

    Each route dict must carry ``summary`` (from summarize_route) and
    ``duration_seconds``.
    """
    if not routes:
        raise ValueError("recommend_route needs at least one route")
    best = min(
        range(len(routes)),
        key=lambda i: recommendation_key(routes[i]["summary"], routes[i]["duration_seconds"]),
    )
    return best


def recommendation_reason(winner: dict, others: list[dict]) -> str:
    """Plain-language explanation of why the winner was recommended."""
    s = winner["summary"]
    parts = []
    if s["no_travel_miles"] == 0 and any(o["summary"]["no_travel_miles"] > 0 for o in others):
        parts.append("it is the only route with no No Travel miles")
    elif s["no_travel_miles"] > 0:
        parts.append(f"it has the fewest No Travel miles ({s['no_travel_miles']:.1f} mi)")
    if s["severe_miles"] == 0:
        parts.append("no Severe miles")
    else:
        parts.append(f"fewest Severe miles ({s['severe_miles']:.1f} mi)")
    parts.append(f"average risk {s['avg_risk_score']:.2f}")
    return "Recommended: " + ", ".join(parts) + "."
