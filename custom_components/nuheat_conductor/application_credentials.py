"""Local Application Credentials fallback for NuHeat Conductor development."""

from homeassistant.components.application_credentials import ClientCredential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_entry_oauth2_flow import AbstractOAuth2Implementation

from .oauth import NuHeatLocalOAuth2Implementation


async def async_get_auth_implementation(
    hass: HomeAssistant, auth_domain: str, credential: ClientCredential
) -> AbstractOAuth2Implementation:
    """Return the user-supplied NuHeat OAuth implementation."""
    return NuHeatLocalOAuth2Implementation(
        hass,
        auth_domain,
        credential.client_id,
        credential.client_secret,
    )


async def async_get_description_placeholders(
    hass: HomeAssistant,
) -> dict[str, str]:
    """Describe where users obtain legitimate application credentials."""
    return {"docs_url": "https://api.mynuheat.com/"}
