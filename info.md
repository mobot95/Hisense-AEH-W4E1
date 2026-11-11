# Hisense AEH-W4E1

Local, cloud-free control of air conditioners equipped with the **Hisense AEH-W4B1 / AEH-W4E1** WiFi module (Ayla Networks LAN mode).

## Highlights

- **Fully local** — after a one-time setup, no add-on, no MQTT bridge and no cloud.
- **Real-time state** (`local_push`) — the module pushes changes immediately, including remote-control usage.
- **Full climate feature set** — modes, target/ambient temperature, fan speeds, vertical & horizontal swing, and presets (Eco, fast cool/heat, 8° heat, sleep curves 1–4).
- **Self-healing network** — DHCP IP changes, disconnects and key replacements are detected and recovered automatically.
- **Gold quality scale**, shared aiohttp session, fully async, strict typing.

## Requirements

- Home Assistant 2024.12 or newer.
- The AC must have been paired to its OEM app **once** (the LAN key comes from there).
- Static or DHCP-reserved IP recommended.

## Installation

Install via HACS as a custom repository (category *Integration*), then restart Home Assistant and add **Hisense AEH-W4E1** from *Settings → Devices & services*.

See the [README](README.md) for full documentation and [Getting started](docs/GETTING_STARTED.md) for a step-by-step setup guide.