"""OAuth config flow for NuHeat Conductor."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any, override

from aiohttp import ClientError
import voluptuous as vol

from homeassistant.config_entries import SOURCE_REAUTH, ConfigFlowResult
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_TOKEN
from homeassistant.helpers import config_entry_oauth2_flow
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import NuHeatApi, NuHeatApiError, NuHeatAuthError
from .const import DOMAIN, OAUTH_SCOPES

_LOGGER = logging.getLogger(__name__)


class NuHeatConductorConfigFlow(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler, domain=DOMAIN
):
    """Handle NuHeat OAuth2 setup and reauthentication."""

    DOMAIN = DOMAIN
    VERSION = 1

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Start with any HA-registered local or cloud OAuth provider."""
        if user_input is None:
            implementations = await config_entry_oauth2_flow.async_get_implementations(
                self.hass, DOMAIN
            )
            if not implementations:
                return self.async_abort(reason="missing_oauth_credentials")
        return await super().async_step_user(user_input)

    @property
    @override
    def logger(self) -> logging.Logger:
        return _LOGGER

    @property
    @override
    def extra_authorize_data(self) -> dict[str, str]:
        return {"scope": " ".join(OAUTH_SCOPES)}

    @override
    async def async_oauth_create_entry(
        self, data: dict[str, Any]
    ) -> ConfigFlowResult:
        token = data[CONF_TOKEN]

        async def async_access_token(force_refresh: bool) -> str:
            return token[CONF_ACCESS_TOKEN]

        api = NuHeatApi(async_get_clientsession(self.hass), async_access_token)
        try:
            account = await api.get_account()
        except NuHeatAuthError:
            return self.async_abort(reason="invalid_auth")
        except (NuHeatApiError, ClientError):
            return self.async_abort(reason="cannot_connect")

        unique_id = account.username.casefold()
        await self.async_set_unique_id(unique_id)

        if self.source == SOURCE_REAUTH:
            self._abort_if_unique_id_mismatch(reason="reauth_account_mismatch")
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), title=account.username, data=data
            )

        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=account.username, data=data)

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask the user to relink the existing account."""
        entry = self._get_reauth_entry()
        if user_input is None:
            return self.async_show_form(
                step_id="reauth_confirm",
                data_schema=vol.Schema({}),
                description_placeholders={"account": entry.title},
            )
        return await self.async_step_pick_implementation(
            {"implementation": entry.data["auth_implementation"]}
        )
