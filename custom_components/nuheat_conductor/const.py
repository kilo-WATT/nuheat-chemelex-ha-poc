"""Constants for the NuHeat Conductor integration."""

from datetime import timedelta

DOMAIN = "nuheat_conductor"
PLATFORMS = ["climate"]

API_BASE_URL = "https://api.mynuheat.com"
AUTHORIZE_URL = "https://identity.mynuheat.com/connect/authorize"
TOKEN_URL = "https://identity.mynuheat.com/connect/token"
OAUTH_SCOPES = ("openid", "openapi", "offline_access")

SCAN_INTERVAL = timedelta(minutes=5)

PRESET_AUTO = "auto"
PRESET_HOLD = "hold"
PRESET_MANUAL = "manual"
PRESET_MODES = [PRESET_AUTO, PRESET_HOLD, PRESET_MANUAL]

# The published examples and legacy API use 1/2/3 for Auto/Hold/Manual.
MODE_AUTO = 1
MODE_HOLD = 2
MODE_MANUAL = 3

