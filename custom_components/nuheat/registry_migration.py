"""Registry-preserving helpers for NuHeat config-entry consolidation."""

from __future__ import annotations

from typing import Any

from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN


class RegistryMigrationError(RuntimeError):
    """Registry ownership could not be transferred safely."""


def transfer_legacy_registry_ownership(
    hass: HomeAssistant,
    old_entry: ConfigEntry[Any],
    anchor_entry: ConfigEntry[Any],
    serial_number: str,
) -> None:
    """Transfer associations while retaining the original registry records."""
    entity_registry = er.async_get(hass)
    entity_id = entity_registry.async_get_entity_id(
        CLIMATE_DOMAIN, DOMAIN, serial_number
    )
    if entity_id is not None:
        entity = entity_registry.async_get(entity_id)
        if entity is None:
            raise RegistryMigrationError("NuHeat entity registry lookup failed")
        if entity.config_entry_id == old_entry.entry_id:
            entity = entity_registry.async_update_entity(
                entity.entity_id, config_entry_id=anchor_entry.entry_id
            )
        if entity.config_entry_id != anchor_entry.entry_id:
            raise RegistryMigrationError(
                "NuHeat entity belongs to an unexpected config entry"
            )

    device_registry = dr.async_get(hass)
    for device in list(
        device_registry.devices.get_devices_for_config_entry_id(old_entry.entry_id)
    ):
        if (DOMAIN, serial_number) not in device.identifiers:
            continue
        migrated_device = device_registry.async_update_device(
            device.id,
            add_config_entry_id=anchor_entry.entry_id,
            remove_config_entry_id=old_entry.entry_id,
        )
        if (
            migrated_device is None
            or anchor_entry.entry_id not in migrated_device.config_entries
            or old_entry.entry_id in migrated_device.config_entries
        ):
            raise RegistryMigrationError(
                "NuHeat device registry association transfer failed"
            )
