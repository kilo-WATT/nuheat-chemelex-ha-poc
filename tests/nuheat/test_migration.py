"""Tests for user-assisted migration of legacy NuHeat entries."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.config_entries import SOURCE_REAUTH
from homeassistant.const import (
    CONF_ACCESS_TOKEN,
    CONF_PASSWORD,
    CONF_TOKEN,
    CONF_USERNAME,
)
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import (
    area_registry as ar,
)
from homeassistant.helpers import (
    device_registry as dr,
)
from homeassistant.helpers import (
    entity_registry as er,
)
from homeassistant.helpers import (
    label_registry as lr,
)
from homeassistant.helpers.config_entry_oauth2_flow import AbstractOAuth2Implementation
from homeassistant.helpers.entity_registry import RegistryEntryDisabler
from pytest_homeassistant_custom_component.common import MockConfigEntry

from chemelex_nuheat import (
    Account,
    NuHeatApiError,
    NuHeatAuthError,
    Thermostat,
    ThermostatMode,
)
from custom_components.nuheat import async_migrate_entry, async_setup_entry
from custom_components.nuheat.config_flow import NuHeatConfigFlow
from custom_components.nuheat.const import CONF_SERIAL_NUMBER, DOMAIN
from custom_components.nuheat.migration import (
    OAUTH_CONFIG_ENTRY_VERSION,
    async_consolidate_legacy_entries,
    is_legacy_entry,
    is_legacy_entry_data,
)

LEGACY_PASSWORD = "synthetic-legacy-password"


def thermostat(serial_number: str, name: str = "Bathroom") -> Thermostat:
    """Return one normalized v2 thermostat."""
    return Thermostat(
        serial_number=serial_number,
        name=name,
        current_temperature=21.0,
        target_temperature=23.0,
        heating=False,
        online=True,
        mode=ThermostatMode.AUTO,
        hold_until=datetime(2026, 7, 8, 1, tzinfo=UTC),
    )


def legacy_data(serial_number: str, username: str = "owner@example.com") -> dict:
    """Return the exact legacy username/password/serial schema."""
    return {
        CONF_USERNAME: username,
        CONF_PASSWORD: LEGACY_PASSWORD,
        CONF_SERIAL_NUMBER: serial_number,
    }


def oauth_data(access_token: str = "synthetic-access-token") -> dict:
    """Return synthetic Home Assistant OAuth entry data."""
    return {
        "auth_implementation": "test",
        CONF_TOKEN: {
            CONF_ACCESS_TOKEN: access_token,
            "refresh_token": "synthetic-refresh-token",
            "expires_at": 4_000_000_000,
            "expires_in": 3600,
        },
    }


def add_legacy_entry(
    hass,
    serial_number: str,
    title: str | None = None,
    *,
    username: str = "owner@example.com",
):
    """Add a realistic version-1 legacy config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=title or serial_number,
        data=legacy_data(serial_number, username),
        unique_id=serial_number,
        version=1,
    )
    entry.add_to_hass(hass)
    return entry


def migration_flow(hass, entry) -> NuHeatConfigFlow:
    """Return a reauthentication flow bound to a legacy entry."""
    flow = NuHeatConfigFlow()
    flow.hass = hass
    flow.handler = DOMAIN
    flow.context = {"source": SOURCE_REAUTH, "entry_id": entry.entry_id}
    return flow


async def run_migration_flow(
    hass,
    entry,
    thermostats: list[Thermostat],
    *,
    account: str = "Owner@Example.com",
    token: str = "new-synthetic-access",
):
    """Complete the post-OAuth migration callback with mocked API data."""
    flow = migration_flow(hass, entry)
    with (
        patch("custom_components.nuheat.config_flow.async_get_clientsession"),
        patch(
            "custom_components.nuheat.config_flow.NuHeatClient.get_account",
            AsyncMock(return_value=Account(account)),
        ),
        patch(
            "custom_components.nuheat.config_flow.NuHeatClient.list_thermostats",
            AsyncMock(return_value=thermostats),
        ),
        patch.object(hass.config_entries, "async_schedule_reload"),
    ):
        return await flow.async_oauth_create_entry(oauth_data(token))


