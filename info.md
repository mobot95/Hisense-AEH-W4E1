# Hisense AEH-W4E1

Local Home Assistant control for air conditioners using the legacy Ayla LAN
protocol found in AEH-W4E1-family Wi-Fi modules.

The integration has been hardware-tested with a **Hisense TQ25XE0CG**. Other
models and OEM brands should be treated as unverified until their exact unit,
module and property set have been reported.

## Highlights

- Local encrypted control after the LAN key has been obtained.
- Push updates for remote-control changes.
- HVAC modes, temperature, fan, two-axis swing, Eco, fast heat/cool, 8 °C heat
  and four sleep curves.
- One-time cloud key retrieval for the app profiles listed in the README, or
  fully manual setup when the key is already known.
- Diagnostics, repair issues and MAC-based address recovery for cloud-created
  entries.

Version 1.0.0 targets Home Assistant 2026.11. Read the
[full README](README.md) and the [setup guide](docs/GETTING_STARTED.md).

This custom integration is not officially rated Gold or Platinum on the Home
Assistant Integration Quality Scale; it follows those practices where they apply
to a custom integration.
