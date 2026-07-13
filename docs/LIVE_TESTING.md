# Safe live-testing plan

Live testing must use a disposable Home Assistant development instance and a
legitimate OAuth registration supplied by Chemelex. Back up the instance before
testing. Never test a mode or command whose effect is not understood on a
freeze-protection, safety-critical, or otherwise sensitive installation.

## Matrix

Record pass, fail, not supported, or not tested for each applicable combination.

| Area | Cases | What to verify |
| --- | --- | --- |
| Thermostat family | Signature; Conductor | Discovery, naming, serial identity, read values, commands, and availability. |
| Account size | One thermostat; multiple thermostats | Complete initial discovery, unique entities, correct commands per serial. |
| Units | HA Celsius; HA Fahrenheit; NuHeat account preference Celsius/Fahrenheit | Current/target values match physical thermostat; writes return the intended physical setpoint. The API payload is still centi-Celsius. |
| Modes | Auto; Hold; Manual | Reported preset, command result, target value, hold expiry, and schedule behavior. |
| Standby | Enter; report; leave, only if an official endpoint is documented | Confirm exact API state and safe HA mapping before implementing Off. |
| Setpoint write | Increase; decrease; boundary-adjacent normal values | Displayed value, centi-Celsius payload, resulting mode, and thermostat display. |
| OAuth expiry | Expired access token | Exactly one refresh and successful retry without user action. |
| Refresh rotation | Provider returns a new refresh token | New token remains usable after restart; old token is not restored. |
| Revocation | Revoked/rejected refresh token | Entry requests reauthentication without a retry loop. |
| Offline | Disconnect one thermostat | Entity becomes unavailable and is not removed or duplicated. |
| Dynamic discovery | Add a thermostat after setup | Entity appears after a later poll without reloading the integration. |
| Temporary omission | API list omits a known thermostat once | Existing entity remains registered and becomes unavailable until it returns. |

## Procedure

1. Record Home Assistant version, integration commit, thermostat family/model,
   firmware version if visible, account size, and configured HA temperature unit.
2. Capture the physical thermostat's displayed current temperature, target, and
   mode before each test.
3. Enable the sanitized debug logging configuration from the README.
4. Perform one matrix action at a time and wait for the API/UI state to settle.
5. Record expected versus observed behavior and whether a restart or next poll
   changed the result.
6. Disable debug logging and review every attachment before submitting a report.

## Safe report contents

Testers should report only:

- Home Assistant version and installation type;
- repository commit SHA and integration domain;
- thermostat product family and model;
- firmware version, if the thermostat exposes it;
- number of thermostats, using aliases such as `device-a` and `device-b`;
- HA configured temperature unit and NuHeat UI/account preference;
- sanitized endpoint path and HTTP status, without query strings or headers;
- expected and observed temperatures/modes/timestamps;
- whether the device was online and whether the action reached the thermostat;
- a minimal sanitized log excerpt with opaque identifiers replaced consistently.

Never request or report:

- access tokens, refresh tokens, ID tokens, authorization codes, or OAuth state;
- client IDs or client secrets;
- NuHeat passwords or Home Assistant credentials;
- `Authorization`, cookie, or complete request headers;
- unredacted config-entry data or `.storage` files;
- complete API response bodies;
- email addresses, physical addresses, thermostat serial numbers, device IDs,
  account IDs, or personally identifying room names.

When redacting, preserve stable relationships with labels (`serial-a`,
`account-a`) rather than partial real values.
