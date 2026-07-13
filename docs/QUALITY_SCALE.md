# Integration Quality Scale readiness

This is a proof-of-concept review checklist, not a quality-tier declaration.
Home Assistant requires every applicable Bronze rule to be complete before a
new Core integration can claim Bronze. The checklist follows the current
[Integration Quality Scale rules](https://developers.home-assistant.io/docs/core/integration-quality-scale/rules/).

## Bronze checklist

| Rule | Status | Evidence or remaining work |
| --- | --- | --- |
| `action-setup` | Exempt | The integration registers no custom service actions. Climate entity actions are provided by the climate platform. |
| `appropriate-polling` | Satisfied for PoC | `SCAN_INTERVAL` is five minutes. NuHeat is a cloud thermostat service, state changes slowly, and no vendor rate limit has yet justified more frequent polling. Vendor confirmation is still desirable. |
| `brands` | Incomplete | No Home Assistant brands repository entry exists yet. This requires the final domain and upstream path. |
| `common-modules` | Satisfied | Shared constants, coordinator behavior, OAuth setup, and uncertain mode mappings are separated rather than duplicated across platforms. |
| `config-flow-test-coverage` | Incomplete | Mocked tests cover missing/local/cloud implementations, OAuth success, duplicate prevention, authentication and connection failures, temporary implementation failure, reauthentication, and account mismatch. A formal Core coverage run is still required before claiming full coverage. |
| `config-flow` | Satisfied for PoC | Setup uses `AbstractOAuth2FlowHandler`; no YAML configuration is accepted. Local Application Credentials are the development fallback. |
| `dependency-transparency` | Incomplete for Core | The library source, license, metadata, and tests are present, but the package is intentionally unpublished and therefore cannot yet be pinned in a Core manifest. Ownership and release policy are undecided. |
| `docs-actions` | Exempt | No custom service actions are provided. Standard climate actions are documented by Home Assistant. |
| `docs-triggers` | Exempt | The integration provides no custom triggers. |
| `docs-conditions` | Exempt | The integration provides no custom conditions. |
| `docs-high-level-description` | Satisfied for PoC | The README describes NuHeat/Chemelex, the cloud architecture, supported thermostat state, and known limitations. Official Home Assistant user documentation remains a Core prerequisite. |
| `docs-installation-instructions` | Satisfied for development | The README documents editable-library installation, custom-component copying, Application Credentials, and OAuth setup. Official installation will change with Cloud Account Linking. |
| `docs-removal-instructions` | Satisfied for development | The README documents config-entry removal, restart, component removal, and editable-package uninstall without touching legacy entries. |
| `entity-event-setup` | Satisfied | The coordinator listener used for dynamic entities is registered through `entry.async_on_unload`. Coordinator shutdown is tied to the config entry. |
| `entity-unique-id` | Satisfied | Every climate entity uses the thermostat serial number as its stable unique ID. |
| `has-entity-name` | Satisfied | The climate entity sets `_attr_has_entity_name = True`. |
| `runtime-data` | Satisfied | `NuHeatConfigEntry` is typed as `ConfigEntry[NuHeatRuntimeData]`, and the API, coordinator, and OAuth session are stored in `entry.runtime_data`. |
| `test-before-configure` | Satisfied | OAuth completion calls the v2 Account endpoint before creating the config entry and maps authentication/connection errors to translated abort reasons. |
| `test-before-setup` | Satisfied | Setup validates/refreshes the OAuth token and performs `async_config_entry_first_refresh`; authentication failures require reauthentication and temporary cloud failures retry setup. |
| `unique-config-entry` | Satisfied | The normalized account username is the provisional unique ID and duplicate setup is rejected. A vendor-provided immutable account identifier is still preferred. |

## Additional readiness requested for review

These items include Silver/Gold behavior or general maintainer expectations and
do not change the incomplete Bronze conclusion above.

| Item | Status | Evidence or remaining work |
| --- | --- | --- |
| Reauthentication available through UI | Implemented and tested | `async_step_reauth` and `async_step_reauth_confirm` relaunch the saved OAuth implementation; wrong-account reauthentication is rejected. |
| Authentication failures trigger reauthentication | Implemented and tested | Setup and coordinator refresh translate rejected OAuth/API authorization into `ConfigEntryAuthFailed`. |
| Setup and polling failure handling | Implemented and tested | Temporary setup failures become `ConfigEntryNotReady`; polling errors become `UpdateFailed`; authorization failures become `ConfigEntryAuthFailed`. |
| Config entry unloading | Implemented and tested | `async_unload_entry` unloads all forwarded platforms. |
| Stable device identifiers | Implemented | `DeviceInfo.identifiers` uses `(DOMAIN, serial_number)` and also exposes the serial number. Final domain choice can affect migration strategy. |
| Device unavailability | Implemented and tested | Offline or temporarily omitted thermostats remain registered and become unavailable. |
| Dynamic entity discovery | Implemented and tested | Later coordinator data adds new serial numbers without duplicates or reloads. |
| User-facing translations | Implemented for PoC | Custom config-flow aborts, reauthentication text, Application Credentials instructions, and invalid-preset exceptions exist in `strings.json` and `translations/en.json`. Core-provided OAuth aborts use Core translations. |
| Entity writes | Implemented and tested | Target writes test Celsius and Fahrenheit HA installations; Auto/Hold/Manual preset mappings are tested. Setpoint mode semantics still require vendor validation. |
| Test coverage | Incomplete for a tier claim | Tests cover setup, unload, config flow, OAuth refresh and rotation, coordinator updates, discovery, availability, entity state, and writes. A formal current-Core coverage report and maintainer review are still required. |

## Conclusion

Do not add a `quality_scale` claim yet. At minimum, branding, a published and
pinned dependency, formal config-flow/code coverage, official documentation,
and maintainer review remain incomplete.
