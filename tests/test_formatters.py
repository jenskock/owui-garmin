#!/usr/bin/env python3
"""Unit tests for garmin.py compact formatters (no live Garmin calls)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from garmin import (  # noqa: E402
    Tools,
    compact_activities,
    compact_body_battery,
    compact_daily_summary,
    compact_heart_rate,
    compact_hrv,
    compact_sleep,
    compact_steps,
    compact_stress,
    compact_training_readiness,
    compact_training_status,
)


class FormatterTests(unittest.TestCase):
    def test_daily_summary(self) -> None:
        raw = {
            "totalSteps": 8000,
            "totalDistanceMeters": 6400,
            "totalKilocalories": 2200,
            "restingHeartRate": 52,
            "averageStressLevel": 25,
            "bodyBatteryChargedValue": 60,
            "bodyBatteryDrainedValue": 40,
        }
        out = compact_daily_summary(raw, "2026-07-15")
        self.assertEqual(out["steps"], 8000)
        self.assertEqual(out["resting_heart_rate"], 52)
        self.assertEqual(out["date"], "2026-07-15")

    def test_sleep(self) -> None:
        raw = {
            "dailySleepDTO": {
                "sleepTimeSeconds": 25200,
                "deepSleepSeconds": 3600,
                "lightSleepSeconds": 14400,
                "remSleepSeconds": 5400,
                "awakeSleepSeconds": 1800,
                "sleepScores": {"overall": {"value": 78, "qualifierKey": "GOOD"}},
            }
        }
        out = compact_sleep(raw, "2026-07-15")
        self.assertEqual(out["sleep_seconds"], 25200)
        self.assertEqual(out["sleep_score"], 78)

    def test_stress_and_hrv(self) -> None:
        stress = compact_stress(
            {"avgStressLevel": 30, "maxStressLevel": 80}, "2026-07-15"
        )
        self.assertEqual(stress["average_stress"], 30)
        hrv = compact_hrv(
            {
                "hrvSummary": {
                    "lastNightAvg": 45,
                    "status": "BALANCED",
                    "baseline": {"balancedLow": 30, "balancedUpper": 60},
                }
            },
            "2026-07-15",
        )
        self.assertTrue(hrv["available"])
        self.assertEqual(hrv["last_night_avg"], 45)

    def test_body_battery_from_summary_fields(self) -> None:
        out = compact_body_battery(
            [{"date": "2026-07-15", "charged": 55, "drained": 35}],
            "2026-07-15",
        )
        self.assertEqual(out["charged"], 55)
        self.assertEqual(out["drained"], 35)

    def test_heart_rate_and_steps(self) -> None:
        hr = compact_heart_rate(
            {"restingHeartRate": 50, "minHeartRate": 42, "maxHeartRate": 160},
            "2026-07-15",
        )
        self.assertEqual(hr["resting_heart_rate"], 50)
        steps = compact_steps(
            {"totalSteps": 9000, "totalDistanceMeters": 7000, "dailyStepGoal": 10000},
            "2026-07-15",
        )
        self.assertEqual(steps["steps"], 9000)
        self.assertEqual(steps["step_goal"], 10000)

    def test_training_readiness_list(self) -> None:
        out = compact_training_readiness(
            [{"calendarDate": "2026-07-15", "score": 72, "level": "MODERATE"}],
            "2026-07-15",
        )
        self.assertEqual(out["score"], 72)
        self.assertEqual(out["level"], "MODERATE")

    def test_training_status_nested(self) -> None:
        raw = {
            "mostRecentTrainingStatus": {
                "latestTrainingStatusData": {
                    "device1": {
                        "calendarDate": "2026-07-15",
                        "trainingStatusFeedbackPhrase": "PRODUCTIVE",
                        "acuteTrainingLoadDTO": {
                            "dailyTrainingLoadAcute": 200,
                            "dailyTrainingLoadChronic": 180,
                            "dailyAcuteChronicWorkloadRatio": 1.1,
                        },
                        "mostRecentVO2Max": {"generic": {"vo2MaxValue": 52}},
                    }
                }
            }
        }
        out = compact_training_status(raw, "2026-07-15")
        self.assertEqual(out["training_status"], "PRODUCTIVE")
        self.assertEqual(out["acute_load"], 200)
        self.assertEqual(out["vo2_max"], 52)

    def test_activities(self) -> None:
        raw = [
            {
                "activityId": 1,
                "activityName": "Morning Run",
                "activityType": {"typeKey": "running"},
                "startTimeLocal": "2026-07-15T07:00:00",
                "duration": 2400,
                "distance": 5000,
            }
        ]
        out = compact_activities(raw)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "Morning Run")
        self.assertEqual(out[0]["type"], "running")


class ToolSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_mfa_requires_code(self) -> None:
        tools = Tools()
        result = json.loads(await tools.submit_mfa(""))
        self.assertIn("error", result)

    async def test_get_activity_requires_id(self) -> None:
        tools = Tools()
        result = json.loads(await tools.get_activity(""))
        self.assertIn("error", result)

    async def test_login_without_credentials(self) -> None:
        tools = Tools()
        tools.valves.email = ""
        tools.valves.password = ""
        with tempfile.TemporaryDirectory() as tmp:
            tools.valves.tokenstore = tmp
            result = json.loads(await tools.login())
            self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
