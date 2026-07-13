"""Tests for the NuHeat Conductor custom integration."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.application_credentials import ClientCredential
from homeassistant.components.climate import ClimateEntityFeature
from homeassistant.components.climate.const import (
    ATTR_CURRENT_TEMPERATURE,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER, ConfigEntryState
from homeassistant.const import (
    ATTR_TEMPERATURE,
    CONF_ACCESS_TOKEN,
    CONF_TOKEN,
    UnitOfTemperature,
)
from homeassistant.data_entry_flow import AbortFlow, FlowResultType
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    OAuth2TokenRequestReauthError,
    OAuth2TokenRequestTransientError,
    ServiceValidationError,
)
from homeassistant.helpers.config_entry_oauth2_flow import (
    AbstractOAuth2Implementation,
    ImplementationUnavailableError,
    LocalOAuth2ImplementationWithPkce,
)
from homeassistant.util.unit_system import IMPERIAL_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry

from chemelex_nuheat import (
    Account,
    NuHeatApiError,
    NuHeatAuthError,
    ScheduleMode,
    Thermostat,
    ThermostatMode,
)
from custom_components.nuheat_conductor import async_setup_entry, async_unload_entry
from custom_components.nuheat_conductor.application_credentials import (
    async_get_auth_implementation,
)
from custom_components.nuheat_conductor.behavior import (
    api_mode_for_preset,
    preset_for_api_mode,
    setpoint_command_mode,
)
from custom_components.nuheat_conductor.climate import (
    NuHeatClimateEntity,
)
from custom_components.nuheat_conductor.climate import (
    async_setup_entry as async_setup_climate,
)
from custom_components.nuheat_conductor.config_flow import NuHeatConductorConfigFlow
from custom_components.nuheat_conductor.const import DOMAIN
from custom_components.nuheat_conductor.coordinator import NuHeatCoordinator


def thermostat(
    serial: str = "ABC123",
    *,
    mode: int = ThermostatMode.AUTO,
    heating: bool = True,
    online: bool = True,
) -> Thermostat:
    """Return a normalized API model for integration tests."""
    return Thermostat(
        serial_number=serial,
        name="Bathroom" if serial == "ABC123" else "Kitchen",
        current_temperature=21.5,
        target_temperature=23.0,
        heating=heating,
        online=online,
        mode=mode,
        hold_until=datetime(2026, 7, 8, 1, tzinfo=UTC),
    )


class FakeOAuthImplementation(AbstractOAuth2Implementation):
    """Minimal local/cloud OAuth provider for flow and refresh tests."""

    def __init__(self, *, token: dict | None = None, domain: str = "test") -> None:
        self._token = token or {
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 3600,
        }
        self._domain = domain

    @property
    def name(self) -> str:
        return "Test credentials"

    @property
    def domain(self) -> str:
        return self._domain

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


def oauth_data(access_token: str = "not-logged") -> dict:
    return {
        "auth_implementation": "test",
        CONF_TOKEN: {CONF_ACCESS_TOKEN: access_token},
    }


def config_flow(hass, *, source: str = SOURCE_USER) -> NuHeatConductorConfigFlow:
    flow = NuHeatConductorConfigFlow()
    flow.hass = hass
    flow.handler = DOMAIN
    flow.context = {"source": source}
    return flow


async def coordinator_with(hass, *thermostats: Thermostat):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    api = AsyncMock()
    api.list_thermostats.return_value = list(thermostats)
    coordinator = NuHeatCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()
    return coordinator, api, entry


@pytest.mark.asyncio
@pytest.mark.parametrize("client_secret", ["issued-client-secret", ""])
async def test_local_application_credentials_path(hass, client_secret) -> None:
    implementation = await async_get_auth_implementation(
        hass,
        "local-test",
        ClientCredential("issued-client-id", client_secret),
    )
    assert isinstance(implementation, LocalOAuth2ImplementationWithPkce)
    assert implementation.domain == "local-test"
    assert implementation.client_id == "issued-client-id"
    assert implementation.extra_authorize_data["code_challenge_method"] == "S256"
    assert len(implementation.extra_token_resolve_data["code_verifier"]) == 128


@pytest.mark.asyncio
async def test_missing_credentials_has_helpful_error(hass) -> None:
    flow = config_flow(hass)
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
async def test_oauth_implementation_temporarily_unavailable(hass) -> None:
    """A cloud implementation lookup failure produces a translated abort."""
    flow = config_flow(hass)
    with patch(
        "homeassistant.helpers.config_entry_oauth2_flow.async_get_implementations",
        AsyncMock(side_effect=ImplementationUnavailableError("cloud unavailable")),
    ):
        result = await flow.async_step_user()
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "oauth_implementation_unavailable"


@pytest.mark.asyncio
async def test_config_flow_accepts_future_cloud_implementation(hass) -> None:
    cloud = FakeOAuthImplementation(domain="cloud")
    flow = config_flow(hass)
    flow.flow_id = "cloud-test-flow"
    with patch(
        "homeassistant.helpers.config_entry_oauth2_flow.async_get_implementations",
        AsyncMock(return_value={"cloud": cloud}),
    ):
        result = await flow.async_step_user()
        assert result["step_id"] == "pick_implementation"
        result = await flow.async_step_user({"implementation": "cloud"})
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    assert result["url"].startswith("https://identity.example/authorize")
    assert flow.flow_impl is cloud


@pytest.mark.asyncio
async def test_successful_oauth_setup(hass) -> None:
    flow = config_flow(hass)
    data = oauth_data()
    with (
        patch("custom_components.nuheat_conductor.config_flow.async_get_clientsession"),
        patch(
            "custom_components.nuheat_conductor.config_flow.NuHeatClient.get_account",
            AsyncMock(return_value=Account("Owner@Example.com")),
        ),
    ):
        result = await flow.async_oauth_create_entry(data)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Owner@Example.com"
    assert result["data"] == data
    assert flow.unique_id == "owner@example.com"


@pytest.mark.asyncio
async def test_duplicate_account_is_prevented(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, data=oauth_data(), unique_id="owner@example.com"
    )
    entry.add_to_hass(hass)
    flow = config_flow(hass)
    with (
        patch("custom_components.nuheat_conductor.config_flow.async_get_clientsession"),
        patch(
            "custom_components.nuheat_conductor.config_flow.NuHeatClient.get_account",
            AsyncMock(return_value=Account("Owner@Example.com")),
        ),
    ):
        with pytest.raises(AbortFlow, match="already_configured"):
            await flow.async_oauth_create_entry(oauth_data())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (NuHeatAuthError("rejected"), "invalid_auth"),
        (NuHeatApiError("down"), "cannot_connect"),
    ],
)
async def test_account_lookup_failures(hass, error, reason, caplog) -> None:
    flow = config_flow(hass)
    secret = "access-token-must-not-be-logged"
    with (
        patch("custom_components.nuheat_conductor.config_flow.async_get_clientsession"),
        patch(
            "custom_components.nuheat_conductor.config_flow.NuHeatClient.get_account",
            AsyncMock(side_effect=error),
        ),
    ):
        result = await flow.async_oauth_create_entry(oauth_data(secret))
    assert result["reason"] == reason
    assert secret not in caplog.text


@pytest.mark.asyncio
async def test_successful_reauthentication(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=oauth_data("old-access"),
        unique_id="owner@example.com",
        title="Owner@Example.com",
    )
    entry.add_to_hass(hass)
    flow = config_flow(hass, source=SOURCE_REAUTH)
    flow.context["entry_id"] = entry.entry_id
    with (
        patch("custom_components.nuheat_conductor.config_flow.async_get_clientsession"),
        patch(
            "custom_components.nuheat_conductor.config_flow.NuHeatClient.get_account",
            AsyncMock(return_value=Account("Owner@Example.com")),
        ),
    ):
        result = await flow.async_oauth_create_entry(oauth_data("new-access"))
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_TOKEN][CONF_ACCESS_TOKEN] == "new-access"


@pytest.mark.asyncio
async def test_reauthentication_rejects_wrong_account(hass) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=oauth_data("old-access"),
        unique_id="owner@example.com",
    )
    entry.add_to_hass(hass)
    flow = config_flow(hass, source=SOURCE_REAUTH)
    flow.context["entry_id"] = entry.entry_id
    with (
        patch("custom_components.nuheat_conductor.config_flow.async_get_clientsession"),
        patch(
            "custom_components.nuheat_conductor.config_flow.NuHeatClient.get_account",
            AsyncMock(return_value=Account("Different@Example.com")),
        ),
    ):
        with pytest.raises(AbortFlow, match="reauth_account_mismatch"):
            await flow.async_oauth_create_entry(oauth_data("wrong-account"))
    assert entry.data[CONF_TOKEN][CONF_ACCESS_TOKEN] == "old-access"


@pytest.mark.asyncio
async def test_coordinator_first_refresh_and_offline_availability(hass) -> None:
    coordinator, api, _ = await coordinator_with(
        hass, thermostat(), thermostat("XYZ789", online=False)
    )
    assert set(coordinator.data) == {"ABC123", "XYZ789"}
    assert coordinator.is_thermostat_available("ABC123") is True
    assert coordinator.is_thermostat_available("XYZ789") is False
    api.list_thermostats.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_coordinator_auth_failure_triggers_reauthentication(hass) -> None:
    """Polling auth rejection uses ConfigEntryAuthFailed for HA reauth."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    api = AsyncMock()
    api.list_thermostats.side_effect = NuHeatAuthError("rejected")
    coordinator = NuHeatCoordinator(hass, entry, api)
    with pytest.raises(ConfigEntryAuthFailed):
        await coordinator._async_update_data()


