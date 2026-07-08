"""Data coordinator for NuHeat Conductor."""

from __future__ import annotations

import logging
from typing import override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import NuHeatApi, NuHeatApiError, NuHeatAuthError, Thermostat
from .const import DOMAIN, SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class NuHeatCoordinator(DataUpdateCoordinator[dict[str, Thermostat]]):
    """Poll all thermostats belonging to the linked account."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, api: NuHeatApi
    ) -> None:
        super().__init__(
            hass,
            logger=_LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=SCAN_INTERVAL,
        )
        self.api = api

    @override
    async def _async_update_data(self) -> dict[str, Thermostat]:
        try:
            thermostats = await self.api.list_thermostats()
        except NuHeatAuthError as err:
            raise ConfigEntryAuthFailed("NuHeat authorization expired") from err
        except NuHeatApiError as err:
            raise UpdateFailed("Unable to update NuHeat thermostats") from err
        return {item.serial_number: item for item in thermostats}

    def async_update_thermostat(self, thermostat: Thermostat) -> None:
        """Apply state returned by a successful write."""
        data = dict(self.data or {})
        data[thermostat.serial_number] = thermostat
        self.async_set_updated_data(data)
