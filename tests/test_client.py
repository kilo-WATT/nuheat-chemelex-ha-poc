from datetime import datetime, timedelta, timezone
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from chemelex_nuheat import NuHeatAuthError, NuHeatClient, ScheduleMode, TokenSet
from chemelex_nuheat.client import API_BASE_URL, DISCOVERY_URL

DISCOVERY = {
    "authorization_endpoint": "https://identity.mynuheat.com/connect/authorize",
    "token_endpoint": "https://identity.mynuheat.com/connect/token",
}

THERMOSTAT = {
    "serialNumber": "ABC123",
    "name": "Bathroom",
    "currentTemperature": 2150,
    "online": True,
    "isHeating": True,
    "setPointTemperature": 2300,
    "holdUntil": "2026-07-08T01:00:00Z",
    "mode": 2,
    "errorState": None,
}


def make_client(handler, *, tokens=None, callback=None):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = NuHeatClient(
        "issued-client-id",
        "http://127.0.0.1:8765/callback",
        tokens=tokens,
        http_client=http,
        token_update_callback=callback,
    )
    return client, http


@pytest.mark.asyncio
async def test_authorization_code_with_pkce_and_exchange():
    requests = []

    def handler(request):
        requests.append(request)
        if str(request.url) == DISCOVERY_URL:
            return httpx.Response(200, json=DISCOVERY)
        form = parse_qs(request.content.decode())
        assert form["grant_type"] == ["authorization_code"]
        assert form["code"] == ["the-code"]
        assert form["code_verifier"][0]
        assert "client_secret" not in form
        return httpx.Response(
            200,
            json={
                "access_token": "access-1",
                "refresh_token": "refresh-1",
                "expires_in": 3600,
            },
        )

    client, http = make_client(handler)
    url = await client.authorization_url()
    query = parse_qs(urlparse(url).query)
    assert query["scope"] == ["openid openapi offline_access"]
    assert query["code_challenge_method"] == ["S256"]
    tokens = await client.authenticate(authorization_code="the-code", state=query["state"][0])
    assert tokens.access_token == "access-1"
    assert tokens.refresh_token == "refresh-1"
    await http.aclose()


@pytest.mark.asyncio
async def test_authorization_code_rejects_missing_state():
    def handler(request):
        assert str(request.url) == DISCOVERY_URL
        return httpx.Response(200, json=DISCOVERY)

    client, http = make_client(handler)
    await client.authorization_url()
    with pytest.raises(NuHeatAuthError, match="state mismatch"):
        await client.authenticate(authorization_code="the-code")
    await http.aclose()


@pytest.mark.asyncio
async def test_refresh_rotates_token_and_lists_thermostats():
    saved = []
    expired = TokenSet(
        "expired",
        "refresh-old",
        datetime.now(timezone.utc) - timedelta(seconds=1),
    )

    def handler(request):
        if str(request.url) == DISCOVERY_URL:
            return httpx.Response(200, json=DISCOVERY)
        if request.url.path == "/connect/token":
            form = parse_qs(request.content.decode())
            assert form["refresh_token"] == ["refresh-old"]
            return httpx.Response(
                200,
                json={
                    "access_token": "fresh",
                    "refresh_token": "refresh-new",
                    "expires_in": 3600,
                },
            )
        assert request.headers["Authorization"] == "Bearer fresh"
        return httpx.Response(200, json=[THERMOSTAT])

    client, http = make_client(handler, tokens=expired, callback=saved.append)
    thermostats = await client.list_thermostats()
    assert thermostats[0].room == "Bathroom"
    assert thermostats[0].current_temperature == 21.5
    assert thermostats[0].target_temperature == 23.0
    assert thermostats[0].heating is True
    assert thermostats[0].min_temperature is None
    assert saved[0].refresh_token == "refresh-new"
    await http.aclose()


@pytest.mark.asyncio
async def test_401_refreshes_once_and_retries():
    api_calls = 0
    tokens = TokenSet("stale", "refresh", datetime.now(timezone.utc) + timedelta(hours=1))

    def handler(request):
        nonlocal api_calls
        if str(request.url) == DISCOVERY_URL:
            return httpx.Response(200, json=DISCOVERY)
        if request.url.path == "/connect/token":
            return httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})
        api_calls += 1
        if api_calls == 1:
            return httpx.Response(401)
        assert request.headers["Authorization"] == "Bearer fresh"
        return httpx.Response(200, json=THERMOSTAT)

    client, http = make_client(handler, tokens=tokens)
    thermostat = await client.get_thermostat("ABC123")
    assert thermostat.online is True
    assert api_calls == 2
    await http.aclose()


@pytest.mark.asyncio
async def test_set_target_temperature_uses_manual_mode_then_refreshes():
    calls = []
    tokens = TokenSet("valid", expires_at=datetime.now(timezone.utc) + timedelta(hours=1))

    def handler(request):
        calls.append(request)
        if request.method == "PUT":
            assert request.url == f"{API_BASE_URL}/api/v2/Mode/Manual"
            assert json.loads(request.content) == {
                "serialNumber": "ABC123",
                "temperature": 2250,
                "temperatureType": 0,
            }
            return httpx.Response(204)
        return httpx.Response(200, json=THERMOSTAT)

    client, http = make_client(handler, tokens=tokens)
    result = await client.set_target_temperature("ABC123", 22.5)
    assert result.serial_number == "ABC123"
    assert [request.method for request in calls] == ["PUT", "GET"]
    await http.aclose()


@pytest.mark.asyncio
async def test_auto_and_hold_payloads():
    payloads = []
    tokens = TokenSet("valid", expires_at=datetime.now(timezone.utc) + timedelta(hours=1))

    def handler(request):
        payloads.append((request.url.path, json.loads(request.content)))
        return httpx.Response(204)

    client, http = make_client(handler, tokens=tokens)
    await client.set_schedule_mode("ABC123", ScheduleMode.AUTO)
    await client.set_schedule_mode(
        "ABC123",
        ScheduleMode.HOLD,
        temperature=24,
        hold_until=datetime(2026, 7, 8, 1, tzinfo=timezone.utc),
    )
    assert payloads == [
        ("/api/v2/Mode/Auto", {"serialNumber": "ABC123"}),
        (
            "/api/v2/Mode/Hold",
            {
                "serialNumber": "ABC123",
                "temperature": 2400,
                "temperatureType": 0,
                "holdUntil": "2026-07-08T01:00:00Z",
            },
        ),
    ]
    await http.aclose()
