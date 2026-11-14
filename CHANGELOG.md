# Changelog

Notable changes are grouped here using the Keep a Changelog structure. The
project follows semantic versioning for published releases.

## [Unreleased]

## [1.0.0] - 2026-11-14

### Added

- Initial public release: local Ayla LAN control for AEH-W4E1-family modules
  with climate, switch, sensor and binary-sensor entities, one-time cloud key
  bootstrap, manual setup, reconfigure flow, diagnostics with redaction,
  repair issues and MAC-based address recovery for cloud-created entries.
- Local encrypted channel with transactional receive-state handling, so a
  datapoint tried against the wrong device key can never corrupt another
  unit's session in multi-unit installations.
- Availability requires an authenticated callback from the module; repeated
  MAC-based rediscovery recovers from address changes, and a new IP is
  persisted only after an authenticated exchange.
- One-time Ayla cloud login with bounded, deterministically closed requests;
  credentials are used for that flow only and are never stored.
- Validated options flow (intervals, ports, IP addresses, scan-network sizes)
  and clear Home Assistant errors for invalid raw enum commands.
- Privacy-conscious diagnostics and scan events: LAN keys, key IDs, addresses
  and identifiers are redacted, and scan results expose only allow-listed
  model/build metadata.
- Push entities on every platform with asynchronous parallel updates, icon
  translations and a voltage device class/unit.
- Climate entities use Home Assistant's native temperature API, with a runtime
  compatibility path for Home Assistant 2026.10 (the legacy API is scheduled
  for removal in Home Assistant 2027.11).
- Mode changes are written while the unit is still off before power-on, so the
  unit never briefly starts in its previously stored mode (verified on the
  Hisense TQ25XE0CG with Smart-1 firmware).
- Brand icon and logo bundled with the integration (`brand/`) so Home
  Assistant and HACS can display them without the central brands repository.
- Regression and import smoke tests for the protocol, encryption, scanner,
  climate behavior and startup ordering, plus CI with tests, Ruff, HACS
  validation and hassfest.
