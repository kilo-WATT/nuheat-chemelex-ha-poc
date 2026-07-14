"""Isolated mappings for NuHeat behavior that still needs live validation."""

from chemelex_nuheat import ScheduleMode, ThermostatMode

from .const import PRESET_AUTO, PRESET_HOLD, PRESET_MANUAL

MODE_TO_PRESET = {
    ThermostatMode.AUTO: PRESET_AUTO,
    ThermostatMode.HOLD: PRESET_HOLD,
    ThermostatMode.MANUAL: PRESET_MANUAL,
}
PRESET_TO_MODE = {
    PRESET_AUTO: ScheduleMode.AUTO,
    PRESET_HOLD: ScheduleMode.HOLD,
    PRESET_MANUAL: ScheduleMode.MANUAL,
}


def preset_for_api_mode(mode: int) -> str:
    """Map a reported v2 integer mode to a Home Assistant preset."""
    try:
        return MODE_TO_PRESET[ThermostatMode(mode)]
    except (ValueError, KeyError):
        return PRESET_MANUAL


def api_mode_for_preset(preset: str) -> ScheduleMode:
    """Map a supported Home Assistant preset to a v2 mode command."""
    try:
        return PRESET_TO_MODE[preset]
    except KeyError as err:
        raise ValueError(f"Unsupported preset mode: {preset}") from err


def setpoint_command_mode() -> ScheduleMode:
    """Return the PoC setpoint policy pending vendor/maintainer confirmation.

    The existing PoC uses Manual. Keeping this choice in one named function
    makes it explicit and easy to replace after live API semantics are known.
    """
    return ScheduleMode.MANUAL
