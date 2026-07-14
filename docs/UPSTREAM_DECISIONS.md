# Upstream decisions

This document separates implemented proof-of-concept behavior from decisions
that require vendor evidence, live hardware, or Home Assistant ownership.

| Topic | Current PoC behavior | Evidence | Remaining validation | Decision owner |
| --- | --- | --- | --- | --- |
| Existing `nuheat` domain | Resolved: this work replaces the built-in integration in place and retains `nuheat`. The former `nuheat_conductor` name describes only earlier PoC history. | The domain, climate platform, serial-number unique ID, and `(nuheat, serial)` device identifier are existing user contracts. | Final maintainer approval of the replacement strategy. | Home Assistant integration maintainer and architecture reviewers. |
| Account OAuth entry versus old per-thermostat entries | One validated legacy entry becomes the account anchor. Matching legacy entries are consolidated only after exact serial validation; unmatched entries remain version 1. | OAuth and v2 discovery are account scoped. Current registry APIs explicitly transfer entity/device config-entry associations before removal. | Live migration on backed-up development data and final stable account identity. | Home Assistant maintainer with migration review. |
| Preserving entity IDs and automations | Implemented as a release requirement. Unique IDs remain exact serials, registry records are reused, and only config-entry ownership changes. | Tests use `climate.master_bath_floor` plus custom names, icons, labels, disabled state, entity/device areas, and device user names. | Validate production-like backups and confirm history behavior during a live migration. | Home Assistant maintainer. |
| Signature versus Conductor compatibility | Uses only documented v2 thermostat models and labels the device generically. | Chemelex recommends OpenAPI v2, but the PoC has no sanitized live matrix from both product families. | Run every applicable case in `LIVE_TESTING.md` on Signature and Conductor devices. | Chemelex for API contract; community hardware testers for evidence. |
| Target-temperature Hold versus Manual | The HA compatibility layer uses v2 Hold for schedule setpoint changes and Manual when already in permanent hold or explicitly using `HVACMode.HEAT`. | This matches the legacy public contract and is isolated in `setpoint_command_mode()`. | Confirm Hold expiration and resulting schedule behavior on live Signature and Conductor thermostats; no expiration is invented. | Chemelex and Home Assistant maintainer. |
| Standby behavior | No standby or Off mode is exposed. | No documented and tested v2 endpoint has been established in this repository. | Identify official endpoint/state semantics and test safe round trips. | Chemelex first; Home Assistant maintainer for entity mapping. |
| Account unique ID | Uses normalized `userName`/email from v2 Account. | The inspected v2 model exposed `userName` but no confirmed immutable account identifier. | Ask whether v2 exposes an immutable subject/account ID, including through OIDC userinfo or token claims. | Chemelex/OAuth owner and Home Assistant maintainer. |
| Native thermostat limits | Library values remain optional; entity falls back to Home Assistant's conservative Celsius defaults and converts them for display. | Native min/max fields have not been confirmed in the documented v2 thermostat response. | Confirm model-specific limits and whether the API returns them. | Chemelex and live-device testers. |
| Official OAuth and Cloud Account Linking | Local Application Credentials use HA's built-in PKCE implementation; the abstract flow accepts a future cloud implementation. | HA supports both local Application Credentials and centrally managed Cloud Account Linking. | Chemelex must issue/register an official HA client and agree redirect URIs/scopes; OHF/Nabu Casa must configure account linking. | Chemelex OAuth team and OHF/Nabu Casa. |
| External library and code ownership | One typed `chemelex_nuheat` package owns the protocol; the integration owns HA concerns. It is not published. | Home Assistant's library guidance keeps token refresh in HA and protocol logic outside Core. | Choose package repository, maintainers, release process, and code owners before a Core requirement pin. | Repository owner and Home Assistant maintainer. |
| Core manifest | Retains a custom-integration `version`, development documentation, no unpublished requirement, and no unagreed code owner. It carries forward legacy DHCP discovery and uses account-level `hub` integration type. | Core and custom integrations have different manifest requirements; DHCP still provides a useful discovery prompt even though authentication is account scoped. | An eventual Core manifest must remove `version`, use a Home Assistant documentation URL, pin a published external-library requirement, name at least one committed code owner, confirm the `nuheat` domain and `hub` type, and add a quality-scale declaration only after review. | Home Assistant maintainer, chosen code owner, and library owner. |

## Legacy manifest comparison

The prototype retains the existing `nuheat` domain, display name, cloud-polling
classification, config flow, and DHCP fingerprint. The integration type changes
from `device` to `hub` because one OAuth account manages multiple thermostat
devices. The obsolete `nuheat==1.0.1` requirement and its logger are removed;
the replacement library is kept in-tree until ownership and publication are
approved. The custom-component-only `version` remains solely for local loading.

## Still unresolved

- final immutable account unique ID instead of provisional normalized username;
- exact temporary Hold expiration behavior;
- standby/Off behavior;
- Signature and Conductor live compatibility;
- official Chemelex OAuth registration and Home Assistant Cloud Account Linking;
- external library ownership and release policy;
- final maintainer and architecture approval.

## Deliberately deferred

- No automatic password exchange. Migration requires one interactive OAuth
  login, validates first, and removes only matching redundant entries last.
- No public package release or Home Assistant Core pull request.
- No Off mode, standby command, group/away command, or SignalR client without
  documented endpoints and tests.
- No claim that mocked tests validate the live NuHeat service.
