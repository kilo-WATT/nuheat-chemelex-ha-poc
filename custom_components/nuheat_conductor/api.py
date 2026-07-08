"""Small aiohttp client for the documented NuHeat OpenAPI v2."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from http import HTTPStatus
from typing import Any
from urllib.parse import quote

from aiohttp import ClientError, ClientResponse, ClientSession

from .const import API_BASE_URL


class NuHeatApiError(RuntimeError):
    """The cloud API request failed or returned invalid data."""


class NuHeatAuthError(NuHeatApiError):
    """The cloud rejected the current authorization."""


class ScheduleMode(StrEnum):
    """Documented OpenAPI v2 mode endpoints."""

    AUTO = "auto"
    HOLD = "hold"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class Account:
    """NuHeat account metadata."""

    username: str
    temperature_scale: str | None = None
    language: str | None = None


@dataclass(frozen=True, slots=True)
class Thermostat:
    """Normalized thermostat data; temperatures are degrees Celsius."""

    serial_number: str
    name: str | None
    current_temperature: float
    target_temperature: float
    heating: bool
    online: bool
    mode: int
    hold_until: datetime | None = None
    error_state: str | None = None
    min_temperature: float | None = None
    max_temperature: float | None = None


AccessTokenProvider = Callable[[bool], Awaitable[str]]


class NuHeatApi:
    """Async NuHeat API using a Home Assistant-owned aiohttp session."""

    def __init__(
        self,
        session: ClientSession,
        access_token_provider: AccessTokenProvider,
    ) -> None:
        self._session = session
        self._access_token_provider = access_token_provider

    async def get_account(self) -> Account:
        payload = await self._request_json("GET", "/api/v2/Account")
        username = payload.get("userName")
        if not isinstance(username, str) or not username.strip():
            raise NuHeatApiError("NuHeat account response did not include a username")
        return Account(
            username=username.strip(),
            temperature_scale=payload.get("temperatureScale"),
            language=payload.get("language"),
        )

    async def list_thermostats(self) -> list[Thermostat]:
        payload = await self._request_json("GET", "/api/v2/Thermostat")
        if not isinstance(payload, list):
            raise NuHeatApiError("NuHeat thermostat response was not a list")
        return [self._parse_thermostat(item) for item in payload]

    async def get_thermostat(self, serial_number: str) -> Thermostat:
        serial = _serial_path(serial_number)
        payload = await self._request_json("GET", f"/api/v2/Thermostat/{serial}")
        return self._parse_thermostat(payload)

    async def set_target_temperature(
        self, serial_number: str, temperature: float
    ) -> Thermostat:
        """Set a target in Celsius using the v2 Manual endpoint."""
        await self.set_schedule_mode(
            serial_number, ScheduleMode.MANUAL, temperature=temperature
        )
        return await self.get_thermostat(serial_number)

    async def set_schedule_mode(
        self,
        serial_number: str,
        mode: ScheduleMode | str,
        *,
        temperature: float | None = None,
        hold_until: datetime | None = None,
        temperature_type: int = 0,
    ) -> Thermostat:
        """Set Auto, temporary Hold, or Manual and return refreshed state."""
        mode = ScheduleMode(mode)
        payload: dict[str, Any] = {"serialNumber": serial_number}
        if mode is not ScheduleMode.AUTO:
            if temperature is not None:
                payload["temperature"] = _celsius_to_api(temperature)
            payload["temperatureType"] = temperature_type
        if mode is ScheduleMode.HOLD and hold_until is not None:
            if hold_until.tzinfo is None:
                raise ValueError("hold_until must be timezone-aware")
            payload["holdUntil"] = (
                hold_until.astimezone(timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )
        await self._request("PUT", f"/api/v2/Mode/{mode.value.title()}", json=payload)
        return await self.get_thermostat(serial_number)

    async def _request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        response = await self._request(method, path, **kwargs)
        try:
            return await response.json()
        except (ClientError, ValueError, TypeError) as err:
            raise NuHeatApiError("NuHeat returned an invalid JSON response") from err

    async def _request(self, method: str, path: str, **kwargs: Any) -> ClientResponse:
        for attempt in range(2):
            force_refresh = attempt == 1
            try:
                token = await self._access_token_provider(force_refresh)
                response = await self._session.request(
                    method,
                    f"{API_BASE_URL}{path}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                    **kwargs,
                )
            except ClientError as err:
                raise NuHeatApiError("Unable to communicate with NuHeat") from err

            if response.status != HTTPStatus.UNAUTHORIZED or force_refresh:
                break
            response.release()

        if response.status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
            response.release()
            raise NuHeatAuthError("NuHeat authorization was rejected")
        if response.status >= HTTPStatus.BAD_REQUEST:
            status = response.status
            response.release()
            raise NuHeatApiError(f"NuHeat API request failed with HTTP {status}")
        return response

    @staticmethod
    def _parse_thermostat(data: Mapping[str, Any]) -> Thermostat:
        try:
            return Thermostat(
                serial_number=str(data["serialNumber"]),
                name=data.get("name"),
                current_temperature=_api_to_celsius(data["currentTemperature"]),
                target_temperature=_api_to_celsius(data["setPointTemperature"]),
                heating=bool(data["isHeating"]),
                online=bool(data["online"]),
                mode=int(data["mode"]),
                hold_until=_parse_datetime(data.get("holdUntil")),
                error_state=data.get("errorState"),
                min_temperature=_optional_temperature(data.get("minTemperature")),
                max_temperature=_optional_temperature(data.get("maxTemperature")),
            )
        except (KeyError, TypeError, ValueError) as err:
            raise NuHeatApiError("NuHeat returned invalid thermostat data") from err


def _celsius_to_api(value: float) -> int:
    return round(value * 100)


def _api_to_celsius(value: Any) -> float:
    return int(value) / 100.0


def _optional_temperature(value: Any) -> float | None:
    return None if value is None else _api_to_celsius(value)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if not isinstance(value, str):
        raise TypeError
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _serial_path(value: str) -> str:
    if not value or any(char in value for char in "/?#"):
        raise ValueError("invalid thermostat serial number")
    return quote(value, safe="")

