"""NuHeat OAuth helpers used by local development credentials.

The config flow itself only depends on Home Assistant's abstract OAuth
implementation interface. A future Home Assistant Cloud Account Linking
implementation can therefore be registered without using this local class.
"""

import base64
import hashlib
import secrets
from typing import override

from homeassistant.core import HomeAssistant
from homeassistant.helpers.config_entry_oauth2_flow import LocalOAuth2Implementation

from .const import AUTHORIZE_URL, OAUTH_SCOPES, TOKEN_URL


class NuHeatLocalOAuth2Implementation(LocalOAuth2Implementation):
    """Authorization Code implementation with PKCE for local credentials."""

    def __init__(
        self,
        hass: HomeAssistant,
        domain: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        super().__init__(
            hass, domain, client_id, client_secret, AUTHORIZE_URL, TOKEN_URL
        )
        self._code_verifier = secrets.token_urlsafe(96)[:128]

    @property
    @override
    def extra_authorize_data(self) -> dict[str, str]:
        digest = hashlib.sha256(self._code_verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return {
            "scope": " ".join(OAUTH_SCOPES),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }

    @property
    @override
    def extra_token_resolve_data(self) -> dict[str, str]:
        return {"code_verifier": self._code_verifier}

