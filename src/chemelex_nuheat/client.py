"""Async client for the documented Chemelex NuHeat OpenAPI v2."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
import os
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx

DISCOVERY_URL = "https://identity.mynuheat.com/.well-known/openid-configuration"
API_BASE_URL = "https://api.mynuheat.com"
DEFAULT_SCOPES = ("openid", "openapi", "offline_access")
EXPIRY_SKEW = timedelta(seconds=30)


class NuHeatApiError(RuntimeError):
    """A NuHeat API request failed."""


class NuHeatAuthError(NuHeatApiError):
    """Authentication or token refresh failed."""


class ScheduleMode(str, Enum):
    """Documented v2 thermostat operating modes."""

    AUTO = "auto"
    HOLD = "hold"
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class TokenSet:
    """OAuth token set, including its calculated expiry time."""

    access_token: str
    refresh_token: str | None = None
    expires_at: datetime | None = None
    token_type: str = "Bearer"
    id_token: str | None = None

    @property
    def expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) + EXPIRY_SKEW >= self.expires_at


@dataclass(frozen=True, slots=True)
class Thermostat:
    """Normalized thermostat state; temperatures are degrees Celsius."""

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

    @property
    def room(self) -> str | None:
        """Home Assistant's legacy integration calls the name ``room``."""
        return self.name


TokenUpdateCallback = Callable[[TokenSet], Awaitable[None] | None]