class FakeOAuthImplementation(AbstractOAuth2Implementation):
    """Minimal OAuth implementation for account-entry setup tests."""

    @property
    def name(self) -> str:
        return "Synthetic test credentials"

    @property
    def domain(self) -> str:
        return "test"

    async def async_generate_authorize_url(self, flow_id: str) -> str:
        return "https://identity.example/authorize"

    async def async_resolve_external_data(self, external_data: object) -> dict:
        return oauth_data()[CONF_TOKEN]

    async def _async_refresh_token(self, token: dict) -> dict:
        return token


def create_customized_registry_records(hass, entry, serial_number: str):
    """Create realistic legacy entity and device records with custom metadata."""
    entity_area = ar.async_get(hass).async_create(f"Entity {serial_number}")
    device_area = ar.async_get(hass).async_create(f"Device {serial_number}")
    label = lr.async_get(hass).async_create(f"Label {serial_number}")

    device_registry = dr.async_get(hass)
    device = device_registry.async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, serial_number)},
        manufacturer="NuHeat",
        model="nVent Signature",
        name=f"Legacy {serial_number}",
        serial_number=serial_number,
    )
    device = device_registry.async_update_device(
        device.id,
        area_id=device_area.id,
        name_by_user=f"Custom device {serial_number}",
    )

    entity_registry = er.async_get(hass)
    entity = entity_registry.async_get_or_create(
        CLIMATE_DOMAIN,
        DOMAIN,
        serial_number,
        config_entry=entry,
        device_id=device.id,
        suggested_object_id=f"legacy_{serial_number.lower()}",
    )
    entity = entity_registry.async_update_entity(
        entity.entity_id,
        area_id=entity_area.id,
        disabled_by=RegistryEntryDisabler.USER,
        icon="mdi:radiator",
        labels={label.label_id},
        name=f"Custom entity {serial_number}",
        new_entity_id=(
            "climate.master_bath_floor"
            if serial_number == "ABC123"
            else f"climate.custom_{serial_number.lower()}"
        ),
    )
    return entity, device, entity_area, device_area, label


@pytest.mark.asyncio
async def test_legacy_entry_detection_and_setup_requests_migration(hass) -> None:
    """Legacy credentials are detected without retrying the obsolete API."""
    entry = add_legacy_entry(hass, "ABC123", "Master Bath")
    assert is_legacy_entry_data(entry.data)
    assert is_legacy_entry(entry)
    assert await async_migrate_entry(hass, entry) is True
    assert entry.version == 1
    assert entry.data[CONF_PASSWORD] == LEGACY_PASSWORD

    with pytest.raises(ConfigEntryAuthFailed) as raised:
        await async_setup_entry(hass, entry)
    assert raised.value.translation_domain == DOMAIN
    assert raised.value.translation_key == "legacy_migration_required"

    flow = migration_flow(hass, entry)
    result = await flow.async_step_reauth(entry.data)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "migration_confirm"


