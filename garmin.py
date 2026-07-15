"""
title: Garmin Connect
author: Jens Kock
author_url: https://github.com/jenskock/owui-garmin
git_url: https://github.com/jenskock/owui-garmin.git
description: Ask your Garmin health and activity data in chat
required_open_webui_version: 0.6.0
requirements: garminconnect, curl_cffi
version: 0.1.0
licence: MIT
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

DEFAULT_TOKENSTORE_DOCKER = "/app/backend/data/garmin_tokens"
DEFAULT_TOKENSTORE_LOCAL = "~/.garminconnect"


class MfaRequired(Exception):
    """Raised when Garmin requires an MFA code before login can finish."""


def default_tokenstore_path() -> str:
    """Prefer OWUI Docker data volume; fall back to home directory."""
    docker_path = Path(DEFAULT_TOKENSTORE_DOCKER)
    if docker_path.parent.is_dir():
        return str(docker_path)
    return str(Path(DEFAULT_TOKENSTORE_LOCAL).expanduser())


def _today() -> str:
    return date.today().isoformat()


def _resolve_date(value: Optional[str]) -> str:
    if not value or not value.strip():
        return _today()
    return value.strip()


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _error(message: str, **extra: Any) -> str:
    body: dict[str, Any] = {"error": message}
    body.update(extra)
    return _json(body)


def compact_daily_summary(raw: Optional[dict[str, Any]], day: str) -> dict[str, Any]:
    data = raw or {}
    return {
        "date": day,
        "steps": data.get("totalSteps"),
        "distance_meters": data.get("totalDistanceMeters"),
        "calories": data.get("totalKilocalories"),
        "active_calories": data.get("activeKilocalories"),
        "floors_ascended": data.get("floorsAscended"),
        "resting_heart_rate": data.get("restingHeartRate"),
        "min_heart_rate": data.get("minHeartRate"),
        "max_heart_rate": data.get("maxHeartRate"),
        "average_stress": data.get("averageStressLevel"),
        "max_stress": data.get("maxStressLevel"),
        "body_battery_charged": data.get("bodyBatteryChargedValue"),
        "body_battery_drained": data.get("bodyBatteryDrainedValue"),
        "intensity_minutes": data.get("moderateIntensityMinutes"),
        "vigorous_intensity_minutes": data.get("vigorousIntensityMinutes"),
    }


def compact_sleep(raw: Optional[dict[str, Any]], day: str) -> dict[str, Any]:
    data = raw or {}
    dto = data.get("dailySleepDTO") or {}
    scores = dto.get("sleepScores") or {}
    overall = scores.get("overall") or {}
    return {
        "date": day,
        "sleep_seconds": dto.get("sleepTimeSeconds"),
        "deep_seconds": dto.get("deepSleepSeconds"),
        "light_seconds": dto.get("lightSleepSeconds"),
        "rem_seconds": dto.get("remSleepSeconds"),
        "awake_seconds": dto.get("awakeSleepSeconds"),
        "sleep_score": overall.get("value"),
        "sleep_score_qualifier": overall.get("qualifierKey"),
        "avg_respiration": dto.get("averageRespirationValue"),
        "avg_spo2": dto.get("averageSpO2Value"),
    }


def compact_stress(raw: Optional[dict[str, Any]], day: str) -> dict[str, Any]:
    data = raw or {}
    return {
        "date": day,
        "average_stress": data.get("overallStressLevel")
        or data.get("avgStressLevel")
        or data.get("averageStressLevel"),
        "max_stress": data.get("maxStressLevel"),
        "rest_stress_duration": data.get("restStressDuration"),
        "low_stress_duration": data.get("lowStressDuration"),
        "medium_stress_duration": data.get("mediumStressDuration"),
        "high_stress_duration": data.get("highStressDuration"),
    }


def compact_hrv(raw: Optional[dict[str, Any]], day: str) -> dict[str, Any]:
    if not raw:
        return {"date": day, "available": False}
    summary = raw.get("hrvSummary") or raw
    baseline = summary.get("baseline") or {}
    return {
        "date": day,
        "available": True,
        "weekly_avg": summary.get("weeklyAvg"),
        "last_night_avg": summary.get("lastNightAvg"),
        "last_night_5_min_high": summary.get("lastNight5MinHigh"),
        "status": summary.get("status"),
        "baseline_low": baseline.get("balancedLow"),
        "baseline_upper": baseline.get("balancedUpper"),
    }


def compact_body_battery(
    raw: Optional[list[Any] | dict[str, Any]], day: str
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    if isinstance(raw, list):
        entries = [e for e in raw if isinstance(e, dict)]
    elif isinstance(raw, dict):
        nested = raw.get("bodyBatteryValuesArray") or raw.get("bodyBattery") or []
        if isinstance(nested, list) and nested and isinstance(nested[0], dict):
            entries = [e for e in nested if isinstance(e, dict)]
        else:
            entries = [raw]

    day_entries = [
        e
        for e in entries
        if str(e.get("date") or e.get("calendarDate") or day).startswith(day)
    ] or entries

    latest_value = None
    charged = None
    drained = None
    for entry in day_entries:
        charged = entry.get("charged") if entry.get("charged") is not None else charged
        drained = entry.get("drained") if entry.get("drained") is not None else drained
        values = entry.get("bodyBatteryValuesArray") or entry.get("values") or []
        if isinstance(values, list) and values:
            last = values[-1]
            if isinstance(last, (list, tuple)) and len(last) >= 2:
                latest_value = last[1]
            elif isinstance(last, dict):
                latest_value = last.get("value") or last.get("bodyBatteryLevel")
        if entry.get("bodyBatteryLevel") is not None:
            latest_value = entry.get("bodyBatteryLevel")

    return {
        "date": day,
        "latest_value": latest_value,
        "charged": charged,
        "drained": drained,
    }


def compact_heart_rate(raw: Optional[dict[str, Any]], day: str) -> dict[str, Any]:
    data = raw or {}
    return {
        "date": day,
        "resting_heart_rate": data.get("restingHeartRate"),
        "min_heart_rate": data.get("minHeartRate"),
        "max_heart_rate": data.get("maxHeartRate"),
        "last_seven_avg_rhr": data.get("lastSevenDaysAvgRestingHeartRate"),
    }


def compact_steps(raw: Optional[dict[str, Any]], day: str) -> dict[str, Any]:
    data = raw or {}
    return {
        "date": day,
        "steps": data.get("totalSteps"),
        "step_goal": data.get("dailyStepGoal"),
        "distance_meters": data.get("totalDistanceMeters"),
        "floors_ascended": data.get("floorsAscended"),
    }


def compact_training_readiness(
    raw: Optional[list[Any] | dict[str, Any]], day: str
) -> dict[str, Any]:
    if isinstance(raw, list) and raw:
        entry = raw[0] if isinstance(raw[0], dict) else {}
    elif isinstance(raw, dict):
        entry = raw
    else:
        entry = {}
    return {
        "date": entry.get("calendarDate") or day,
        "score": entry.get("score") or entry.get("trainingReadiness"),
        "level": entry.get("level") or entry.get("feedbackShort"),
        "feedback": entry.get("feedbackLong") or entry.get("feedback"),
        "sleep_score": entry.get("sleepScore"),
        "recovery_time": entry.get("recoveryTime"),
        "hrv_factor": entry.get("hrvFactor"),
        "acute_load": entry.get("acuteLoad"),
    }


def compact_training_status(
    raw: Optional[dict[str, Any]], day: str
) -> dict[str, Any]:
    data = raw or {}
    most_recent = data.get("mostRecentTrainingStatus") or data
    daily = (
        most_recent.get("latestTrainingStatusData")
        or most_recent.get("dailyTrainingStatusDTO")
        or most_recent
    )
    if isinstance(daily, dict) and len(daily) == 1:
        # Often keyed by device id
        only = next(iter(daily.values()))
        if isinstance(only, dict):
            daily = only

    load = daily.get("trainingLoadBalanceDTO") or daily.get("acuteTrainingLoadDTO") or {}
    vo2 = daily.get("mostRecentVO2Max") or data.get("mostRecentVO2Max") or {}
    if isinstance(vo2, dict) and "generic" in vo2:
        vo2 = vo2.get("generic") or vo2

    return {
        "date": daily.get("calendarDate") or day,
        "training_status": daily.get("trainingStatusFeedbackPhrase")
        or daily.get("trainingStatus")
        or daily.get("trainingStatusKey"),
        "load_phrase": load.get("trainingLoadPhrase") or load.get("loadPhrase"),
        "acute_load": load.get("dailyTrainingLoadAcute") or load.get("acuteLoad"),
        "chronic_load": load.get("dailyTrainingLoadChronic") or load.get("chronicLoad"),
        "acute_chronic_ratio": load.get("dailyAcuteChronicWorkloadRatio")
        or load.get("acwr"),
        "vo2_max": vo2.get("vo2MaxValue") if isinstance(vo2, dict) else vo2,
    }


def compact_activity(raw: Optional[dict[str, Any]]) -> dict[str, Any]:
    data = raw or {}
    activity_type = data.get("activityType") or {}
    if isinstance(activity_type, dict):
        type_key = activity_type.get("typeKey") or activity_type.get("typeId")
    else:
        type_key = activity_type
    return {
        "id": data.get("activityId") or data.get("activityIdSafe") or data.get("id"),
        "name": data.get("activityName") or data.get("name"),
        "type": type_key,
        "start_time": data.get("startTimeLocal") or data.get("startTimeGMT"),
        "duration_seconds": data.get("duration") or data.get("elapsedDuration"),
        "distance_meters": data.get("distance"),
        "calories": data.get("calories"),
        "avg_hr": data.get("averageHR") or data.get("avgHR"),
        "max_hr": data.get("maxHR"),
        "avg_speed": data.get("averageSpeed"),
        "elevation_gain": data.get("elevationGain"),
    }


def compact_activities(raw: Optional[list[Any]]) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    return [compact_activity(item) for item in raw if isinstance(item, dict)]


class Tools:
    class Valves(BaseModel):
        email: str = Field(default="", description="Garmin Connect account email")
        password: str = Field(default="", description="Garmin Connect account password")
        tokenstore: str = Field(
            default="",
            description=(
                "Directory for saved OAuth tokens. Leave empty to use "
                f"{DEFAULT_TOKENSTORE_DOCKER} in Docker or ~/.garminconnect locally."
            ),
        )

    def __init__(self) -> None:
        self.valves = self.Valves()
        self._client: Any = None
        self._mfa_pending: bool = False

    def _tokenstore(self) -> str:
        configured = (self.valves.tokenstore or "").strip()
        if configured:
            return str(Path(configured).expanduser())
        return default_tokenstore_path()

    def _credentials_ready(self) -> Optional[str]:
        if not (self.valves.email or "").strip():
            return "Set Valves.email to your Garmin Connect email."
        if not (self.valves.password or "").strip():
            return "Set Valves.password to your Garmin Connect password."
        return None

    async def _emit_status(
        self,
        event_emitter: Optional[Callable[..., Any]],
        description: str,
        done: bool = False,
    ) -> None:
        if not event_emitter:
            return
        try:
            await event_emitter(
                {
                    "type": "status",
                    "data": {"description": description, "done": done},
                }
            )
        except Exception:
            logger.debug("Failed to emit status event", exc_info=True)

    def _ensure_import(self) -> Any:
        try:
            from garminconnect import (  # type: ignore
                Garmin,
                GarminConnectAuthenticationError,
                GarminConnectConnectionError,
                GarminConnectTooManyRequestsError,
            )
        except ImportError as exc:
            raise RuntimeError(
                "garminconnect is not installed. Save the tool so Open WebUI "
                "can install requirements, or pip install garminconnect curl_cffi."
            ) from exc
        return (
            Garmin,
            GarminConnectAuthenticationError,
            GarminConnectConnectionError,
            GarminConnectTooManyRequestsError,
        )

    def _dump_tokens(self, client: Any) -> None:
        path = self._tokenstore()
        Path(path).mkdir(parents=True, exist_ok=True)
        try:
            client.client.dump(path)
        except Exception:
            logger.debug("Failed to dump Garmin tokens to %s", path, exc_info=True)

    def _login_with_tokens_or_credentials(
        self, *, mfa_code: Optional[str] = None
    ) -> tuple[Any, Optional[str]]:
        (
            Garmin,
            GarminConnectAuthenticationError,
            GarminConnectConnectionError,
            GarminConnectTooManyRequestsError,
        ) = self._ensure_import()

        tokenstore = self._tokenstore()
        Path(tokenstore).mkdir(parents=True, exist_ok=True)

        # Prefer existing tokens when not completing MFA.
        if not mfa_code:
            try:
                client = Garmin()
                result = client.login(tokenstore)
                status = result[0] if isinstance(result, tuple) else None
                if status != "needs_mfa":
                    self._client = client
                    self._mfa_pending = False
                    return client, None
            except Exception:
                logger.debug("Tokenstore login failed; will use credentials", exc_info=True)

        cred_error = self._credentials_ready()
        if cred_error:
            raise GarminConnectAuthenticationError(cred_error)

        email = self.valves.email.strip()
        password = self.valves.password

        if mfa_code:
            client = Garmin(
                email=email,
                password=password,
                prompt_mfa=lambda: mfa_code.strip(),
                return_on_mfa=False,
            )
            client.login(tokenstore)
            self._dump_tokens(client)
            self._client = client
            self._mfa_pending = False
            return client, None

        client = Garmin(
            email=email,
            password=password,
            return_on_mfa=True,
        )
        result = client.login(tokenstore)
        status = result[0] if isinstance(result, tuple) else None
        if status == "needs_mfa":
            self._client = client
            self._mfa_pending = True
            raise MfaRequired(
                "MFA required. Ask the user for their Garmin MFA code, then call "
                "submit_mfa with that code."
            )

        self._dump_tokens(client)
        self._client = client
        self._mfa_pending = False
        return client, None

    def _get_client(self) -> Any:
        (
            _Garmin,
            GarminConnectAuthenticationError,
            _Conn,
            _Rate,
        ) = self._ensure_import()

        if self._client is not None and not self._mfa_pending:
            return self._client

        try:
            client, _ = self._login_with_tokens_or_credentials()
            return client
        except MfaRequired:
            raise
        except GarminConnectAuthenticationError:
            raise
        except Exception as exc:
            raise GarminConnectAuthenticationError(str(exc)) from exc

    def _handle_exc(self, exc: Exception) -> str:
        name = type(exc).__name__
        message = str(exc)
        if isinstance(exc, MfaRequired):
            return _error(
                message,
                action="submit_mfa",
                hint="Call submit_mfa(code) with the code from email or authenticator app.",
            )
        if "Authentication" in name or "auth" in message.lower():
            return _error(
                message,
                action="login",
                hint="Call login(), or submit_mfa(code) if MFA is required.",
            )
        if "TooManyRequests" in name or "429" in message:
            return _error("Garmin rate limit exceeded. Wait a few minutes and retry.")
        return _error(message)

    async def login(
        self,
        __event_emitter__: Optional[Callable[..., Any]] = None,
    ) -> str:
        """
        Log in to Garmin Connect using Valves email/password and saved tokens.
        If MFA is required, returns instructions to call submit_mfa with the code.
        """
        await self._emit_status(__event_emitter__, "Logging in to Garmin Connect…")
        try:
            client, _ = self._login_with_tokens_or_credentials()
            await self._emit_status(__event_emitter__, "Logged in", done=True)
            return _json(
                {
                    "status": "logged_in",
                    "display_name": getattr(client, "display_name", None),
                    "full_name": getattr(client, "full_name", None),
                    "tokenstore": self._tokenstore(),
                }
            )
        except MfaRequired as exc:
            await self._emit_status(__event_emitter__, "MFA required", done=True)
            return self._handle_exc(exc)
        except Exception as exc:
            await self._emit_status(__event_emitter__, "Login failed", done=True)
            return self._handle_exc(exc)

    async def submit_mfa(
        self,
        code: str,
        __event_emitter__: Optional[Callable[..., Any]] = None,
    ) -> str:
        """
        Complete Garmin MFA using a one-time code from chat (email or authenticator app).
        :param code: The MFA verification code
        """
        if not code or not str(code).strip():
            return _error("code is required. Pass the MFA code from email or authenticator.")

        await self._emit_status(__event_emitter__, "Submitting MFA code…")
        (
            _Garmin,
            GarminConnectAuthenticationError,
            _Conn,
            _Rate,
        ) = self._ensure_import()

        try:
            if self._mfa_pending and self._client is not None:
                self._client.resume_login({}, str(code).strip())
                self._dump_tokens(self._client)
                # Load profile after resume (resume_login on Garmin already tries)
                try:
                    self._client._load_profile_and_settings()
                except Exception:
                    logger.debug("Profile load after MFA skipped", exc_info=True)
                self._mfa_pending = False
                client = self._client
            else:
                client, _ = self._login_with_tokens_or_credentials(
                    mfa_code=str(code).strip()
                )

            await self._emit_status(__event_emitter__, "MFA accepted", done=True)
            return _json(
                {
                    "status": "logged_in",
                    "display_name": getattr(client, "display_name", None),
                    "full_name": getattr(client, "full_name", None),
                    "tokenstore": self._tokenstore(),
                }
            )
        except Exception as exc:
            self._mfa_pending = False
            await self._emit_status(__event_emitter__, "MFA failed", done=True)
            return _error(
                f"MFA failed: {exc}",
                hint="Request a new code and call login() then submit_mfa(code) again.",
            )

    async def auth_status(self) -> str:
        """Check whether a Garmin session is available (tokens or in-memory client)."""
        tokenstore = self._tokenstore()
        path = Path(tokenstore)
        token_files = []
        if path.is_dir():
            token_files = [p.name for p in path.glob("*") if p.is_file()]
        elif path.is_file():
            token_files = [path.name]

        logged_in = False
        display_name = None
        try:
            client = self._get_client()
            logged_in = True
            display_name = getattr(client, "display_name", None)
        except MfaRequired:
            return _json(
                {
                    "logged_in": False,
                    "mfa_pending": True,
                    "tokenstore": tokenstore,
                    "token_files": token_files,
                    "action": "submit_mfa",
                }
            )
        except Exception as exc:
            return _json(
                {
                    "logged_in": False,
                    "mfa_pending": self._mfa_pending,
                    "tokenstore": tokenstore,
                    "token_files": token_files,
                    "detail": str(exc),
                }
            )

        return _json(
            {
                "logged_in": logged_in,
                "mfa_pending": False,
                "display_name": display_name,
                "tokenstore": tokenstore,
                "token_files": token_files,
            }
        )

    async def logout(self) -> str:
        """Clear the in-memory Garmin session and delete saved tokens."""
        tokenstore = self._tokenstore()
        try:
            (
                Garmin,
                _Auth,
                _Conn,
                _Rate,
            ) = self._ensure_import()
            client = self._client or Garmin()
            client.logout(tokenstore)
        except Exception:
            path = Path(tokenstore)
            if path.is_dir():
                for child in path.iterdir():
                    if child.is_file():
                        child.unlink(missing_ok=True)
            elif path.exists():
                path.unlink(missing_ok=True)

        self._client = None
        self._mfa_pending = False
        return _json({"status": "logged_out", "tokenstore": tokenstore})

    async def _with_client(
        self,
        __event_emitter__: Optional[Callable[..., Any]],
        status: str,
        fn: Callable[[Any], Any],
    ) -> str:
        await self._emit_status(__event_emitter__, status)
        try:
            client = self._get_client()
            result = fn(client)
            await self._emit_status(__event_emitter__, "Done", done=True)
            return _json(result)
        except Exception as exc:
            await self._emit_status(__event_emitter__, "Failed", done=True)
            return self._handle_exc(exc)

    async def get_daily_summary(
        self,
        date: Optional[str] = None,
        __event_emitter__: Optional[Callable[..., Any]] = None,
    ) -> str:
        """
        Get a compact daily health summary (steps, calories, HR, stress, body battery).
        :param date: Date as YYYY-MM-DD (defaults to today)
        """
        day = _resolve_date(date)

        def _run(client: Any) -> dict[str, Any]:
            raw = client.get_user_summary(day)
            return compact_daily_summary(raw, day)

        return await self._with_client(
            __event_emitter__, f"Fetching daily summary for {day}…", _run
        )

    async def get_sleep(
        self,
        date: Optional[str] = None,
        __event_emitter__: Optional[Callable[..., Any]] = None,
    ) -> str:
        """
        Get sleep duration, stages, and sleep score for a date.
        :param date: Date as YYYY-MM-DD (defaults to today)
        """
        day = _resolve_date(date)

        def _run(client: Any) -> dict[str, Any]:
            raw = client.get_sleep_data(day)
            return compact_sleep(raw, day)

        return await self._with_client(
            __event_emitter__, f"Fetching sleep for {day}…", _run
        )

    async def get_stress(
        self,
        date: Optional[str] = None,
        __event_emitter__: Optional[Callable[..., Any]] = None,
    ) -> str:
        """
        Get stress levels for a date.
        :param date: Date as YYYY-MM-DD (defaults to today)
        """
        day = _resolve_date(date)

        def _run(client: Any) -> dict[str, Any]:
            raw = client.get_stress_data(day)
            compact = compact_stress(raw if isinstance(raw, dict) else {}, day)
            # Fill duration buckets from daily summary when missing
            if compact.get("average_stress") is None or compact.get(
                "high_stress_duration"
            ) is None:
                summary = client.get_user_summary(day) or {}
                compact.setdefault("average_stress", summary.get("averageStressLevel"))
                compact.setdefault("max_stress", summary.get("maxStressLevel"))
                for key, src in (
                    ("rest_stress_duration", "restStressDuration"),
                    ("low_stress_duration", "lowStressDuration"),
                    ("medium_stress_duration", "mediumStressDuration"),
                    ("high_stress_duration", "highStressDuration"),
                ):
                    if compact.get(key) is None:
                        compact[key] = summary.get(src)
            return compact

        return await self._with_client(
            __event_emitter__, f"Fetching stress for {day}…", _run
        )

    async def get_hrv(
        self,
        date: Optional[str] = None,
        __event_emitter__: Optional[Callable[..., Any]] = None,
    ) -> str:
        """
        Get heart-rate variability (HRV) for a date.
        :param date: Date as YYYY-MM-DD (defaults to today)
        """
        day = _resolve_date(date)

        def _run(client: Any) -> dict[str, Any]:
            raw = client.get_hrv_data(day)
            return compact_hrv(raw if isinstance(raw, dict) else None, day)

        return await self._with_client(
            __event_emitter__, f"Fetching HRV for {day}…", _run
        )

    async def get_body_battery(
        self,
        date: Optional[str] = None,
        __event_emitter__: Optional[Callable[..., Any]] = None,
    ) -> str:
        """
        Get Body Battery charged/drained values for a date.
        :param date: Date as YYYY-MM-DD (defaults to today)
        """
        day = _resolve_date(date)

        def _run(client: Any) -> dict[str, Any]:
            raw = client.get_body_battery(day, day)
            compact = compact_body_battery(raw, day)
            if compact.get("charged") is None and compact.get("drained") is None:
                summary = client.get_user_summary(day) or {}
                compact["charged"] = summary.get("bodyBatteryChargedValue")
                compact["drained"] = summary.get("bodyBatteryDrainedValue")
            return compact

        return await self._with_client(
            __event_emitter__, f"Fetching body battery for {day}…", _run
        )

    async def get_heart_rate(
        self,
        date: Optional[str] = None,
        __event_emitter__: Optional[Callable[..., Any]] = None,
    ) -> str:
        """
        Get resting/min/max heart rate for a date (no full time series).
        :param date: Date as YYYY-MM-DD (defaults to today)
        """
        day = _resolve_date(date)

        def _run(client: Any) -> dict[str, Any]:
            raw = client.get_heart_rates(day)
            return compact_heart_rate(raw if isinstance(raw, dict) else {}, day)

        return await self._with_client(
            __event_emitter__, f"Fetching heart rate for {day}…", _run
        )

    async def get_steps(
        self,
        date: Optional[str] = None,
        __event_emitter__: Optional[Callable[..., Any]] = None,
    ) -> str:
        """
        Get steps and distance for a date.
        :param date: Date as YYYY-MM-DD (defaults to today)
        """
        day = _resolve_date(date)

        def _run(client: Any) -> dict[str, Any]:
            raw = client.get_user_summary(day)
            return compact_steps(raw if isinstance(raw, dict) else {}, day)

        return await self._with_client(
            __event_emitter__, f"Fetching steps for {day}…", _run
        )

    async def get_training_readiness(
        self,
        date: Optional[str] = None,
        __event_emitter__: Optional[Callable[..., Any]] = None,
    ) -> str:
        """
        Get training readiness score and level for a date.
        :param date: Date as YYYY-MM-DD (defaults to today)
        """
        day = _resolve_date(date)

        def _run(client: Any) -> dict[str, Any]:
            raw = client.get_training_readiness(day)
            return compact_training_readiness(raw, day)

        return await self._with_client(
            __event_emitter__, f"Fetching training readiness for {day}…", _run
        )

    async def get_training_status(
        self,
        date: Optional[str] = None,
        __event_emitter__: Optional[Callable[..., Any]] = None,
    ) -> str:
        """
        Get training status / load and VO2 max for a date.
        :param date: Date as YYYY-MM-DD (defaults to today)
        """
        day = _resolve_date(date)

        def _run(client: Any) -> dict[str, Any]:
            raw = client.get_training_status(day)
            return compact_training_status(raw if isinstance(raw, dict) else {}, day)

        return await self._with_client(
            __event_emitter__, f"Fetching training status for {day}…", _run
        )

    async def list_recent_activities(
        self,
        limit: int = 10,
        days: Optional[int] = None,
        __event_emitter__: Optional[Callable[..., Any]] = None,
    ) -> str:
        """
        List recent activities with compact summaries.
        :param limit: Max number of activities to return (default 10)
        :param days: If set, only include activities from the last N days
        """
        safe_limit = max(1, min(int(limit or 10), 50))

        def _run(client: Any) -> dict[str, Any]:
            if days is not None and int(days) > 0:
                end = date.today()
                start = end - timedelta(days=int(days))
                raw = client.get_activities_by_date(
                    start.isoformat(), end.isoformat()
                )
                activities = compact_activities(raw)[:safe_limit]
            else:
                raw = client.get_activities(0, safe_limit)
                activities = compact_activities(raw)
            return {"count": len(activities), "activities": activities}

        return await self._with_client(
            __event_emitter__, "Fetching recent activities…", _run
        )

    async def get_activity(
        self,
        activity_id: str,
        __event_emitter__: Optional[Callable[..., Any]] = None,
    ) -> str:
        """
        Get a compact summary for one activity by ID.
        :param activity_id: Garmin activity ID
        """
        if not activity_id or not str(activity_id).strip():
            return _error("activity_id is required")

        def _run(client: Any) -> dict[str, Any]:
            raw = client.get_activity(str(activity_id).strip())
            return compact_activity(raw if isinstance(raw, dict) else {})

        return await self._with_client(
            __event_emitter__, f"Fetching activity {activity_id}…", _run
        )