@pytest.mark.asyncio
async def test_dynamic_discovery_retains_entities_without_duplicates(hass) -> None:
    coordinator, api, entry = await coordinator_with(
        hass, thermostat(), thermostat("XYZ789")
    )
    entry.runtime_data = SimpleNamespace(coordinator=coordinator)
    added: list[NuHeatClimateEntity] = []
    await async_setup_climate(hass, entry, lambda entities: added.extend(entities))
    assert {entity.unique_id for entity in added} == {"ABC123", "XYZ789"}

    api.list_thermostats.return_value = [thermostat(), thermostat("NEW456")]
    await coordinator.async_refresh()
    assert {entity.unique_id for entity in added} == {"ABC123", "XYZ789", "NEW456"}
    assert "XYZ789" in coordinator.data
    assert coordinator.is_thermostat_available("XYZ789") is False

    await coordinator.async_refresh()
    assert len(added) == 3
    await coordinator.async_shutdown()


async def add_entity_state(hass, entity: NuHeatClimateEntity, entity_id: str):
    entity.hass = hass
    entity.entity_id = entity_id
    await entity.async_added_to_hass()
    entity.async_write_ha_state()
    await hass.async_block_till_done()
    return hass.states.get(entity_id)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("imperial", "unit", "current", "target", "minimum", "maximum", "write", "celsius"),
    [
        (False, UnitOfTemperature.CELSIUS, 21.5, 23.0, 7.0, 35.0, 24.0, 24.0),
        (True, UnitOfTemperature.FAHRENHEIT, 71.0, 73.0, 45.0, 95.0, 75.2, 24.0),
    ],
)
async def test_climate_state_and_writes_follow_ha_unit(
    hass, imperial, unit, current, target, minimum, maximum, write, celsius
) -> None:
    if imperial:
        hass.config.units = IMPERIAL_SYSTEM
    coordinator, api, _ = await coordinator_with(hass, thermostat())
    api.set_target_temperature.return_value = thermostat(mode=ThermostatMode.MANUAL)
    entity = NuHeatClimateEntity(coordinator, "ABC123")
    state = await add_entity_state(hass, entity, "climate.nuheat_test")

    assert entity.temperature_unit == unit
    assert state.attributes[ATTR_CURRENT_TEMPERATURE] == pytest.approx(current)
    assert state.attributes[ATTR_TEMPERATURE] == pytest.approx(target)
    assert state.attributes["min_temp"] == pytest.approx(minimum)
    assert state.attributes["max_temp"] == pytest.approx(maximum)
    assert entity.hvac_mode is HVACMode.HEAT
    assert entity.hvac_action is HVACAction.HEATING
    assert entity.supported_features & ClimateEntityFeature.TARGET_TEMPERATURE

    await entity.async_set_temperature(temperature=write)
    api.set_target_temperature.assert_awaited_once_with(
        "ABC123", pytest.approx(celsius), mode=ScheduleMode.MANUAL
    )
    await entity.async_will_remove_from_hass()
    await coordinator.async_shutdown()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("preset", "schedule_mode", "api_mode"),
    [
        ("auto", ScheduleMode.AUTO, ThermostatMode.AUTO),
        ("hold", ScheduleMode.HOLD, ThermostatMode.HOLD),
        ("manual", ScheduleMode.MANUAL, ThermostatMode.MANUAL),
    ],
)
async def test_preset_and_mode_mapping(hass, preset, schedule_mode, api_mode) -> None:
    coordinator, api, _ = await coordinator_with(hass, thermostat())
    api.set_schedule_mode.return_value = thermostat(mode=api_mode)
    entity = NuHeatClimateEntity(coordinator, "ABC123")
    await entity.async_set_preset_mode(preset)
    expected_temperature = None if preset == "auto" else 23.0
    api.set_schedule_mode.assert_awaited_once_with(
        "ABC123", schedule_mode, temperature=expected_temperature
    )
    assert preset_for_api_mode(api_mode) == preset
    assert api_mode_for_preset(preset) is schedule_mode
    assert setpoint_command_mode() is ScheduleMode.MANUAL


