# NuHeat Conductor for Home Assistant

This repository contains a Home Assistant custom-integration proof of concept
and a standalone async client for the documented Chemelex/NuHeat OpenAPI v2.
It does not replace Home Assistant's built-in `nuheat` integration or modify a
live Home Assistant configuration.

## Repository layout

```text
custom_components/nuheat_conductor/  Home Assistant custom integration
src/chemelex_nuheat/                  Standalone async reference client
tests/                               Mocked client and integration tests
README.md                            Design, setup, and maintainer notes
pyproject.toml                       Package and test configuration
```

## Authentication

Request your own OAuth client registration from Chemelex/NuHeat. Copy
`.env.example` to `.env` and fill in the issued client ID, registered redirect
URI, and client secret only if one was issued. `.env` is gitignored.

The initial flow is Authorization Code + PKCE:

```python
import asyncio
from urllib.parse import parse_qs, urlparse
from chemelex_nuheat import NuHeatClient

async def main():
    async with NuHeatClient.from_env() as client:
        print(await client.authorization_url())
        callback = urlparse(input("Paste the complete redirect URL: "))
        query = parse_qs(callback.query)
        tokens = await client.authenticate(
            authorization_code=query["code"][0], state=query["state"][0]
        )
        # Persist tokens.refresh_token in a secure store; it can rotate.
        print(await client.list_thermostats())

asyncio.run(main())
```

For a real Home Assistant integration, the callback's `state` must also be
passed to `authenticate`, tokens should live in the config entry, and the
`token_update_callback` should persist every rotated token set.

## Client surface

- `authenticate`
- `authorization_url`
- `list_thermostats`
- `get_thermostat(serial_number)`
- `set_target_temperature(serial_number, celsius)`
- `set_schedule_mode(serial_number, auto|hold|manual, ...)`

Normalized thermostat temperatures are Celsius. Based on the API guide's
temperature examples, the OpenAPI encodes them as integer hundredths of a
degree (`22.5 C` becomes `2250`). The v2 response
schema exposes current/target temperature, heating, online, name, mode, hold
time, and error state. It does **not** expose min/max values. Those therefore
remain `None` unless supplied as client constructor defaults, or unless a
future compatible response includes `minTemperature`/`maxTemperature`.

## Legacy Home Assistant contract

The current HA entity receives one `NuHeatThermostat` and polls `get_data()`
every five minutes. It reads:

- identity/availability: `serial_number`, `room`, `online`
- state: `celsius`/`fahrenheit`, `target_temperature`, `heating`
- limits: `min_celsius`/`max_celsius` or Fahrenheit equivalents
- mode: `schedule_mode` (`1` run, `2` temporary hold, `3` permanent hold)

It writes `schedule_mode` as a property and calls
`set_target_temperature(raw_temperature, schedule_mode)`. Setup also expects
`NuHeat(username, password)`, synchronous `authenticate()`, and
`get_thermostat(serial)`. A production migration therefore needs more than a
manifest bump: HA's config flow must become OAuth/application-credentials,
the coordinator and entity must await async methods, and the entity should use
the normalized model rather than the old package's unusual temperature format.

## Tests

```shell
python -m pip install -e ".[dev]"
python -m pytest
```

All HTTP is mocked with `httpx.MockTransport`; tests do not contact NuHeat.

## Public references

- NuHeat OpenAPI guide: <https://api.mynuheat.com/>
- v2 Swagger schema: <https://api.mynuheat.com/swagger/v2/swagger.json>
- OIDC discovery: <https://identity.mynuheat.com/.well-known/openid-configuration>
- legacy HA integration: <https://github.com/home-assistant/core/tree/master/homeassistant/components/nuheat>
- legacy python package: <https://github.com/broox/python-nuheat>

## Maintainer Notes

- The old `www.mynuheat.com/api` username/password API used by the current
  `nuheat==1.0.1` Home Assistant integration appears obsolete following the
  Chemelex/NuHeat platform migration.
- This proof of concept uses the published Chemelex/NuHeat OpenAPI v2 at
  `https://api.mynuheat.com`, with OAuth 2.0 Authorization Code + PKCE and
  refresh-token rotation.
