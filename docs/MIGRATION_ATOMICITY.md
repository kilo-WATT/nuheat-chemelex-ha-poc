# Migration failure boundaries

The legacy-to-OAuth migration is staged and rollback-aware, but it is not a
database transaction. Home Assistant does not provide one transaction spanning
config entries, the entity registry, and the device registry, and removing a
config entry does not provide a supported way to recreate the same entry ID.

## Core patterns reviewed

Current Home Assistant integrations that consolidate entries update entity
`config_entry_id` associations through the entity registry, add/remove device
config-entry associations through the device registry, and then call
`ConfigEntries.async_remove`. Repair issues are the established way to expose a
persistent condition that cannot be repaired automatically. Those APIs do not
share a rollback primitive or transaction boundary.

NuHeat therefore uses four explicit stages:

1. `build_migration_plan` performs remote-account validation and captures
   detached, immutable snapshots without mutating Home Assistant.
2. `validate_migration_plan` checks that entries and registry records are still
   exactly as planned immediately before execution.
3. `execute_migration_plan` transfers ownership, converts the anchor, marks
   redundant entries as inert cleanup stubs, reloads the anchor, and verifies
   every expected thermostat before removal begins.
4. `rollback_migration_plan` restores original associations and config-entry
   fields if any reversible stage fails.

## Preflight and reversible rollback

The authenticated v2 account must contain the initiating serial. Every matching
legacy entry must have a valid serial, registry ownership must be either the
expected legacy entry or the selected anchor, devices must have the exact
NuHeat identifier, all planned entries must still exist, and no duplicate OAuth
account entry may have appeared. A preflight failure performs no mutation.

Before cleanup, rollback restores the original entity and device associations
on the same registry record IDs. It also restores anchor and redundant entry
data, title, unique ID, and version. Consequently, entity IDs and user registry
customizations are not recreated. If restoration itself fails, the integration
logs a credential-free error and creates the translated
`migration_rollback_failed` repair issue. At that point the supported recovery
is the Home Assistant backup made before migration.

## Irreversible removal boundary

Redundant entries are not removed until the OAuth anchor reloads successfully,
its coordinator contains every remotely validated serial, and each existing
entity/device is owned by the anchor. Until the first successful
`async_remove`, all local mutations are treated as reversible.

The first successfully removed redundant config entry is the irreversible
boundary. The integration does not attempt to recreate an entry with a new ID
and call that rollback. If a later removal fails, the valid OAuth anchor and
registry ownership remain in place, remaining redundant entries stay as
non-secret, inert cleanup markers, and a translated
`migration_cleanup_incomplete` repair issue is created.

## Restart and retry behavior

The anchor marker contains only migration state and validated serial numbers.
Cleanup stubs contain only the anchor entry ID and thermostat serial. They do
not call the obsolete service, create entities, or retain credentials.

On the next successful anchor setup, cleanup revalidates coordinator and
registry ownership, absorbs any matching legacy entry left by interruption,
and retries removal idempotently. The marker and repair issue are cleared only
after cleanup converges. A retry after a successful pre-boundary rollback starts
from the original entries and can build a fresh plan.

An operating-system or storage failure can still interrupt separate Home
Assistant writes, and a failure after the removal boundary cannot restore the
old entry ID. A full Home Assistant backup remains required before live
migration testing.