@pytest.mark.asyncio
async def test_unsupported_preset_uses_translated_exception(hass) -> None:
    """Invalid climate input raises HA's translatable validation error."""
    coordinator, _, _ = await coordinator_with(hass, thermostat())
    entity = NuHeatClimateEntity(coordinator, "ABC123")
    with pytest.raises(ServiceValidationError) as raised:
        await entity.async_set_preset_mode("unsupported")
    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == "unsupported_preset"


@pytest.mark.asyncio
async def test_refresh_token_rotation_is_stored(hass) -> None:
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
    with (
        patch(
            "custom_components.nuheat_conductor.async_get_config_entry_implementation",
            AsyncMock(return_value=FakeOAuthImplementation()),
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            OAuth2TokenRequestReauthError(domain=DOMAIN, request_info=MagicMock()),
            ConfigEntryAuthFailed,
        ),
        (
            OAuth2TokenRequestTransientError(domain=DOMAIN, request_info=MagicMock()),
            ConfigEntryNotReady,
        ),
    ],
)
async def test_rejected_and_transient_refresh_tokens(hass, error, expected) -> None:
    entry = MockConfigEntry(domain=DOMAIN, data=oauth_data())
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.nuheat_conductor.async_get_config_entry_implementation",
            AsyncMock(return_value=FakeOAuthImplementation()),
        ),
        patch(
            "custom_components.nuheat_conductor.OAuth2Session.async_ensure_token_valid",
            AsyncMock(side_effect=error),
        ),
    ):
        with pytest.raises(expected):
            await async_setup_entry(hass, entry)


@pytest.mark.asyncio
async def test_setup_cloud_failure_is_retryable(hass) -> None:
    """A temporary failure during the initial coordinator poll retries setup."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "auth_implementation": "test",
            CONF_TOKEN: {
                "access_token": "valid-access",
                "refresh_token": "refresh",
                "expires_at": time.time() + 3600,
                "expires_in": 3600,
            },
        },
    )
    entry.add_to_hass(hass)
    entry.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    with (
        patch(
            "custom_components.nuheat_conductor.async_get_config_entry_implementation",
            AsyncMock(return_value=FakeOAuthImplementation()),
        ),
        patch("custom_components.nuheat_conductor.async_get_clientsession"),
        patch(
            "custom_components.nuheat_conductor.NuHeatClient.list_thermostats",
            AsyncMock(side_effect=NuHeatApiError("temporary cloud failure")),
        ),
    ):
        with pytest.raises(ConfigEntryNotReady):
            await async_setup_entry(hass, entry)


@pytest.mark.asyncio
async def test_unload_entry(hass) -> None:
    """Unload forwards to the configured entity platforms."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        AsyncMock(return_value=True),
    ) as unload:
        assert await async_unload_entry(hass, entry) is True
    unload.assert_awaited_once()