- The principal blocker for a public Home Assistant integration is an official
  OAuth client registration issued by Chemelex for Home Assistant. No shared
  client secret, mobile-app credential, or reverse-engineered credential is
  included here.
- The desired production end state is Home Assistant Cloud Account Linking,
  backed by the Chemelex-issued Home Assistant OAuth application. End users
  should then authorize their account without creating a client registration.
- Home Assistant Application Credentials remain supported strictly as a
  development and local-testing fallback. They are not the intended public
  onboarding experience.

## Home Assistant custom integration

The proof of concept now includes a separate custom integration at
`custom_components/nuheat_conductor`. It does not replace or modify Home
Assistant's built-in `nuheat` integration.

### Development/testing path: local Application Credentials

This custom development build intentionally contains no shared client secret.
For local testing:

1. Request a legitimate development OAuth client ID and secret from
   NuHeat/Chemelex.
2. Register Home Assistant's OAuth redirect URI with NuHeat. With the `my`
   integration enabled this is
   `https://my.home-assistant.io/redirect/oauth`; otherwise it is
   `<your Home Assistant URL>/auth/external/callback`.
3. Copy the complete `custom_components/nuheat_conductor` directory to
   `/config/custom_components/nuheat_conductor` on the Home Assistant host.
4. Restart Home Assistant.
5. Open **Settings → Devices & services → ⋮ → Application credentials**.
6. Add credentials for **NuHeat Conductor**, entering only the client ID and
   client secret issued for your own registration.
7. Open **Settings → Devices & services → Add integration**, select
   **NuHeat Conductor**, choose those credentials, and complete NuHeat's OAuth
   consent page.

The integration's normal config flow never asks for a client ID or secret. It
only selects from OAuth implementations already registered with Home Assistant.
Application Credentials supplies the local development implementation.

If neither a local implementation nor a centrally managed implementation is
available, setup stops with: “OAuth application credentials are required for
this development build. A future official Home Assistant integration should
use centrally managed credentials.”

### Public/official path: Home Assistant Cloud Account Linking

The upstream path is for Chemelex to issue an OAuth application specifically
for Home Assistant, followed by registration with Home Assistant Cloud Account
Linking. Home Assistant can then register that centrally managed OAuth
implementation with the same abstract config flow. End users would select the
integration and authorize their NuHeat account; they would not create or enter
their own client credentials.

The local PKCE implementation is isolated in `oauth.py` and is constructed only
by `application_credentials.py`. The config flow, config entry, API client, and
token-refresh path depend on Home Assistant's abstract OAuth implementation,
so introducing a cloud provider does not require changing thermostat logic or
storing a secret in this repository.

No YAML configuration is accepted by the integration. OAuth access and refresh
tokens are stored in the Home Assistant config entry and refreshed by Home
Assistant's `OAuth2Session`; rotated refresh tokens replace the old value.

### Debug logging

Add this temporarily to `/config/configuration.yaml`, then restart Home
Assistant:

```yaml
logger:
  default: info
  logs:
    custom_components.nuheat_conductor: debug
```

Remove the override after diagnosis. The integration deliberately does not log
OAuth tokens, client secrets, authorization codes, or API response bodies.

### Integration assumptions and API limits

- OpenAPI v2 has Auto, Hold, and Manual endpoints but no off endpoint. The HA
  entity therefore exposes only `HVACMode.HEAT`; API modes are exposed as
  `auto`, `hold`, and `manual` presets.
- The thermostat model's integer modes are mapped as `1=Auto`, `2=Hold`, and
  `3=Manual`, matching the published mode examples and legacy NuHeat values.
- Temperatures are normalized to Celsius; API integers are treated as
  hundredths of a degree based on the published examples.
- V2 does not publish native min/max temperatures. The entity layer alone uses
  Home Assistant's conservative defaults of 7–35 °C when values are absent.
- The v2 Account model exposes `userName` but no stable account ID, so its
  case-folded username/email is the config-entry unique ID.
- Thermostats are polled every five minutes. Writes refresh the affected
  thermostat immediately from the cloud response path.
