# NuHeat / Chemelex Home Assistant proof of concept

This repository contains a review-oriented replacement prototype for Home
Assistant's existing `nuheat` integration and a typed async library for the
documented Chemelex NuHeat OpenAPI v2. It retains the existing `nuheat` domain
and identity contract while replacing obsolete username/password access with
account-level OAuth. It is development work only and must not be installed on a
production Home Assistant instance without a backup and maintainer review.

## Repository layout

```text
custom_components/nuheat/            Replacement proof-of-concept integration
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

## Replacement and migration contract

The replacement intentionally preserves the public identity established by the
built-in integration:

- integration domain: `nuheat`;
- entity platform: `climate`;
- entity unique ID: the thermostat serial number, unchanged;
- device identifier: `(nuheat, serial_number)`, unchanged.

Legacy entries contain one username/password/serial tuple per thermostat. A
legacy entry remains unchanged and requests interactive reauthentication until
the user completes OAuth. After the authenticated account and thermostat list
are validated, the initiating entry becomes the account entry. Only other
legacy entries whose exact serial numbers are returned by that account are
consolidated. Registry ownership is transferred to the surviving entry before
redundant entries are removed. Unmatched or temporarily omitted entries remain
unchanged for a later attempt.

Migration tests pre-create customized entity and device records and verify that
entity IDs, names, icons, labels, disabled state, areas, device IDs, device user
names, and device areas remain on the same registry records. Automations,
dashboards, history, and scripts that refer to an unchanged entity ID such as
`climate.master_bath_floor` therefore remain compatible.

## API behavior

- Base host: `https://api.nam.mynuheat.com`
- API generation: documented v2 endpoints
- Polling: every five minutes
- Temperatures: centi-Celsius at the HTTP boundary and Celsius in every library
  model
- API modes: Auto, Hold, and Manual
- Home Assistant compatibility: `HVACMode.AUTO`, `HVACMode.HEAT`, `Run
  Schedule`, `Temporary Hold`, and `Permanent Hold`
- Off: not exposed without a documented and tested endpoint
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
3. Copy `custom_components/nuheat/` to `<config>/custom_components/nuheat/`.
4. Restart the development Home Assistant instance.
5. Add legitimate Chemelex development credentials under **Settings → Devices
   & services → Application credentials**.
6. Add **NuHeat** and complete the OAuth consent flow.

Do not perform these steps against a production instance until the integration
has received review and the live test plan has been completed.

This custom component shadows the built-in `nuheat` integration and is suitable
only for a disposable development instance. Before testing migration, back up
Home Assistant through its supported backup feature. After a successful
migration, restoring that backup is the supported way to return to the obsolete
legacy-entry data during PoC testing. Do not manually edit storage files.

Temporary debug logging:

```yaml
logger:
  default: info
  logs:
    custom_components.nuheat: debug
    chemelex_nuheat: debug
```

The current code does not log response bodies or OAuth secrets. Still sanitize
all logs before attaching them to an issue.

## Maintainer notes

- The old MyNuHeat username/password API used by Home Assistant's existing
  integration appears obsolete after the Chemelex platform migration.
- This proof of concept targets in-place replacement of the built-in `nuheat`
  integration using official NuHeat OpenAPI v2 and the NAM API host.
- Retaining serial-number entity unique IDs and `(nuheat, serial)` device
  identifiers is a release requirement.
- Official OAuth registration and Cloud Account Linking remain the public
  integration blocker. Local Application Credentials are a development fallback.
- The domain decision is resolved. Stable account identity, device
  compatibility, Hold expiration, standby, library ownership, and maintainer
  approval remain explicit upstream decisions.

Entity preservation cannot guarantee identical cloud behavior. Hold duration,
standby semantics, unavailable API fields, and the shift from per-thermostat
entries to one account entry still require live validation.

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
