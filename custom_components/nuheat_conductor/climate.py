"""Climate entities for NuHeat Conductor thermostats."""

from __future__ import annotations

from typing import Any, override

from homeassistant.components.climate import ClimateEntity, ClimateEntityFeature
from homeassistant.components.climate.const import (
    DEFAULT_MAX_TEMP,
    DEFAULT_MIN_TEMP,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import NuHeatConfigEntry
from .api import ScheduleMode, Thermostat
from .const import (
    DOMAIN,
    MODE_AUTO,
    MODE_HOLD,
    MODE_MANUAL,
    PRESET_AUTO,
    PRESET_HOLD,
    PRESET_MANUAL,
    PRESET_MODES,
)
from .coordinator import NuHeatCoordinator

MODE_TO_PRESET = {
    MODE_AUTO: PRESET_AUTO,
    MODE_HOLD: PRESET_HOLD,
    MODE_MANUAL: PRESET_MANUAL,
}
PRESET_TO_MODE = {
    PRESET_AUTO: ScheduleMode.AUTO,
    PRESET_HOLD: ScheduleMode.HOLD,
    PRESET_MANUAL: ScheduleMode.MANUAL,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NuHeatConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one climate entity for every thermostat in the account."""
    coordinator = entry.runtime_data.coordinator
    async_add_entities(
        NuHeatClimateEntity(coordinator, thermostat.serial_number)
        for thermostat in coordinator.data.values()
    )


class NuHeatClimateEntity(CoordinatorEntity[NuHeatCoordinator], ClimateEntity):
    """A NuHeat radiant-floor thermostat."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_preset_modes = PRESET_MODES
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator: NuHeatCoordinator, serial_number: str) -> None:
        super().__init__(coordinator)
        self._serial_number = serial_number
        self._attr_unique_id = serial_number

    @property
    def thermostat(self) -> Thermostat:
        return self.coordinator.data[self._serial_number]

    @property
    @override
    def available(self) -> bool:
        return super().available and self.thermostat.online

    @property
    @override
    def current_temperature(self) -> float:
        return self.thermostat.current_temperature

    @property
    @override
    def target_temperature(self) -> float:
        return self.thermostat.target_temperature

    @property
    @override
    def min_temp(self) -> float:
        native = self.thermostat.min_temperature
        return native if native is not None else DEFAULT_MIN_TEMP

    @property
    @override
    def max_temp(self) -> float:
        native = self.thermostat.max_temperature
        return native if native is not None else DEFAULT_MAX_TEMP

    @property
    @override
    def hvac_mode(self) -> HVACMode:
        # OpenAPI v2 has no off endpoint; all three API modes heat as needed.
        return HVACMode.HEAT

    @property
    @override
    def hvac_action(self) -> HVACAction:
        return HVACAction.HEATING if self.thermostat.heating else HVACAction.IDLE

    @property
    @override
    def preset_mode(self) -> str:
        return MODE_TO_PRESET.get(self.thermostat.mode, PRESET_MANUAL)

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        thermostat = await self.coordinator.api.set_target_temperature(
            self._serial_number, float(temperature)
        )
        self.coordinator.async_update_thermostat(thermostat)

    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        mode = PRESET_TO_MODE.get(preset_mode)
        if mode is None:
            raise ValueError(f"Unsupported preset mode: {preset_mode}")
        temperature = (
            None if mode is ScheduleMode.AUTO else self.thermostat.target_temperature
        )
        thermostat = await self.coordinator.api.set_schedule_mode(
            self._serial_number, mode, temperature=temperature
        )
        self.coordinator.async_update_thermostat(thermostat)

    @property
    @override
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._serial_number)},
            serial_number=self._serial_number,
            name=self.thermostat.name or self._serial_number,
            manufacturer="Chemelex / NuHeat",
            model="NuHeat Conductor",
            suggested_area=self.thermostat.name,
        )
