"""Unit tests for the risk rules and recommendation ranking.

These test the brief's tables exactly, including every boundary value.
No network access: pure logic only.
"""

from django.test import SimpleTestCase

from .risk import (
    HIGH,
    LOW,
    MODERATE,
    NO_TRAVEL,
    SEVERE,
    checkpoint_risk,
    classify_rain,
    classify_snow,
    classify_wind,
    recommend_route,
    summarize_route,
)


class WindClassificationTests(SimpleTestCase):
    def test_boundaries(self):
        self.assertEqual(classify_wind(0), LOW)
        self.assertEqual(classify_wind(24.9), LOW)
        self.assertEqual(classify_wind(25), MODERATE)
        self.assertEqual(classify_wind(34.9), MODERATE)
        self.assertEqual(classify_wind(35), HIGH)
        self.assertEqual(classify_wind(44.9), HIGH)
        self.assertEqual(classify_wind(45), SEVERE)
        self.assertEqual(classify_wind(54.9), SEVERE)
        self.assertEqual(classify_wind(55), NO_TRAVEL)
        self.assertEqual(classify_wind(80), NO_TRAVEL)


class RainClassificationTests(SimpleTestCase):
    def test_boundaries(self):
        self.assertEqual(classify_rain(0), LOW)
        self.assertEqual(classify_rain(0.09), LOW)
        self.assertEqual(classify_rain(0.10), MODERATE)
        self.assertEqual(classify_rain(0.24), MODERATE)
        self.assertEqual(classify_rain(0.25), HIGH)
        self.assertEqual(classify_rain(0.49), HIGH)
        self.assertEqual(classify_rain(0.50), SEVERE)
        self.assertEqual(classify_rain(1.00), SEVERE)
        self.assertEqual(classify_rain(1.01), NO_TRAVEL)


class SnowClassificationTests(SimpleTestCase):
    def test_boundaries(self):
        self.assertEqual(classify_snow(0), LOW)
        self.assertEqual(classify_snow(0.49), LOW)
        self.assertEqual(classify_snow(0.5), MODERATE)
        self.assertEqual(classify_snow(0.99), MODERATE)
        self.assertEqual(classify_snow(1.0), HIGH)
        self.assertEqual(classify_snow(1.99), HIGH)
        self.assertEqual(classify_snow(2.0), SEVERE)
        self.assertEqual(classify_snow(3.0), SEVERE)
        self.assertEqual(classify_snow(3.01), NO_TRAVEL)


class CheckpointRiskTests(SimpleTestCase):
    def test_worst_of_three_wins(self):
        # Wind low, rain high, snow moderate -> high.
        self.assertEqual(checkpoint_risk(10, 0.30, 0.6, 0), HIGH)
        # Snow severe beats wind high.
        self.assertEqual(checkpoint_risk(40, 0, 2.5, 0), SEVERE)

    def test_wind_55_is_no_travel_any_load(self):
        self.assertEqual(checkpoint_risk(55, 0, 0, 0), NO_TRAVEL)
        self.assertEqual(checkpoint_risk(60, 0, 0, 50_000), NO_TRAVEL)

    def test_wind_45_54_over_30000_lb_is_no_travel(self):
        self.assertEqual(checkpoint_risk(50, 0, 0, 30_001), NO_TRAVEL)
        # Exactly 30,000 lb does NOT escalate ("more than 30,000").
        self.assertEqual(checkpoint_risk(50, 0, 0, 30_000), SEVERE)
        self.assertEqual(checkpoint_risk(50, 0, 0, 20_000), SEVERE)

    def test_wind_35_44_over_40000_lb_is_at_least_severe(self):
        self.assertEqual(checkpoint_risk(40, 0, 0, 40_001), SEVERE)
        # Exactly 40,000 lb does NOT escalate.
        self.assertEqual(checkpoint_risk(40, 0, 0, 40_000), HIGH)
        self.assertEqual(checkpoint_risk(40, 0, 0, 20_000), HIGH)
        # Escalation never downgrades an existing No Travel (heavy rain).
        self.assertEqual(checkpoint_risk(40, 1.5, 0, 45_000), NO_TRAVEL)

    def test_calm_weather_is_low(self):
        self.assertEqual(checkpoint_risk(5, 0, 0, 45_000), LOW)


class SummarizeRouteTests(SimpleTestCase):
    def test_miles_and_average(self):
        checkpoints = [
            {"risk": LOW, "segment_miles": 10},
            {"risk": HIGH, "segment_miles": 20},
            {"risk": SEVERE, "segment_miles": 10},
            {"risk": LOW, "segment_miles": 0},  # destination checkpoint
        ]
        summary = summarize_route(checkpoints)
        self.assertEqual(summary["low_miles"], 10)
        self.assertEqual(summary["high_miles"], 20)
        self.assertEqual(summary["severe_miles"], 10)
        self.assertEqual(summary["no_travel_miles"], 0)
        # (0*10 + 2*20 + 3*10) / 40 = 1.75
        self.assertEqual(summary["avg_risk_score"], 1.75)


class RecommendationTests(SimpleTestCase):
    def _route(self, no_travel, severe, high, avg, duration):
        return {
            "summary": {
                "no_travel_miles": no_travel,
                "severe_miles": severe,
                "high_miles": high,
                "avg_risk_score": avg,
            },
            "duration_seconds": duration,
        }

    def test_fewest_severe_miles_wins(self):
        routes = [self._route(0, 30, 0, 1.0, 100), self._route(0, 10, 50, 2.0, 200)]
        self.assertEqual(recommend_route(routes), 1)

    def test_no_travel_miles_ranked_first(self):
        # Route 0 has fewer severe miles but some No Travel miles; route 1 wins.
        routes = [self._route(5, 0, 0, 0.5, 100), self._route(0, 20, 0, 1.5, 200)]
        self.assertEqual(recommend_route(routes), 1)

    def test_high_miles_breaks_severe_tie(self):
        routes = [self._route(0, 10, 40, 1.0, 100), self._route(0, 10, 5, 2.0, 200)]
        self.assertEqual(recommend_route(routes), 1)

    def test_average_risk_breaks_miles_tie(self):
        routes = [self._route(0, 10, 10, 1.8, 100), self._route(0, 10, 10, 1.2, 200)]
        self.assertEqual(recommend_route(routes), 1)

    def test_shortest_time_breaks_final_tie(self):
        routes = [self._route(0, 10, 10, 1.5, 300), self._route(0, 10, 10, 1.5, 200)]
        self.assertEqual(recommend_route(routes), 1)

    def test_empty_raises(self):
        with self.assertRaises(ValueError):
            recommend_route([])