class NuHeatClient:
    """OAuth2/OIDC-aware asynchronous NuHeat OpenAPI client.

    Initial login uses Authorization Code with PKCE. A client secret is sent
    only when one was issued by Chemelex for a confidential client. Password
    grant and private/mobile application credentials are deliberately absent.
    """

    def __init__(
        self,
        client_id: str,
        redirect_uri: str,
        *,
        client_secret: str | None = None,
        tokens: TokenSet | None = None,
        http_client: httpx.AsyncClient | None = None,
        token_update_callback: TokenUpdateCallback | None = None,
        min_temperature: float | None = None,
        max_temperature: float | None = None,
    ) -> None:
        if not client_id or not redirect_uri:
            raise ValueError("client_id and redirect_uri are required")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.tokens = tokens
        self._http = http_client or httpx.AsyncClient(timeout=20.0)
        self._owns_http = http_client is None
        self._token_update_callback = token_update_callback
        self._discovery: dict[str, Any] | None = None
        self._refresh_lock = asyncio.Lock()
        self._code_verifier: str | None = None
        self._state: str | None = None
        self._min_temperature = min_temperature
        self._max_temperature = max_temperature

    @classmethod
    def from_env(
        cls, *, http_client: httpx.AsyncClient | None = None
    ) -> NuHeatClient:
        """Build from environment variables, optionally loading local .env."""
        try:
            from dotenv import load_dotenv
        except ImportError:
            pass
        else:
            load_dotenv()

        refresh_token = os.getenv("NUHEAT_REFRESH_TOKEN") or None
        tokens = TokenSet(access_token="", refresh_token=refresh_token) if refresh_token else None
        return cls(
            os.environ["NUHEAT_CLIENT_ID"],
            os.environ["NUHEAT_REDIRECT_URI"],
            client_secret=os.getenv("NUHEAT_CLIENT_SECRET") or None,
            tokens=tokens,
            http_client=http_client,
        )

    async def __aenter__(self) -> NuHeatClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _get_discovery(self) -> Mapping[str, Any]:
        if self._discovery is None:
            response = await self._http.get(DISCOVERY_URL)
            self._raise_for_status(response, auth=True)
            self._discovery = response.json()
        return self._discovery

    async def authorization_url(self) -> str:
        """Create an OIDC authorization URL and retain PKCE/state locally."""
        discovery = await self._get_discovery()
        self._code_verifier = secrets.token_urlsafe(64)
        digest = hashlib.sha256(self._code_verifier.encode()).digest()
        challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        self._state = secrets.token_urlsafe(32)
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": self.redirect_uri,
                "response_type": "code",
                "scope": " ".join(DEFAULT_SCOPES),
                "state": self._state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{discovery['authorization_endpoint']}?{query}"

    async def authenticate(
        self, *, authorization_code: str | None = None, state: str | None = None
    ) -> TokenSet:
        """Exchange an authorization code, refresh, or validate current auth."""
        if authorization_code is not None:
            if not self._code_verifier:
                raise NuHeatAuthError("call authorization_url() before exchanging a code")
            if state is None or not secrets.compare_digest(state, self._state or ""):
                raise NuHeatAuthError("OIDC state mismatch")
            await self._exchange_token(
                {
                    "grant_type": "authorization_code",
                    "code": authorization_code,
                    "redirect_uri": self.redirect_uri,
                    "code_verifier": self._code_verifier,
                }
            )
        elif self.tokens and self.tokens.refresh_token and (
            not self.tokens.access_token or self.tokens.expired
        ):
            await self._refresh_access_token()
        elif not self.tokens or not self.tokens.access_token:
            raise NuHeatAuthError(
                "authorization required: call authorization_url(), then authenticate(code)"
            )
        return self.tokens

    async def _refresh_access_token(self) -> None:
        async with self._refresh_lock:
            if self.tokens and self.tokens.access_token and not self.tokens.expired:
                return
            if not self.tokens or not self.tokens.refresh_token:
                raise NuHeatAuthError("no refresh token available")
            old_refresh_token = self.tokens.refresh_token
            await self._exchange_token(
                {"grant_type": "refresh_token", "refresh_token": old_refresh_token},
                fallback_refresh_token=old_refresh_token,
            )

    async def _exchange_token(
        self, data: dict[str, str], *, fallback_refresh_token: str | None = None
    ) -> None:
        discovery = await self._get_discovery()
        data["client_id"] = self.client_id
        if self.client_secret:
            data["client_secret"] = self.client_secret
        response = await self._http.post(discovery["token_endpoint"], data=data)
        self._raise_for_status(response, auth=True)
        payload = response.json()
        now = datetime.now(timezone.utc)
        self.tokens = TokenSet(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token", fallback_refresh_token),
            expires_at=now + timedelta(seconds=int(payload.get("expires_in", 3600))),
            token_type=payload.get("token_type", "Bearer"),
            id_token=payload.get("id_token"),
        )
        if self._token_update_callback:
            result = self._token_update_callback(self.tokens)
            if result is not None:
                await result

    async def _access_token(self) -> str:
        await self.authenticate()
        assert self.tokens is not None
        return self.tokens.access_token

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        token = await self._access_token()
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = f"Bearer {token}"
        headers.setdefault("Accept", "application/json")
        response = await self._http.request(
            method, f"{API_BASE_URL}{path}", headers=headers, **kwargs
        )
        if response.status_code == 401 and self.tokens and self.tokens.refresh_token:
            self.tokens = replace(
                self.tokens, expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
            )
            await self._refresh_access_token()
            headers["Authorization"] = f"Bearer {self.tokens.access_token}"
            response = await self._http.request(
                method, f"{API_BASE_URL}{path}", headers=headers, **kwargs
            )
        self._raise_for_status(response)
        return response

    @staticmethod
    def _raise_for_status(response: httpx.Response, *, auth: bool = False) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            try:
                detail = json.dumps(response.json())
            except (ValueError, TypeError):
                detail = response.text
            error = f"NuHeat returned HTTP {response.status_code}: {detail}"
            raise (NuHeatAuthError(error) if auth else NuHeatApiError(error)) from exc

    async def list_thermostats(self) -> list[Thermostat]:
        response = await self._request("GET", "/api/v2/Thermostat")
        return [self._parse_thermostat(item) for item in response.json()]

    async def get_thermostat(self, serial_number: str) -> Thermostat:
        serial = _path_serial(serial_number)
        response = await self._request("GET", f"/api/v2/Thermostat/{serial}")
        return self._parse_thermostat(response.json())

    async def set_target_temperature(
        self, serial_number: str, temperature: float
    ) -> Thermostat:
        """Set a permanent manual target in degrees Celsius."""
        await self.set_schedule_mode(serial_number, ScheduleMode.MANUAL, temperature=temperature)
        return await self.get_thermostat(serial_number)

    async def set_schedule_mode(
        self,
        serial_number: str,
        mode: ScheduleMode | str,
        *,
        temperature: float | None = None,
        hold_until: datetime | None = None,
        temperature_type: int = 0,
    ) -> None:
        """Set Auto, temporary Hold, or Manual mode via documented v2 endpoints."""
        mode = ScheduleMode(mode)
        payload: dict[str, Any] = {"serialNumber": serial_number}
        if mode is not ScheduleMode.AUTO:
            if temperature is not None:
                payload["temperature"] = _celsius_to_api(temperature)
            payload["temperatureType"] = temperature_type
        if mode is ScheduleMode.HOLD and hold_until is not None:
            if hold_until.tzinfo is None:
                raise ValueError("hold_until must be timezone-aware")
            payload["holdUntil"] = hold_until.astimezone(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            )
        await self._request("PUT", f"/api/v2/Mode/{mode.value.title()}", json=payload)

    def _parse_thermostat(self, data: Mapping[str, Any]) -> Thermostat:
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
            min_temperature=_optional_api_temperature(data.get("minTemperature"), self._min_temperature),
            max_temperature=_optional_api_temperature(data.get("maxTemperature"), self._max_temperature),
        )


def _celsius_to_api(value: float) -> int:
    """OpenAPI temperature integers are hundredths of a degree Celsius."""
    return round(value * 100)


def _api_to_celsius(value: int) -> float:
    return int(value) / 100.0


def _optional_api_temperature(value: Any, fallback: float | None) -> float | None:
    return fallback if value is None else _api_to_celsius(value)


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _path_serial(value: str) -> str:
    if not value or any(char in value for char in "/?#"):
        raise ValueError("invalid serial number")
    return value
