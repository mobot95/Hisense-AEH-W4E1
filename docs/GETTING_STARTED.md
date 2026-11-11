# Getting started

This guide walks you through setting up the Hisense AEH-W4E1 integration end to end.

## What you need

- Home Assistant **2024.12 or newer**.
- An air conditioner with an **AEH-W4B1 / AEH-W4E1** WiFi module.
- The AC **paired once** to its OEM app (Hisense / Beko / Westinghouse / …). This is required only to obtain the LAN key; afterwards the integration is fully local.
- A **static or DHCP-reserved IP** for the AC (recommended).

## 1. Install

1. In HACS go to *⋮ → Custom repositories*.
2. Add this repository with category *Integration*.
3. Find **Hisense AEH-W4E1** and click *Download*.
4. Restart Home Assistant.

## 2. Add the integration

Go to *Settings → Devices & services → Add integration* and choose **Hisense AEH-W4E1**.

You are offered two setup methods. Pick the one that fits:

| Method | When to use it |
|---|---|
| **Cloud (one-time, default)** | First-time setup: sign in with the OEM app credentials and pick the device; the key and IP are fetched automatically. |
| **Manual** | You already know the IP, `lanip_key` and `lanip_key_id`. |

Repeat the flow once per air conditioner (each unit gets its own config entry; the local LAN server is shared).

## 3. Getting the LAN key without the cloud

If you prefer not to use the cloud method, you need the `lanip_key` from a previous local setup:

- **Manual** — enter the values directly.

## 4. Verify

After setup you should see:

- `climate.<name>` with modes, target/ambient temperature, fan speeds, swing and presets.
- `switch.<name>_backlight` and `switch.<name>_silent_mode`.
- `sensor.<name>_humidity` and `sensor.<name>_room_temperature`.
- `binary_sensor.<name>_filter_needs_cleaning` and `binary_sensor.<name>_fault`.

State changes pushed by the remote control or the OEM app are reflected in Home Assistant within seconds (`local_push`).

## Troubleshooting

### The module rejects registration with `403`

The module refuses registrations whose advertised IP is on a different subnet. If HA has multiple network interfaces, open the integration options and set **Advertised IP** (`local_ip`) to an address on the AC's subnet.

### The entity is unavailable

Check that HA can reach the AC on port `80/TCP` and that the AC can reach HA on the LAN server port (automatic, or pinned in the options). A DHCP IP change is recovered automatically; verify the AC's reserved IP is correct.

### "Key replaced" / unknown module repair issue

If the module was re-paired to a different app account, the LAN key changed. Reconfigure the entry with the new `lanip_key` / `lanip_key_id`.

### The AC does not react to sleep presets

The sleep curves are controlled by the `t_sleep` property, not by the aggregated bitmap. If you are on an older version of the integration, update to the latest release where this is handled correctly.