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
from homeassistant.util.unit_conversion import TemperatureConverter

from chemelex_nuheat import ScheduleMode, Thermostat

from . import NuHeatConfigEntry
from .behavior import api_mode_for_preset, preset_for_api_mode, setpoint_command_mode
from .const import DOMAIN, PRESET_MODES
from .coordinator import NuHeatCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NuHeatConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create entities initially and when later polls discover thermostats."""
    coordinator = entry.runtime_data.coordinator
    known_serials: set[str] = set()

    def async_add_new_entities() -> None:
        new_serials = set(coordinator.data or {}) - known_serials
        if not new_serials:
            return
        known_serials.update(new_serials)
        async_add_entities(
            NuHeatClimateEntity(coordinator, serial_number)
            for serial_number in sorted(new_serials)
        )

    async_add_new_entities()
    entry.async_on_unload(coordinator.async_add_listener(async_add_new_entities))


class NuHeatClimateEntity(CoordinatorEntity[NuHeatCoordinator], ClimateEntity):
    """A NuHeat radiant-floor thermostat."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_hvac_modes = [HVACMode.HEAT]
    _attr_preset_modes = PRESET_MODES
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.PRESET_MODE
    )

    def __init__(self, coordinator: NuHeatCoordinator, serial_number: str) -> None:
        super().__init__(coordinator)
        self._serial_number = serial_number
        self._attr_unique_id = serial_number
        self._attr_temperature_unit = coordinator.hass.config.units.temperature_unit
        self._attr_target_temperature_step = (
            0.5 if self._attr_temperature_unit == UnitOfTemperature.CELSIUS else 1.0
        )

    @property
    def thermostat(self) -> Thermostat:
        return self.coordinator.data[self._serial_number]

    def _from_celsius(self, value: float) -> float:
        return TemperatureConverter.convert(
            value, UnitOfTemperature.CELSIUS, self.temperature_unit
        )

    def _to_celsius(self, value: float) -> float:
        return TemperatureConverter.convert(
            value, self.temperature_unit, UnitOfTemperature.CELSIUS
        )

    @property
    @override
    def available(self) -> bool:
        return super().available and self.coordinator.is_thermostat_available(
            self._serial_number
        )

    @property
    @override
    def current_temperature(self) -> float:
        return self._from_celsius(self.thermostat.current_temperature)

    @property
    @override
    def target_temperature(self) -> float:
        return self._from_celsius(self.thermostat.target_temperature)

    @property
    @override
    def min_temp(self) -> float:
        value = self.thermostat.min_temperature
        return self._from_celsius(DEFAULT_MIN_TEMP if value is None else value)

    @property
    @override
    def max_temp(self) -> float:
        value = self.thermostat.max_temperature
        return self._from_celsius(DEFAULT_MAX_TEMP if value is None else value)

    @property
    @override
    def hvac_mode(self) -> HVACMode:
        # OpenAPI v2 has no documented off endpoint.
        return HVACMode.HEAT

    @property
    @override
    def hvac_action(self) -> HVACAction:
        return HVACAction.HEATING if self.thermostat.heating else HVACAction.IDLE

    @property
    @override
    def preset_mode(self) -> str:
        return preset_for_api_mode(self.thermostat.mode)

    @override
    async def async_set_temperature(self, **kwargs: Any) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        thermostat = await self.coordinator.api.set_target_temperature(
            self._serial_number,
            self._to_celsius(float(temperature)),
            mode=setpoint_command_mode(),
        )
        self.coordinator.async_update_thermostat(thermostat)

    @override
    async def async_set_preset_mode(self, preset_mode: str) -> None:
        mode = api_mode_for_preset(preset_mode)
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
