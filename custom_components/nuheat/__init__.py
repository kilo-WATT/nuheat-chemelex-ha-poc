"""NuHeat Conductor custom integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    OAuth2TokenRequestError,
    OAuth2TokenRequestReauthError,
    OAuth2TokenRequestTransientError,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import (
    ImplementationUnavailableError,
    OAuth2Session,
    async_get_config_entry_implementation,
)

from chemelex_nuheat import NuHeatApiError, NuHeatAuthError, NuHeatClient

from .coordinator import NuHeatCoordinator

PLATFORMS = [Platform.CLIMATE]


@dataclass(slots=True)
class NuHeatRuntimeData:
    """Runtime objects for a NuHeat account."""

    api: NuHeatClient
    coordinator: NuHeatCoordinator
    oauth_session: OAuth2Session


type NuHeatConfigEntry = ConfigEntry[NuHeatRuntimeData]


async def async_setup_entry(hass: HomeAssistant, entry: NuHeatConfigEntry) -> bool:
    """Set up NuHeat Conductor from an OAuth config entry."""
    try:
        implementation = await async_get_config_entry_implementation(hass, entry)
    except ImplementationUnavailableError as err:
        raise ConfigEntryNotReady(
            "NuHeat OAuth implementation temporarily unavailable"
        ) from err

    oauth_session = OAuth2Session(hass, entry, implementation)

    async def async_access_token(force_refresh: bool) -> str:
        if force_refresh:
            token = {**oauth_session.token, "expires_at": 0}
            hass.config_entries.async_update_entry(
                entry, data={**entry.data, CONF_TOKEN: token}
            )
        try:
            await oauth_session.async_ensure_token_valid()
        except OAuth2TokenRequestReauthError as err:
            raise NuHeatAuthError("NuHeat authorization expired") from err
        except (OAuth2TokenRequestTransientError, OAuth2TokenRequestError) as err:
            raise NuHeatApiError("Unable to refresh NuHeat authorization") from err
        return oauth_session.token["access_token"]

    try:
        await oauth_session.async_ensure_token_valid()
    except OAuth2TokenRequestReauthError as err:
        raise ConfigEntryAuthFailed("NuHeat authorization expired") from err
    except (OAuth2TokenRequestTransientError, OAuth2TokenRequestError) as err:
        raise ConfigEntryNotReady("Unable to refresh NuHeat authorization") from err

    api = NuHeatClient(async_get_clientsession(hass), async_access_token)
    coordinator = NuHeatCoordinator(hass, entry, api)
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = NuHeatRuntimeData(api, coordinator, oauth_session)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: NuHeatConfigEntry) -> bool:
    """Unload NuHeat Conductor."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
