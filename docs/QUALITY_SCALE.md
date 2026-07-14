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
| `brands` | Incomplete | The existing `nuheat` domain is retained, but branding changes still require review in the Home Assistant brands repository. |
| `common-modules` | Satisfied | Shared constants, coordinator behavior, OAuth setup, and uncertain mode mappings are separated rather than duplicated across platforms. |
| `config-flow-test-coverage` | Incomplete | Mocked tests cover missing/local/cloud implementations, fresh OAuth, duplicate prevention, authentication and connection failures, reauthentication, legacy detection, wrong-account rollback, one/multiple-entry migration, existing-account consolidation, and partial discovery. A formal Core coverage run is still required before claiming full coverage. |
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
| `test-before-configure` | Satisfied | OAuth completion calls both v2 Account and Thermostat endpoints before creating or converting an entry and maps authentication/connection errors to translated abort reasons. |
| `test-before-setup` | Satisfied | Setup validates/refreshes the OAuth token and performs `async_config_entry_first_refresh`; authentication failures require reauthentication and temporary cloud failures retry setup. |
| `unique-config-entry` | Satisfied | The normalized account username is the provisional unique ID and duplicate setup is rejected. A vendor-provided immutable account identifier is still preferred. |

## Additional readiness requested for review

These items include Silver/Gold behavior or general maintainer expectations and
do not change the incomplete Bronze conclusion above.

| Item | Status | Evidence or remaining work |
| --- | --- | --- |
| Reauthentication available through UI | Implemented and tested | OAuth entries use `async_step_reauth_confirm`; version-1 legacy entries use a translated migration confirmation before OAuth. Wrong-account reauthentication/migration is rejected without mutation. |
| Authentication failures trigger reauthentication | Implemented and tested | Setup and coordinator refresh translate rejected OAuth/API authorization into `ConfigEntryAuthFailed`. |
| Setup and polling failure handling | Implemented and tested | Temporary setup failures become `ConfigEntryNotReady`; polling errors become `UpdateFailed`; authorization failures become `ConfigEntryAuthFailed`. |
| Config entry unloading | Implemented and tested | `async_unload_entry` unloads all forwarded platforms. |
| Stable device identifiers | Implemented and migration-tested | `DeviceInfo.identifiers` remains `(nuheat, serial_number)`. Registry tests prove the same device ID, user name, area, and identifiers survive config-entry consolidation. |
| Device unavailability | Implemented and tested | Offline or temporarily omitted thermostats remain registered and become unavailable. |
| Dynamic entity discovery | Implemented and tested | Later coordinator data adds new serial numbers without duplicates or reloads. |
| User-facing translations | Implemented for PoC | Custom config-flow aborts, legacy migration/reauthentication text, Application Credentials instructions, migration-required setup exception, and invalid-preset exception exist in `strings.json` and `translations/en.json`. |
| Entity writes | Implemented and tested | Target writes test Celsius and Fahrenheit; legacy `AUTO`/`HEAT` and title-cased presets map to v2 Auto/Hold/Manual. Hold expiration still requires live validation. |
| Legacy identity preservation | Implemented and tested | Tests retain a deliberately customized `climate.master_bath_floor`, its unique ID, custom name/icon/labels/area/disabled state, and its original device record and customization. Config-entry ownership moves before redundant removal. |
| Migration rollback | Implemented and failure-tested | Immutable preflight rejects changed entries, duplicates, and unrelated registry owners before mutation. Injected failures at entity/device transfer, anchor update/reload/verification, and first cleanup restore original entries and associations. A rollback failure creates a translated repair issue without logging secrets. The first successful redundant-entry removal is explicitly irreversible. |
| Migration restart and cleanup | Implemented and failure-tested | Non-sensitive anchor/stub markers make interrupted conversion and partial post-boundary cleanup idempotently resumable. Pending stubs never call the obsolete API or create duplicate entities. A persistent translated repair issue remains until cleanup converges. |
| Test coverage | Incomplete for a tier claim | Tests cover setup, unload, config flow, OAuth refresh/rotation, coordinator updates, discovery, availability, entity writes, legacy migration, consolidation, duplicate prevention, registry ownership, customization, injected rollback failures, the removal boundary, and restart/retry convergence. Formal coverage and maintainer review remain required. |

## Conclusion

Do not add a `quality_scale` claim yet. At minimum, branding, a published and
pinned dependency, formal config-flow/code coverage, official documentation,
and maintainer review remain incomplete.
