# NuHeat / Chemelex Home Assistant proof of concept

This repository contains a review-oriented Home Assistant custom integration
and a typed async library for the documented Chemelex NuHeat OpenAPI v2. It is
development work only: it does not replace Home Assistant's built-in `nuheat`
integration, migrate existing entries, publish a package, or modify a live Home
Assistant configuration.

## Repository layout

```text
custom_components/nuheat_conductor/  Home Assistant proof-of-concept integration
src/chemelex_nuheat/                  HA-independent aiohttp API library
tests/                               Mocked API and integration tests
docs/                                Upstream decisions and live-testing plan
.github/                             CI and structured issue templates
```

## Architecture

`chemelex_nuheat.NuHeatClient` owns endpoint paths, request/response parsing,
centi-Celsius encoding, thermostat models, commands, retry classification, and
safe error mapping. It accepts an injected `aiohttp.ClientSession` and an async
access-token provider. It does not import Home Assistant and does not store or
refresh OAuth tokens.

The custom integration obtains Home Assistant's shared aiohttp session and uses
`OAuth2Session` for token storage, refresh, and refresh-token rotation. Its
Application Credentials fallback constructs Home Assistant's built-in
`LocalOAuth2ImplementationWithPkce`. The config flow remains based on
`AbstractOAuth2FlowHandler`, so a future Cloud Account Linking implementation
can be registered without changing the API or thermostat code.

No OAuth client ID, client secret, access token, refresh token, authorization
code, password, or mobile-app credential belongs in this repository.

## API behavior

- Base host: `https://api.nam.mynuheat.com`
- API generation: documented v2 endpoints
- Polling: every five minutes
- Temperatures: centi-Celsius at the HTTP boundary and Celsius in every library
  model
- Modes: Auto, Hold, and Manual; there is no exposed Off mode without a
  documented and tested endpoint
- Limits: v2 has not been confirmed to expose native thermostat min/max values;
  conservative defaults exist only in the Home Assistant entity
- Discovery: later coordinator refreshes add newly discovered thermostats while
  retaining existing entities and marking omitted/offline devices unavailable

Home Assistant entity values follow the installation's configured temperature
unit. Reads convert library Celsius to Celsius or Fahrenheit. Service calls are
converted back to Celsius before reaching the API library.

## OAuth paths

### Development and testing

Use a legitimate OAuth application registration issued by Chemelex and enter
it through Home Assistant's **Application credentials** UI. The client secret
may be empty if Chemelex registers a public PKCE client. The normal NuHeat
config flow never asks users to type client credentials directly.

If no OAuth implementation is registered, the development build reports:

> OAuth application credentials are required for this development build. A
> future official Home Assistant integration should use centrally managed
> credentials.

### Public and official path

The intended public path is a Chemelex-issued Home Assistant OAuth application
managed through Home Assistant Cloud Account Linking. That coordination belongs
to Chemelex and OHF/Nabu Casa. It should let end users link NuHeat without
creating their own OAuth application and without publishing a shared secret.

## Local development

The external API library supports Python 3.13 and later. Home Assistant Core's
current development environment requires Python 3.14.2 or later, so Python
3.14.2 is authoritative for the integration test suite:

```shell
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest
.venv/Scripts/ruff check .
.venv/Scripts/ruff format --check .
.venv/Scripts/mypy
.venv/Scripts/python -m build
```

On POSIX systems, use `.venv/bin/` instead of `.venv/Scripts/`.

All tests use mocked HTTP/OAuth responses. They do not validate the live NuHeat
service. Live validation must follow [docs/LIVE_TESTING.md](docs/LIVE_TESTING.md).

## Installing the development custom integration

This package is intentionally not on PyPI. On a disposable Home Assistant
development environment:

1. Clone this repository.
2. Install the library into the same Python environment with
   `python -m pip install -e /path/to/repository`.
3. Copy `custom_components/nuheat_conductor/` to
   `<config>/custom_components/nuheat_conductor/`.
4. Restart the development Home Assistant instance.
5. Add legitimate Chemelex development credentials under **Settings → Devices
   & services → Application credentials**.
6. Add **NuHeat Conductor** and complete the OAuth consent flow.

Do not perform these steps against a production instance until the integration
has received review and the live test plan has been completed.

To remove the development integration, delete its config entry from **Settings
→ Devices & services**, restart Home Assistant, remove
`custom_components/nuheat_conductor/`, and uninstall the editable
`chemelex-nuheat` package from that development environment. This does not
migrate or delete legacy built-in `nuheat` entries.

Temporary debug logging:

```yaml
logger:
  default: info
  logs:
    custom_components.nuheat_conductor: debug
    chemelex_nuheat: debug
```

The current code does not log response bodies or OAuth secrets. Still sanitize
all logs before attaching them to an issue.

## Maintainer notes

- The old MyNuHeat username/password API used by Home Assistant's existing
  integration appears obsolete after the Chemelex platform migration.
- This proof of concept uses the official NuHeat OpenAPI v2 design and the NAM
  API host identified by Chemelex.
- Official OAuth registration and Cloud Account Linking remain the public
  integration blocker. Local Application Credentials are a development fallback.
- Domain choice, migration strategy, device compatibility, setpoint semantics,
  standby, and stable account identity remain explicit upstream decisions.

See [docs/UPSTREAM_DECISIONS.md](docs/UPSTREAM_DECISIONS.md) for the complete
decision record.

## References

- [NuHeat OpenAPI documentation](https://api.nam.mynuheat.com/)
- [NuHeat OIDC discovery](https://identity.mynuheat.com/.well-known/openid-configuration)
- [Home Assistant Application Credentials](https://developers.home-assistant.io/docs/core/platform/application_credentials/)
- [Home Assistant OAuth config flows](https://developers.home-assistant.io/docs/core/integration/config_flow/#configuration-via-oauth2)
- [Existing Home Assistant NuHeat integration](https://github.com/home-assistant/core/tree/dev/homeassistant/components/nuheat)

## License

Apache-2.0. See [LICENSE](LICENSE).
