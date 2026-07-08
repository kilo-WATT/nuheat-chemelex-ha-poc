"""Tests for the NuHeat Conductor custom integration."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import time
from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.components.application_credentials import ClientCredential
from homeassistant.components.climate.const import (
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntryState, SOURCE_USER
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.config_entry_oauth2_flow import AbstractOAuth2Implementation
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.nuheat_conductor import async_setup_entry
from custom_components.nuheat_conductor.application_credentials import (
    async_get_auth_implementation,
)
from custom_components.nuheat_conductor.api import (
    Account,
    NuHeatAuthError,
    ScheduleMode,
    Thermostat,
)
from custom_components.nuheat_conductor.climate import NuHeatClimateEntity
from custom_components.nuheat_conductor.config_flow import NuHeatConductorConfigFlow
from custom_components.nuheat_conductor.const import DOMAIN, MODE_AUTO, MODE_HOLD, MODE_MANUAL
from custom_components.nuheat_conductor.coordinator import NuHeatCoordinator
from custom_components.nuheat_conductor.oauth import NuHeatLocalOAuth2Implementation


def thermostat(*, mode: int = MODE_AUTO, heating: bool = True) -> Thermostat:
    return Thermostat(
        serial_number="ABC123",
        name="Bathroom",
        current_temperature=21.5,
        target_temperature=23.0,
        heating=heating,
        online=True,
        mode=mode,
        hold_until=datetime(2026, 7, 8, 1, tzinfo=timezone.utc),
    )


class FakeOAuthImplementation(AbstractOAuth2Implementation):
    """Minimal OAuth provider used by config-flow and refresh tests."""

    def __init__(self, *, token: dict | None = None) -> None:
        self._token = token or {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
        }

    @property
    def name(self) -> str:
        return "Test credentials"

    @property
    def domain(self) -> str:
        return "test"

    async def async_generate_authorize_url(self, flow_id: str) -> str:
        return "https://identity.example/authorize"

    async def async_resolve_external_data(self, external_data: object) -> dict:
        return dict(self._token)

    async def _async_refresh_token(self, token: dict) -> dict:
        return {
            **token,
            "access_token": "rotated-access",
            "refresh_token": "rotated-refresh",
            "expires_in": 3600,
        }


@pytest.mark.asyncio
async def test_local_application_credentials_path(hass):
    """Local credentials create the development PKCE implementation."""
    implementation = await async_get_auth_implementation(
        hass,
        "local-test",
        ClientCredential("issued-client-id", "issued-client-secret"),
    )

    assert isinstance(implementation, NuHeatLocalOAuth2Implementation)
    assert implementation.domain == "local-test"
    assert implementation.client_id == "issued-client-id"
    assert implementation.extra_authorize_data["scope"] == (
        "openid openapi offline_access"
    )
    assert implementation.extra_authorize_data["code_challenge_method"] == "S256"
    assert implementation.extra_token_resolve_data["code_verifier"]


@pytest.mark.asyncio
async def test_missing_credentials_has_helpful_error(hass):
    """Development builds explain how the missing provider will be solved."""
    flow = NuHeatConductorConfigFlow()
    flow.hass = hass
    flow.context = {"source": SOURCE_USER}

    with patch(
        "homeassistant.helpers.config_entry_oauth2_flow.async_get_implementations",
        AsyncMock(return_value={}),
    ):
        result = await flow.async_step_user()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "missing_oauth_credentials"
    strings = json.loads(
        Path("custom_components/nuheat_conductor/strings.json").read_text()
    )
    assert strings["config"]["abort"]["missing_oauth_credentials"] == (
        "OAuth application credentials are required for this development build. "
        "A future official Home Assistant integration should use centrally managed "
        "credentials."
    )


@pytest.mark.asyncio
async def test_config_flow_accepts_future_cloud_oauth_implementation(hass):
    """The normal flow consumes an abstract cloud provider without credentials."""
    cloud = FakeOAuthImplementation()
    flow = NuHeatConductorConfigFlow()
    flow.hass = hass
    flow.context = {"source": SOURCE_USER}
    flow.flow_id = "cloud-test-flow"

    with patch(
        "homeassistant.helpers.config_entry_oauth2_flow.async_get_implementations",
        AsyncMock(return_value={"cloud": cloud}),
    ):
        result = await flow.async_step_user()
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "pick_implementation"

        result = await flow.async_step_user({"implementation": "cloud"})

    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["url"].startswith("https://identity.example/authorize")
    assert flow.flow_impl is cloud

@pytest.mark.asyncio
async def test_config_flow_happy_path(hass):
    """OAuth completion creates an account-keyed config entry."""
    flow = NuHeatConductorConfigFlow()
    flow.hass = hass
    flow.context = {"source": SOURCE_USER}

    data = {
        "auth_implementation": "test",
        CONF_TOKEN: {CONF_ACCESS_TOKEN: "not-logged"},
    }
    with (
        patch(
            "custom_components.nuheat_conductor.config_flow.async_get_clientsession"
        ),
        patch(
            "custom_components.nuheat_conductor.config_flow.NuHeatApi.get_account",
            AsyncMock(return_value=Account("Owner@Example.com")),
        ),
    ):
        result = await flow.async_oauth_create_entry(data)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Owner@Example.com"
    assert result["data"] == data


@pytest.mark.asyncio
async def test_config_flow_auth_failure(hass):
    """A rejected account lookup aborts without creating an entry."""
    flow = NuHeatConductorConfigFlow()
    flow.hass = hass
    flow.context = {"source": SOURCE_USER}

    with (
        patch(
            "custom_components.nuheat_conductor.config_flow.async_get_clientsession"
        ),
        patch(
            "custom_components.nuheat_conductor.config_flow.NuHeatApi.get_account",
            AsyncMock(side_effect=NuHeatAuthError("rejected")),
        ),
    ):
        result = await flow.async_oauth_create_entry(
            {
                "auth_implementation": "test",
                CONF_TOKEN: {CONF_ACCESS_TOKEN: "not-logged"},
            }
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "invalid_auth"


@pytest.mark.asyncio
async def test_coordinator_first_refresh(hass):
    """The first refresh indexes every thermostat by serial number."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    api = AsyncMock()
    api.list_thermostats.return_value = [thermostat()]
    coordinator = NuHeatCoordinator(hass, entry, api)
    entry.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)

    await coordinator.async_config_entry_first_refresh()

    assert coordinator.data == {"ABC123": thermostat()}
    api.list_thermostats.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_climate_entity_properties_and_defaults(hass):
    """Entity state mirrors the API and uses HA-only fallback limits."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    api = AsyncMock()
    coordinator = NuHeatCoordinator(hass, entry, api)
    coordinator.async_set_updated_data({"ABC123": thermostat()})
    entity = NuHeatClimateEntity(coordinator, "ABC123")

    assert entity.unique_id == "ABC123"
    assert entity.current_temperature == 21.5
    assert entity.target_temperature == 23.0
    assert entity.hvac_mode is HVACMode.HEAT
    assert entity.hvac_action is HVACAction.HEATING
    assert entity.preset_mode == "auto"
    assert entity.available is True
    assert entity.min_temp == DEFAULT_MIN_TEMP
    assert entity.max_temp == DEFAULT_MAX_TEMP
    assert entity.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE


@pytest.mark.asyncio
async def test_setting_target_temperature(hass):
    """A HA target write uses the documented Manual endpoint abstraction."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    api = AsyncMock()
    updated = thermostat(mode=MODE_MANUAL)
    api.set_target_temperature.return_value = updated
    coordinator = NuHeatCoordinator(hass, entry, api)
    coordinator.async_set_updated_data({"ABC123": thermostat()})
    entity = NuHeatClimateEntity(coordinator, "ABC123")

    await entity.async_set_temperature(temperature=24.0)

    api.set_target_temperature.assert_awaited_once_with("ABC123", 24.0)
    assert entity.preset_mode == "manual"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("preset", "schedule_mode", "api_mode"),
    [
        ("auto", ScheduleMode.AUTO, MODE_AUTO),
        ("hold", ScheduleMode.HOLD, MODE_HOLD),
        ("manual", ScheduleMode.MANUAL, MODE_MANUAL),
    ],
)
async def test_preset_mode_mapping(hass, preset, schedule_mode, api_mode):
    """HA presets map exactly to the three OpenAPI v2 endpoints."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    api = AsyncMock()
    api.set_schedule_mode.return_value = thermostat(mode=api_mode)
    coordinator = NuHeatCoordinator(hass, entry, api)
    coordinator.async_set_updated_data({"ABC123": thermostat()})
    entity = NuHeatClimateEntity(coordinator, "ABC123")

    await entity.async_set_preset_mode(preset)

    expected_temperature = None if preset == "auto" else 23.0
    api.set_schedule_mode.assert_awaited_once_with(
        "ABC123", schedule_mode, temperature=expected_temperature
    )
    assert entity.preset_mode == preset


@pytest.mark.asyncio
async def test_refresh_token_rotation_is_stored(hass):
    """OAuth2Session persists both rotated access and refresh tokens."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "auth_implementation": "test",
            CONF_TOKEN: {
                "access_token": "expired-access",
                "refresh_token": "old-refresh",
                "expires_at": time.time() - 60,
                "expires_in": 0,
            },
        },
    )
    entry.add_to_hass(hass)
    implementation = FakeOAuthImplementation()

    with (
        patch(
            "custom_components.nuheat_conductor.async_get_config_entry_implementation",
            AsyncMock(return_value=implementation),
        ),
        patch(
            "custom_components.nuheat_conductor.NuHeatCoordinator.async_config_entry_first_refresh",
            AsyncMock(),
        ),
        patch("custom_components.nuheat_conductor.async_get_clientsession"),
        patch.object(hass.config_entries, "async_forward_entry_setups", AsyncMock()),
    ):
        assert await async_setup_entry(hass, entry) is True

    assert entry.data[CONF_TOKEN]["access_token"] == "rotated-access"
    assert entry.data[CONF_TOKEN]["refresh_token"] == "rotated-refresh"
