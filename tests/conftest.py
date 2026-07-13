"""Home Assistant test fixtures for NuHeat Conductor."""

from __future__ import annotations

import base64
import hashlib
import secrets
import sys
from pathlib import Path

import pytest
import pytest_socket
from pytest_homeassistant_custom_component import plugins as ha_test_plugins

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

# The local harness is HA 2025.1. Production code imports current Core's
# built-ins directly; these test-only shims allow the same tests to run on the
# older Windows harness while CI exercises current Python/Home Assistant.
from homeassistant.helpers import config_entry_oauth2_flow as oauth2  # noqa: E402

if not hasattr(oauth2, "ImplementationUnavailableError"):

    class ImplementationUnavailableError(Exception):
        """Compatibility shim for current Core."""

    oauth2.ImplementationUnavailableError = ImplementationUnavailableError

if not hasattr(oauth2, "OAuth2TokenRequestError"):

    class OAuth2TokenRequestError(Exception):
        """Compatibility shim for current Core."""

    class OAuth2TokenRequestReauthError(OAuth2TokenRequestError):
        """Compatibility shim for current Core."""

    class OAuth2TokenRequestTransientError(OAuth2TokenRequestError):
        """Compatibility shim for current Core."""

    oauth2.OAuth2TokenRequestError = OAuth2TokenRequestError
    oauth2.OAuth2TokenRequestReauthError = OAuth2TokenRequestReauthError
    oauth2.OAuth2TokenRequestTransientError = OAuth2TokenRequestTransientError

if not hasattr(oauth2, "LocalOAuth2ImplementationWithPkce"):

    class LocalOAuth2ImplementationWithPkce(oauth2.LocalOAuth2Implementation):
        """Test-only backport of the current built-in PKCE implementation."""

        def __init__(
            self,
            hass,
            domain,
            client_id,
            *,
            authorize_url,
            token_url,
            client_secret="",
            code_verifier_length=128,
        ) -> None:
            super().__init__(
                hass,
                domain,
                client_id,
                client_secret,
                authorize_url,
                token_url,
            )
            self._code_verifier = secrets.token_urlsafe(code_verifier_length)[
                :code_verifier_length
            ]

        @property
        def extra_authorize_data(self):
            digest = hashlib.sha256(self._code_verifier.encode()).digest()
            challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
            return {
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }

        @property
        def extra_token_resolve_data(self):
            return {"code_verifier": self._code_verifier}

    oauth2.LocalOAuth2ImplementationWithPkce = LocalOAuth2ImplementationWithPkce

pytest_plugins = ["pytest_homeassistant_custom_component"]


def pytest_configure(config):
    """Keep the HA harness from blocking Windows' asyncio socketpair."""
    if sys.platform == "win32":
        pytest_socket.enable_socket()
        ha_test_plugins.pytest_socket.disable_socket = lambda **kwargs: None


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations, socket_enabled):
    """Enable custom integrations and Windows event-loop socketpair creation."""
    yield
