<p align="center">
  <img src="https://raw.githubusercontent.com/mobot95/Hisense-AEH-W4E1/main/docs/images/logo.png" alt="Hisense" width="360">
</p>

# Hisense AEH-W4E1 for Home Assistant

[![GitHub release](https://img.shields.io/github/v/release/mobot95/Hisense-AEH-W4E1.svg?style=flat-square)](https://github.com/mobot95/Hisense-AEH-W4E1/releases)
[![Validation](https://img.shields.io/github/actions/workflow/status/mobot95/Hisense-AEH-W4E1/validate.yml?branch=main&style=flat-square)](https://github.com/mobot95/Hisense-AEH-W4E1/actions/workflows/validate.yml)
[![Home Assistant](https://img.shields.io/badge/Home_Assistant-2026.10%2B-41bdf5?style=flat-square)](https://www.home-assistant.io/)
[![License](https://img.shields.io/badge/License-GPL--3.0-blue.svg?style=flat-square)](https://github.com/mobot95/Hisense-AEH-W4E1/blob/main/LICENSE)

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=mobot95&repository=Hisense-AEH-W4E1&category=integration)

This custom integration controls air conditioners that use the legacy Ayla LAN
protocol found in the Hisense AEH-W4E1 family of Wi-Fi modules. Once the LAN key
has been obtained, commands and status updates stay on the local network: there
is no add-on, MQTT bridge or cloud polling service to keep running.

I built and tested the integration with a **Hisense TQ25XE0CG**. That is the only
air-conditioner model I currently list as hardware-verified. Other units may
work when they expose the same Ayla properties, but a supported cloud login does
not by itself prove that the air conditioner uses the supported LAN protocol.

Version 1.0.0 supports **Home Assistant 2026.10 and newer**. Supported
versions are verified on 2026.10.4 (physical unit) and 2026.11.1 (automated
suite). Take a Home Assistant backup before upgrading a working installation.

The automated suite runs against Home Assistant 2026.11.1. Startup, encrypted
state updates and the corrected off-to-new-mode sequence were also verified on
the Hisense TQ25XE0CG with Home Assistant 2026.10.4.

## What is verified, and what is only expected to work

| Status | Device or module |
|---|---|
| Hardware tested | Hisense **TQ25XE0CG** with the AEH-W4E1 integration |
| Protocol target | Hisense **AEH-W4E1** and compatible legacy Ayla LAN modules |
| Expected, not hardware tested here | AEH-W4B1 and OEM units exposing the same properties and LAN exchange |
| Not implemented | Modules that use the newer, incompatible Ayla protocol (including the AEH-W4A1/W4G1 families) |

If your model works, please open an issue with the exact indoor-unit model,
Wi-Fi module, app name and Home Assistant version. That is enough to expand the
verified list without guessing from brand names.

## How the local connection works

The Wi-Fi module does not expose a conventional control API. Home Assistant
registers a callback address with `http://<module>/local_reg.json`; the module
then connects back to Home Assistant, performs an Ayla key exchange and polls an
encrypted command queue. State changes are pushed back over the same channel.

The integration therefore needs traffic in both directions:

- Home Assistant to the module on TCP port 80;
- the module to Home Assistant on the integration's LAN server port.

The server uses a free system-assigned port by default. A fixed port is only
needed for VLAN or firewall rules. The module's registration request is renewed
every 10 seconds by default, while a complete property refresh is queued every
10 minutes. Remote-control changes normally arrive immediately as push updates.

The cloud is used only during the optional setup flow that retrieves the
per-device `lanip_key`. The username and password are not saved in the config
entry. Normal operation does not call the Ayla cloud.

## Cloud login profiles in the code

These are the exact app profiles implemented in `ayla_cloud.py`. “Region” is the
Ayla endpoint selected by that profile; it is not a statement about where a
particular air-conditioner model was sold.

| Profile | App shown during setup | Region |
|---|---|---|
| `beko-eu` | Beko | EU |
| `denali-us` | Denali Aire | US |
| `fglair-cn` | FGLair (Fujitsu) | China |
| `fglair-eu` | FGLair (Fujitsu) | EU |
| `fglair-us` | FGLair (Fujitsu) | US |
| `field-us` | HiSmart Air | US |
| `haxxair` | HAXXAIR | US fallback |
| `hisense-eu` | HiSmart Life (Hisense EU) | EU |
| `hisense-us` | HiSmart Home (Hisense US) | US |
| `hismart-eu` | Smart-Living | EU |
| `hismart-us` | AI-Home | US |
| `huihe-us` | SunHome | US |
| `mid-eu` | WiFi AC | EU |
| `mid-us` | Smiling Air | US |
| `oem-eu` | Hi-Smart AC | EU |
| `oem-us` | Hisense (OEM US) | US |
| `tornado-us` | Tornado WiFi | US |
| `winia-us` | Winia HomeSmart | US |
| `wwh-us` | Westinghouse | US |
| `york-us` | YORK Smart | US |

The list is derived from the app ID/secret mappings in the repository. It means
the login request can be built for those apps; most profiles have not been
tested by this project's maintainer with a physical unit.

## Features

The main climate entity provides:

- off, fan-only, heat, cool, dry and auto modes;
- target and room temperature;
- auto, quiet, low, medium, high and maximum fan speeds;
- independent vertical and horizontal swing controls;
- Eco, fast heat/cool, 8 °C heat and sleep curves 1–4.

Additional entities include:

- display backlight and silent-mode switches;
- display-power and double-frequency switches, disabled by default;
- humidity and room-temperature sensors;
- voltage and electricity diagnostics, disabled by default;
- filter-cleaning and aggregate fault binary sensors.

The implementation supports both individual `t_*` properties and firmware
that combines its main settings in the `t_control_value` bitmap.

## Installation

### HACS

1. In HACS (or the Home Assistant Marketplace), search for
   **Hisense AEH-W4E1** and download it.
2. Restart Home Assistant.
3. Go to **Settings → Devices & services → Add integration** and search for
   **Hisense AEH-W4E1**.

If it does not appear in search results yet, add it as a custom repository and
retry:

1. Open HACS, choose **Custom repositories** from the menu and add
   `https://github.com/mobot95/Hisense-AEH-W4E1` as an **Integration**.
2. Download **Hisense AEH-W4E1** and restart Home Assistant.

When updating to a new version, redownload the integration in HACS and
restart Home Assistant: existing config entries and entities are kept.

## Setup

Choose one setup method per air conditioner:

- **Cloud (one time)**: choose the OEM app profile, enter the same credentials
  used by that app and select the device. The flow stores the LAN key, current
  IP, MAC, DSN and model data, but not the credentials.
- **Manual**: enter a name, IP address, HTTP port, `lanip_key`,
  `lanip_key_id` and the temperature unit reported by the device.

Repeat the flow for additional units. The local HTTP server is shared when the
entries use the same server-port option.

### Options

| Option | Default | Valid values and use |
|---|---:|---|
| LAN server port | `0` | `0` asks the operating system for a free port; use `1–65535` only for a fixed firewall rule. |
| Advertised local IP | automatic | An IPv4 address on the module's subnet. Set it when Home Assistant has several interfaces or VLANs. |
| Full status refresh | 600 s | Minimum 60 s. Push updates still arrive between refreshes. |
| Keep-alive | 10 s | Minimum 5 s. Lower values add traffic without improving normal operation. |
| Scan network | inferred `/24` | Optional IPv4 CIDR used for lost-device recovery and the scan action. The largest accepted range is `/22`. |

## Network recovery and known limits

- A command is not released from the queue until the source address has been
  confirmed by a valid encrypted exchange.
- After repeated registration failures, an entry created through the cloud
  flow is searched by MAC address. Scans are retried while the device remains
  unreachable. A newly learned IP is persisted only after the module
  authenticates at that address.
- Manual entries do not contain a MAC address, so they cannot be relocated by
  MAC. Give those units a DHCP reservation or use **Reconfigure** after an IP
  change.
- There is no SSDP, Zeroconf or other native announcement in this protocol.
  The `scan_network` action is an explicit subnet probe, not automatic setup of
  unknown devices; a LAN key is still required.
- Some modules reject registration with HTTP 403 when the advertised Home
  Assistant address is outside the module's subnet. Routed VLANs may therefore
  need an address/interface on the device subnet, not only an open firewall.
- The `/status.json` fingerprint used for recovery is empirical. Scan results
  expose only IP, normalized MAC and a small allow-list of model/build fields;
  keys and device serial numbers are not placed on the event bus.

## Actions and event

- `aeh_w4e1.send_command` writes a raw writable property. Numeric values and
  enum names such as `ON`, `OFF`, `COOL` and `LOW` are accepted.
- `aeh_w4e1.request_status_refresh` queues all known properties for refresh.
- `aeh_w4e1.scan_network` probes the configured/inferred subnet and fires
  `aeh_w4e1_scan_completed` with a `modules` list.

The first two actions accept entity, device or config-entry targets. For
backward compatibility, omitting the target applies them to every loaded entry;
new automations should always select a target explicitly.

Example automation:

```yaml
automation:
  - alias: Refresh bedroom AC after the router starts
    triggers:
      - trigger: homeassistant
        event: start
    actions:
      - delay: "00:01:00"
      - action: aeh_w4e1.request_status_refresh
        target:
          entity_id: climate.bedroom
```

## Troubleshooting

### The entity stays unavailable

Check both network directions. A successful request to port 80 is not enough:
the module must also reach Home Assistant on the bound LAN server port. With a
fixed port, confirm that nothing else is listening on it. With several network
interfaces, set the advertised local IP explicitly.

### Cloud login fails

Confirm that the selected profile matches the mobile app and region actually
used to pair the unit. A valid account on a different Hisense/OEM app uses a
different Ayla application identity and will be rejected. Also confirm that the
unit appears in the OEM app and currently has a LAN IP.

### The unit was paired again and now reports an unknown key ID

Pairing to another account can replace the LAN key. Open the integration entry,
choose **Reconfigure**, and enter the new key values (or remove and add the
entry again through the one-time cloud flow).

### Sleep does not change immediately

Sleep curves use the separate `t_sleep` property even on bitmap-capable
firmware. Some firmware confirms that write slowly, so the integration retries
it for about 90 seconds and stops as soon as the module reports the requested
curve.

Diagnostics are available from the integration menu. LAN keys, key IDs, IPs,
MAC addresses, DSNs and network options are redacted.

## Removing or rolling back

Remove each config entry from **Settings → Devices & services**, then remove the
integration from HACS and restart Home Assistant. Removing an entry does not
unpair the air conditioner from its OEM app.

To roll back to a previous version, download that release in HACS again and
restart Home Assistant; the config entries and entity IDs are preserved.

## Development and project status

```bash
python3.14 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check .
.venv/bin/pytest tests -q --cov=custom_components.aeh_w4e1 --cov-report=term
```

The repository includes protocol-level unit tests and an end-to-end simulated
module; the same suite runs in CI on every change. See
[CHANGELOG.md](CHANGELOG.md) for the release history.

This custom integration does **not** claim an official Home Assistant Gold or
Platinum tier. Those tiers require every rule in the lower levels as well, a
`quality_scale.yaml` review in Home Assistant Core and, among other things,
full config-flow tests, more than 95% coverage and strict typing.

## License and credits

Licensed under the [GNU General Public License v3.0](LICENSE).

The OEM app secret/ID mappings in `ayla_cloud.py` are derived from the GPL-3.0
[AirCon](https://github.com/deiger/AirCon) project; details are in [NOTICE](NOTICE).
The LAN server, Home Assistant entities and the rest of this integration are an
independent implementation. This project is not affiliated with Hisense, Ayla
Networks, Fujitsu or any of the OEM brands listed above.
