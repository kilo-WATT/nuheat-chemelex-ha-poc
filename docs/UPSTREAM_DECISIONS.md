# Upstream decisions

This document separates implemented proof-of-concept behavior from decisions
that require vendor evidence, live hardware, or Home Assistant ownership.

| Topic | Current PoC behavior | Evidence | Remaining validation | Decision owner |
| --- | --- | --- | --- | --- |
| Existing `nuheat` versus new `nuheat_conductor` domain | Keeps `nuheat_conductor`; makes no final domain or migration decision. | The built-in `nuheat` domain represents an existing user contract, while the new API is account-scoped OAuth. | Assess breaking-change policy, user expectations, and whether in-place replacement is feasible. | Home Assistant integration maintainer and architecture reviewers. |
| Account OAuth entry versus old per-thermostat entries | One OAuth config entry discovers all account thermostats. | OAuth authorization and v2 account/thermostat listing are account scoped. | Confirm how legacy serial-number entries can be associated without duplicate devices. | Home Assistant maintainer with migration review. |
| Preserving entity IDs and automations | Thermostat serial number remains the entity unique ID; no migration is implemented. | The legacy integration and PoC both have a stable thermostat serial. | Test entity-registry behavior and design a reversible config-entry migration before changing the built-in domain. | Home Assistant maintainer. |
| Signature versus Conductor compatibility | Uses only documented v2 thermostat models and labels the device generically. | Chemelex recommends OpenAPI v2, but the PoC has no sanitized live matrix from both product families. | Run every applicable case in `LIVE_TESTING.md` on Signature and Conductor devices. | Chemelex for API contract; community hardware testers for evidence. |
| Target-temperature Hold versus Manual | A small `setpoint_command_mode()` policy currently returns Manual to preserve the earlier PoC behavior. | The earlier PoC used the v2 Manual endpoint; this is not proof of desired user behavior. | Chemelex must describe the intended semantics and testers must observe schedule behavior after writes. | Chemelex and Home Assistant maintainer. |
| Standby behavior | No standby or Off mode is exposed. | No documented and tested v2 endpoint has been established in this repository. | Identify official endpoint/state semantics and test safe round trips. | Chemelex first; Home Assistant maintainer for entity mapping. |
| Account unique ID | Uses normalized `userName`/email from v2 Account. | The inspected v2 model exposed `userName` but no confirmed immutable account identifier. | Ask whether v2 exposes an immutable subject/account ID, including through OIDC userinfo or token claims. | Chemelex/OAuth owner and Home Assistant maintainer. |
| Native thermostat limits | Library values remain optional; entity falls back to Home Assistant's conservative Celsius defaults and converts them for display. | Native min/max fields have not been confirmed in the documented v2 thermostat response. | Confirm model-specific limits and whether the API returns them. | Chemelex and live-device testers. |
| Official OAuth and Cloud Account Linking | Local Application Credentials use HA's built-in PKCE implementation; the abstract flow accepts a future cloud implementation. | HA supports both local Application Credentials and centrally managed Cloud Account Linking. | Chemelex must issue/register an official HA client and agree redirect URIs/scopes; OHF/Nabu Casa must configure account linking. | Chemelex OAuth team and OHF/Nabu Casa. |
| External library and code ownership | One typed `chemelex_nuheat` package owns the protocol; the integration owns HA concerns. It is not published. | Home Assistant's library guidance keeps token refresh in HA and protocol logic outside Core. | Choose package repository, maintainers, release process, and code owners before a Core requirement pin. | Repository owner and Home Assistant maintainer. |
| Core manifest | Retains a custom-integration manifest with `version` and development documentation so local testing remains valid. | Core and custom integrations have different manifest requirements. | An eventual Core manifest must remove `version`, use a Home Assistant documentation URL, pin a published external-library requirement, name at least one committed code owner, settle the final domain and integration type, and add an appropriate quality-scale declaration only after review. | Home Assistant maintainer, chosen code owner, and library owner. |

## Deliberately deferred

- No irreversible config-entry migration.
- No public package release or Home Assistant Core pull request.
- No Off mode, standby command, group/away command, or SignalR client without
  documented endpoints and tests.
- No claim that mocked tests validate the live NuHeat service.
