"""Constants for the NuHeat Conductor integration."""

from datetime import timedelta

DOMAIN = "nuheat_conductor"
AUTHORIZE_URL = "https://identity.mynuheat.com/connect/authorize"
TOKEN_URL = "https://identity.mynuheat.com/connect/token"
OAUTH_SCOPES = ("openid", "openapi", "offline_access")

SCAN_INTERVAL = timedelta(minutes=5)

PRESET_AUTO = "auto"
PRESET_HOLD = "hold"
PRESET_MANUAL = "manual"
PRESET_MODES = [PRESET_AUTO, PRESET_HOLD, PRESET_MANUAL]
