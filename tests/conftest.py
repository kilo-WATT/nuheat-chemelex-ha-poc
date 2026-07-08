"""Home Assistant test fixtures for NuHeat Conductor."""

pytest_plugins = ["pytest_homeassistant_custom_component"]


import sys

import pytest
import pytest_socket
from pytest_homeassistant_custom_component import plugins as ha_test_plugins


def pytest_configure(config):
    """Keep the HA harness from blocking Windows' asyncio socketpair."""
    if sys.platform == "win32":
        pytest_socket.enable_socket()
        ha_test_plugins.pytest_socket.disable_socket = lambda **kwargs: None


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations, socket_enabled):
    """Enable custom integrations and Windows event-loop socketpair creation."""
    yield
