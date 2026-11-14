# Getting started

This is the short setup path. The [README](../README.md) contains the full list
of cloud profiles, entities, options and limitations.

## Before installing

- Confirm the air conditioner uses an AEH-W4E1-family legacy Ayla LAN module.
  The hardware-verified model for this project is the **Hisense TQ25XE0CG**.
- Pair the unit to its OEM mobile app if you plan to retrieve the LAN key with
  the cloud flow.
- Ensure Home Assistant can reach the module on TCP port 80 and that the module
  can connect back to Home Assistant.
- Reserve the module's DHCP address when possible. Automatic relocation by MAC
  is available only when setup stored a MAC address (normally the cloud flow).

## Install with HACS

1. In HACS (or the Home Assistant Marketplace), search for
   **Hisense AEH-W4E1** and download it.
2. Restart Home Assistant.
3. Open **Settings → Devices & services → Add integration** and select it.

If it does not appear in search results yet, add it as a custom repository:
open **Custom repositories** in HACS, add `https://github.com/mobot95/Hisense-AEH-W4E1`
as an **Integration**, then download it and restart Home Assistant.

When testing an unpublished working tree, copy `custom_components/aeh_w4e1`
over the installed copy yourself, keep a backup of the previous directory and
restart Home Assistant.

## Add one air conditioner

Choose **Cloud** for a first setup. Select the exact OEM app/region used for the
unit, enter those app credentials and choose the device returned by Ayla. The
credentials are used for that flow only and are not stored.

Choose **Manual** when you already have:

- the module's current IPv4 address and HTTP port (normally 80);
- `lanip_key` and `lanip_key_id`;
- the temperature unit reported by the module.

Repeat the flow for each additional air conditioner.

## First verification

After the encrypted callback succeeds, the climate entity should become
available. Check these items before changing options:

1. Power and mode from Home Assistant reach the physical unit.
2. A change made with the remote appears in Home Assistant.
3. Target and room temperature use the correct unit.
4. Fan, vertical swing and horizontal swing move independently.
5. The entry reconnects after a Home Assistant restart.

If the entity remains unavailable, the usual cause is the reverse connection:
the module can answer Home Assistant on port 80 but cannot reach the advertised
Home Assistant IP/server port. Set a fixed port and advertised IPv4 address in
the integration options when firewall or VLAN rules require them.
