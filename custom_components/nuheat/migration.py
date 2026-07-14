"""User-assisted migration from legacy per-thermostat NuHeat entries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_TOKEN, CONF_USERNAME
from homeassistant.core import HomeAssistant

from chemelex_nuheat import Thermostat

from .const import CONF_SERIAL_NUMBER, DOMAIN
from .registry_migration import transfer_legacy_registry_ownership

LEGACY_CONFIG_ENTRY_VERSION = 1
OAUTH_CONFIG_ENTRY_VERSION = 2


class MigrationAccountMismatchError(ValueError):
    """The authenticated account does not contain the initiating thermostat."""


@dataclass(frozen=True, slots=True)
class MigrationResult:
    """Describe a completed legacy-entry consolidation."""

    anchor_entry: ConfigEntry[Any]
    removed_entry_ids: tuple[str, ...]
    migrated_serials: frozenset[str]


def is_legacy_entry_data(data: Mapping[str, Any]) -> bool:
    """Return whether data has the obsolete per-thermostat credential schema."""
    return CONF_TOKEN not in data and all(
        key in data for key in (CONF_USERNAME, CONF_PASSWORD, CONF_SERIAL_NUMBER)
    )


def is_legacy_entry(entry: ConfigEntry[Any]) -> bool:
    """Return whether a config entry requires interactive OAuth migration."""
    return is_legacy_entry_data(entry.data)


def _legacy_serial(entry: ConfigEntry[Any]) -> str | None:
    value = entry.data.get(CONF_SERIAL_NUMBER)
    return value if isinstance(value, str) and value else None


async def async_consolidate_legacy_entries(
    hass: HomeAssistant,
    initiating_entry: ConfigEntry[Any],
    *,
    oauth_data: dict[str, Any],
    account_unique_id: str,
    account_title: str,
    thermostats: list[Thermostat],
) -> MigrationResult:
    """Convert matching legacy entries after successful account validation.

    All remote validation happens before this function. It first confirms that
    the initiating thermostat is present, then transfers registry ownership,
    updates the surviving account entry, and removes redundant entries last.
    """
    initiating_serial = _legacy_serial(initiating_entry)
    discovered_serials = {thermostat.serial_number for thermostat in thermostats}
    if initiating_serial is None or initiating_serial not in discovered_serials:
        raise MigrationAccountMismatchError

    domain_entries = hass.config_entries.async_entries(DOMAIN)
    matching_legacy_entries = [
        entry
        for entry in domain_entries
        if is_legacy_entry(entry)
        and (serial := _legacy_serial(entry)) is not None
        and serial in discovered_serials
    ]
    migrated_serials = frozenset(
        serial
        for entry in matching_legacy_entries
        if (serial := _legacy_serial(entry)) is not None
    )

    existing_account_entry = next(
        (
            entry
            for entry in domain_entries
            if not is_legacy_entry(entry)
            and entry.unique_id == account_unique_id
            and entry.entry_id != initiating_entry.entry_id
        ),
        None,
    )
    anchor_entry = existing_account_entry or initiating_entry
    redundant_entries = [
        entry
        for entry in matching_legacy_entries
        if entry.entry_id != anchor_entry.entry_id
    ]

    # Registry ownership is transferred before any redundant config entry is
    # removed. Entity IDs and every user customization remain on the same
    # registry records; only their config-entry association changes.
    for entry in redundant_entries:
        serial = _legacy_serial(entry)
        assert serial is not None
        transfer_legacy_registry_ownership(hass, entry, anchor_entry, serial)

    hass.config_entries.async_update_entry(
        anchor_entry,
        data=oauth_data,
        title=account_title,
        unique_id=account_unique_id,
        version=OAUTH_CONFIG_ENTRY_VERSION,
    )

    # Removal is deliberately last. Unmatched or temporarily omitted legacy
    # thermostats never enter redundant_entries and remain untouched.
    for entry in redundant_entries:
        await hass.config_entries.async_remove(entry.entry_id)

    return MigrationResult(
        anchor_entry=anchor_entry,
        removed_entry_ids=tuple(entry.entry_id for entry in redundant_entries),
        migrated_serials=migrated_serials,
    )