@pytest.mark.asyncio
async def test_version_one_oauth_entry_advances_without_legacy_data(hass) -> None:
    """Only the legacy credential schema remains at config-entry version 1."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data=oauth_data(),
        unique_id="owner@example.com",
        version=1,
    )
    entry.add_to_hass(hass)

    assert await async_migrate_entry(hass, entry) is True
    assert entry.version == OAUTH_CONFIG_ENTRY_VERSION


@pytest.mark.asyncio
async def test_one_legacy_entry_becomes_oauth_account(hass) -> None:
    """A validated legacy entry is converted in place and loses its password."""
    entry = add_legacy_entry(hass, "ABC123")
    result = await run_migration_flow(hass, entry, [thermostat("ABC123")])

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "migration_successful"
    assert hass.config_entries.async_get_entry(entry.entry_id) is entry
    assert entry.version == OAUTH_CONFIG_ENTRY_VERSION
    assert entry.unique_id == "owner@example.com"
    assert entry.data[CONF_TOKEN][CONF_ACCESS_TOKEN] == "new-synthetic-access"
    assert CONF_USERNAME not in entry.data
    assert CONF_PASSWORD not in entry.data
    assert CONF_SERIAL_NUMBER not in entry.data


@pytest.mark.asyncio
async def test_customized_entity_and_device_survive_initialization(hass) -> None:
    """Setup reuses legacy registry records and preserves all customization."""
    entry = add_legacy_entry(hass, "ABC123")
    original_entity, original_device, entity_area, device_area, label = (
        create_customized_registry_records(hass, entry, "ABC123")
    )
    result = await run_migration_flow(hass, entry, [thermostat("ABC123")])
    assert result["reason"] == "migration_successful"

    with (
        patch(
            "custom_components.nuheat.async_get_config_entry_implementation",
            AsyncMock(return_value=FakeOAuthImplementation()),
        ),
        patch("custom_components.nuheat.async_get_clientsession", MagicMock()),
        patch(
            "custom_components.nuheat.NuHeatClient.list_thermostats",
            AsyncMock(return_value=[thermostat("ABC123")]),
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id) is True
        await hass.async_block_till_done()

    entity_registry = er.async_get(hass)
    entities = [
        item
        for item in entity_registry.entities.values()
        if item.domain == CLIMATE_DOMAIN
        and item.platform == DOMAIN
        and item.unique_id == "ABC123"
    ]
    assert len(entities) == 1
    migrated_entity = entities[0]
    assert migrated_entity.id == original_entity.id
    assert migrated_entity.entity_id == "climate.master_bath_floor"
    assert migrated_entity.name == "Custom entity ABC123"
    assert migrated_entity.icon == "mdi:radiator"
    assert migrated_entity.area_id == entity_area.id
    assert migrated_entity.disabled_by is RegistryEntryDisabler.USER
    assert migrated_entity.labels == {label.label_id}
    assert migrated_entity.config_entry_id == entry.entry_id

    device_registry = dr.async_get(hass)
    devices = [
        item
        for item in device_registry.devices.values()
        if (DOMAIN, "ABC123") in item.identifiers
    ]
    assert len(devices) == 1
    migrated_device = devices[0]
    assert migrated_device.id == original_device.id
    assert migrated_device.area_id == device_area.id
    assert migrated_device.name_by_user == "Custom device ABC123"
    assert migrated_device.config_entries == {entry.entry_id}


@pytest.mark.asyncio
async def test_multiple_entries_consolidate_and_transfer_registry_ownership(
    hass,
) -> None:
    """Matching thermostats share one account entry without registry churn."""
    anchor = add_legacy_entry(hass, "ABC123")
    redundant = add_legacy_entry(hass, "XYZ789")
    entity_a, device_a, *_ = create_customized_registry_records(hass, anchor, "ABC123")
    entity_b, device_b, *_ = create_customized_registry_records(
        hass, redundant, "XYZ789"
    )

    result = await run_migration_flow(
        hass,
        anchor,
        [thermostat("ABC123"), thermostat("XYZ789", "Kitchen")],
    )

    assert result["reason"] == "migration_successful"
    assert hass.config_entries.async_get_entry(redundant.entry_id) is None
    assert hass.config_entries.async_entries(DOMAIN) == [anchor]
    entity_registry = er.async_get(hass)
    assert entity_registry.async_get(entity_a.entity_id).id == entity_a.id
    migrated_b = entity_registry.async_get(entity_b.entity_id)
    assert migrated_b.id == entity_b.id
    assert migrated_b.config_entry_id == anchor.entry_id
    assert (
        len(
            [
                item
                for item in entity_registry.entities.values()
                if item.platform == DOMAIN and item.unique_id in {"ABC123", "XYZ789"}
            ]
        )
        == 2
    )

    device_registry = dr.async_get(hass)
    assert device_registry.async_get(device_a.id).id == device_a.id
    migrated_device_b = device_registry.async_get(device_b.id)
    assert migrated_device_b.id == device_b.id
    assert migrated_device_b.config_entries == {anchor.entry_id}
    assert (
        len(
            [
                item
                for item in device_registry.devices.values()
                if item.identifiers & {(DOMAIN, "ABC123"), (DOMAIN, "XYZ789")}
            ]
        )
        == 2
    )


@pytest.mark.asyncio
async def test_unrelated_and_temporarily_omitted_entries_remain_untouched(hass) -> None:
    """Only serials returned by this account are eligible for consolidation."""
    anchor = add_legacy_entry(hass, "ABC123")
    omitted = add_legacy_entry(hass, "XYZ789")
    unrelated = add_legacy_entry(hass, "OTHER1", username="other@example.com")
    omitted_data = dict(omitted.data)
    unrelated_data = dict(unrelated.data)

    result = await run_migration_flow(hass, anchor, [thermostat("ABC123")])

    assert result["reason"] == "migration_successful"
    assert hass.config_entries.async_get_entry(omitted.entry_id) is omitted
    assert hass.config_entries.async_get_entry(unrelated.entry_id) is unrelated
    assert omitted.data == omitted_data
    assert unrelated.data == unrelated_data
    assert omitted.data[CONF_PASSWORD] == LEGACY_PASSWORD
    assert unrelated.data[CONF_PASSWORD] == LEGACY_PASSWORD


@pytest.mark.asyncio
async def test_wrong_account_rolls_back_without_registry_changes(hass) -> None:
    """The initiating serial must exist before any local mutation occurs."""
    entry = add_legacy_entry(hass, "ABC123")
    entity, device, *_ = create_customized_registry_records(hass, entry, "ABC123")
    original_data = dict(entry.data)

    result = await run_migration_flow(hass, entry, [thermostat("DIFFERENT")])

    assert result["reason"] == "migration_account_mismatch"
    assert entry.version == 1
    assert entry.unique_id == "ABC123"
    assert entry.data == original_data
    assert (
        er.async_get(hass).async_get(entity.entity_id).config_entry_id == entry.entry_id
    )
    assert dr.async_get(hass).async_get(device.id).config_entries == {entry.entry_id}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "reason"),
    [
        (NuHeatAuthError("synthetic OAuth rejection"), "invalid_auth"),
        (NuHeatApiError("synthetic API failure"), "cannot_connect"),
    ],
)
async def test_oauth_and_api_failures_leave_legacy_state_unchanged(
    hass, error, reason, caplog
) -> None:
    """Remote failures occur before any destructive migration operation."""
    entry = add_legacy_entry(hass, "ABC123")
    entity, device, *_ = create_customized_registry_records(hass, entry, "ABC123")
    original_data = dict(entry.data)
    flow = migration_flow(hass, entry)
    authorization_code = "synthetic-authorization-code-not-for-logs"

    with (
        patch("custom_components.nuheat.config_flow.async_get_clientsession"),
        patch(
            "custom_components.nuheat.config_flow.NuHeatClient.get_account",
            AsyncMock(side_effect=error),
        ),
    ):
        result = await flow.async_oauth_create_entry(oauth_data(authorization_code))

    assert result["reason"] == reason
    assert entry.data == original_data
    assert entry.version == 1
    assert hass.config_entries.async_get_entry(entry.entry_id) is entry
    assert (
        er.async_get(hass).async_get(entity.entity_id).config_entry_id == entry.entry_id
    )
    assert dr.async_get(hass).async_get(device.id).config_entries == {entry.entry_id}
    assert LEGACY_PASSWORD not in caplog.text
    assert authorization_code not in caplog.text
    assert "synthetic-refresh-token" not in caplog.text


@pytest.mark.asyncio
async def test_existing_oauth_account_absorbs_matching_legacy_entry(hass) -> None:
    """Migration reuses an existing account entry rather than duplicating it."""
    account_entry = MockConfigEntry(
        domain=DOMAIN,
        title="Owner@Example.com",
        data=oauth_data("old-account-token"),
        unique_id="owner@example.com",
        version=OAUTH_CONFIG_ENTRY_VERSION,
    )
    account_entry.add_to_hass(hass)
    legacy = add_legacy_entry(hass, "ABC123")
    entity, device, *_ = create_customized_registry_records(hass, legacy, "ABC123")

    result = await run_migration_flow(hass, legacy, [thermostat("ABC123")])

    assert result["reason"] == "migration_successful"
    assert hass.config_entries.async_get_entry(legacy.entry_id) is None
    assert hass.config_entries.async_entries(DOMAIN) == [account_entry]
    assert account_entry.data[CONF_TOKEN][CONF_ACCESS_TOKEN] == ("new-synthetic-access")
    assert er.async_get(hass).async_get(entity.entity_id).config_entry_id == (
        account_entry.entry_id
    )
    assert dr.async_get(hass).async_get(device.id).config_entries == {
        account_entry.entry_id
    }


@pytest.mark.asyncio
async def test_direct_consolidation_reports_only_confirmed_serials(hass) -> None:
    """The migration result documents exactly which entries were validated."""
    anchor = add_legacy_entry(hass, "ABC123")
    unmatched = add_legacy_entry(hass, "XYZ789")

    result = await async_consolidate_legacy_entries(
        hass,
        anchor,
        oauth_data=oauth_data(),
        account_unique_id="owner@example.com",
        account_title="Owner@Example.com",
        thermostats=[thermostat("ABC123")],
    )

    assert result.anchor_entry is anchor
    assert result.migrated_serials == {"ABC123"}
    assert result.removed_entry_ids == ()
    assert hass.config_entries.async_get_entry(unmatched.entry_id) is unmatched
