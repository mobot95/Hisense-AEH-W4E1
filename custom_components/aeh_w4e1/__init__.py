"""The Hisense AEH-W4E1 air conditioner integration.

Native Home Assistant control of Hisense-based ACs with an AEH-W4B1/W4E1
WiFi module (Ayla Networks LAN mode) over a direct local connection: no
add-on and no MQTT bridge. The module connects *to* Home Assistant (key
exchange, command polling, status pushes); we keep the registration alive
and recover automatically from network changes.
"""

import asyncio
import ipaddress
import logging
from ipaddress import IPv4Network
from typing import Any

from aiohttp import web

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.issue_registry import IssueSeverity, async_create_issue
from homeassistant.helpers.service import async_extract_config_entry_ids
import voluptuous as vol

from .const import (
    CONF_DEVICE_PORT,
    CONF_DSN,
    CONF_KEEPALIVE_INTERVAL,
    CONF_LANIP_KEY,
    CONF_LANIP_KEY_ID,
    CONF_LOCAL_IP,
    CONF_MAC,
    CONF_MODEL,
    CONF_REFRESH_INTERVAL,
    CONF_SCAN_NETWORK,
    CONF_SERVER_PORT,
    CONF_SW_VERSION,
    CONF_TEMP_UNIT,
    DEFAULT_DEVICE_PORT,
    DEFAULT_KEEPALIVE_INTERVAL,
    DEFAULT_MODEL,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_SERVER_PORT,
    DOMAIN,
    ISSUE_PORT_BIND_FAILED,
    ISSUE_UNKNOWN_KEY_ID,
    SERVICE_REQUEST_STATUS_REFRESH,
    SERVICE_SCAN_NETWORK,
    SERVICE_SEND_COMMAND,
    SIGNAL_AVAILABLE,
    SIGNAL_UPDATE,
)
from .device import AehW4e1Device, DeviceConfig
from .lan_server import LanServer
from .protocol import AC_PROPERTIES, PropertyError, convert_value
from .scanner import DiscoveredModule, infer_network, scan_subnet

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ("binary_sensor", "climate", "sensor", "switch")


def _runtime_config(entry: ConfigEntry) -> DeviceConfig:
    return DeviceConfig(
        name=entry.data.get("name", "Air Conditioner"),
        host=entry.data[CONF_HOST],
        lanip_key=entry.data[CONF_LANIP_KEY],
        lanip_key_id=int(entry.data[CONF_LANIP_KEY_ID]),
        temp_unit=entry.data.get(CONF_TEMP_UNIT, "C"),
        device_port=int(entry.data.get(CONF_DEVICE_PORT, DEFAULT_DEVICE_PORT)),
        server_port=int(entry.options.get(CONF_SERVER_PORT, DEFAULT_SERVER_PORT)),
        local_ip=str(entry.options.get(CONF_LOCAL_IP, "") or ""),
        refresh_interval=float(
            entry.options.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL)
        ),
        keepalive_interval=float(
            entry.options.get(CONF_KEEPALIVE_INTERVAL, DEFAULT_KEEPALIVE_INTERVAL)
        ),
        mac=str(entry.data.get(CONF_MAC) or ""),
        dsn=str(entry.data.get(CONF_DSN) or ""),
        model=str(entry.data.get(CONF_MODEL) or ""),
        sw_version=str(entry.data.get(CONF_SW_VERSION) or ""),
    )


def _get_store(hass: HomeAssistant) -> dict[str, Any]:
    store = hass.data.setdefault(DOMAIN, {})
    store.setdefault("devices", {})
    store.setdefault("servers", {})
    store.setdefault("scan_task", None)
    store.setdefault("scan_listeners", [])
    return store


# --------------------------------------------------------------- LAN server


async def _async_start_server(
    hass: HomeAssistant, requested_port: int
) -> tuple[LanServer, int]:
    """Start the shared LAN server for a requested port; returns server + bound port.

    With the default `requested_port == 0` the OS assigns a free port, so a
    conflict with another service is impossible unless the user explicitly
    pins a port. The actually-bound port is advertised to the modules in the
    keep-alive registration.
    """
    servers: dict[int, tuple[LanServer, web.AppRunner]] = _get_store(hass)["servers"]
    if requested_port in servers:
        server, _ = servers[requested_port]
        return server, server.bound_port

    server = LanServer(requested_port, callbacks=_server_callbacks(hass))
    runner = web.AppRunner(server.app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=requested_port, reuse_address=True)
    try:
        await site.start()
    except OSError as ex:
        await runner.cleanup()
        if requested_port == 0:
            raise HomeAssistantError(
                f"Could not start the AEH-W4E1 LAN server: {ex}"
            ) from ex
        # Explicit port busy: raise a repair issue so the user can decide
        # (change the port, or free it) without losing the integration.
        async_create_issue(
            hass,
            DOMAIN,
            f"{ISSUE_PORT_BIND_FAILED}_{requested_port}",
            is_fixable=False,
            severity=IssueSeverity.ERROR,
            translation_key=ISSUE_PORT_BIND_FAILED,
            translation_placeholders={"port": str(requested_port), "error": str(ex)},
        )
        raise HomeAssistantError(
            f"Could not bind the AEH-W4E1 LAN server to port {requested_port}: {ex}. "
            "Leave the port option empty to let the system pick a free port."
        ) from ex
    server.bound_port = runner.addresses[0][1]
    servers[requested_port] = (server, runner)
    _LOGGER.info(
        "AEH-W4E1 LAN server listening on port %d (requested %s)",
        server.bound_port,
        requested_port or "auto",
    )
    return server, server.bound_port


async def _async_stop_server_if_idle(hass: HomeAssistant, requested_port: int) -> None:
    servers = _get_store(hass)["servers"]
    holder = servers.get(requested_port)
    if holder and holder[0].device_count == 0:
        server, runner = servers.pop(requested_port)
        await runner.cleanup()
        _LOGGER.debug("Stopped AEH-W4E1 LAN server (requested port %s)", requested_port)
        _ = server


def _server_callbacks(hass: HomeAssistant) -> dict:
    """Callbacks the LAN server uses to surface protocol anomalies."""

    def on_unknown_key_id(key_id: int, ip: str) -> None:
        async_create_issue(
            hass,
            DOMAIN,
            f"{ISSUE_UNKNOWN_KEY_ID}_{ip}",
            is_fixable=False,
            severity=IssueSeverity.WARNING,
            translation_key=ISSUE_UNKNOWN_KEY_ID,
            translation_placeholders={"key_id": str(key_id), "ip": ip},
        )

    return {"unknown_key_id": on_unknown_key_id}


# ------------------------------------------------------------------ scanning


def _first_runtime_config(hass: HomeAssistant) -> DeviceConfig | None:
    devices: dict[str, AehW4e1Device] = _get_store(hass)["devices"]
    for device in devices.values():
        return device.config
    return None


def _scan_options(hass: HomeAssistant) -> str:
    """Optional CIDR override for targeted scans (first entry that sets it wins)."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.options.get(CONF_SCAN_NETWORK):
            return str(entry.options[CONF_SCAN_NETWORK])
    return ""


def _scan_config(hass: HomeAssistant) -> IPv4Network | None:
    """Resolve the network used by targeted scans (rediscovery, service)."""
    custom = _scan_options(hass)
    config = _first_runtime_config(hass)
    if config is None:
        return None
    if custom:
        try:
            return ipaddress.ip_network(custom, strict=False)
        except ValueError:
            _LOGGER.warning("Invalid scan network CIDR: %s", custom)
    return infer_network(config.local_ip or config.host)


async def _async_run_scan(hass: HomeAssistant, include_known: bool) -> list[DiscoveredModule]:
    """Scan the inferred/custom network; returns discovered modules (manual)."""
    store = _get_store(hass)
    network = _scan_config(hass)
    if network is None:
        return []
    session = async_get_clientsession(hass)
    known_macs = None
    if not include_known:
        known_macs = {
            d.config.mac.lower() for d in store["devices"].values() if d.config.mac
        }
    return await scan_subnet(session, network, known_macs)


async def _async_rediscover(hass: HomeAssistant, device: AehW4e1Device) -> None:
    """Find an already-configured module's new IP after keep-alive failures.

    This is *not* new-device discovery (which requires the cloud-provisioned
    LAN key anyway): it only relocates a unit we already own by its MAC.
    """
    network = _scan_config(hass)
    if network is None:
        return
    session = async_get_clientsession(hass)
    _LOGGER.info("%s: unreachable, scanning %s for its MAC", device.config.name, network)
    try:
        found = await scan_subnet(session, network, known_macs=None)
    except (OSError, asyncio.TimeoutError):
        return
    target_mac = device.config.mac.lower()
    match = None
    for module in found:
        if module.mac == target_mac:
            match = module
            break
    if match is not None and match.ip != device.config.host:
        _LOGGER.info(
            "%s: found again at %s (was %s); re-registering",
            device.config.name,
            match.ip,
            device.config.host,
        )
        device.handle_peer_ip(match.ip)
    elif match is not None:
        # Same IP: retry registration right away.
        device.handle_peer_ip(device.config.host)


# -------------------------------------------------------------------- setup


async def async_setup(hass: HomeAssistant, config) -> bool:
    """Register integration-level services."""
    _get_store(hass)

    async def _target_devices(call: ServiceCall) -> list[AehW4e1Device]:
        devices: dict[str, AehW4e1Device] = _get_store(hass)["devices"]
        entry_ids = await async_extract_config_entry_ids(call)
        targeted = [devices[eid] for eid in entry_ids if eid in devices]
        return targeted or list(devices.values())

    async def handle_send_command(call: ServiceCall) -> None:
        name = call.data["property"]
        value = call.data["value"]
        try:
            typed = convert_value(name, value)
        except PropertyError as ex:
            raise HomeAssistantError(str(ex)) from ex
        for device in await _target_devices(call):
            await device.send_command(name, typed)

    async def handle_refresh(call: ServiceCall) -> None:
        for device in await _target_devices(call):
            device.queue_status_refresh()

    async def handle_scan(call: ServiceCall) -> None:
        found = await _async_run_scan(hass, include_known=True)
        hass.bus.async_fire(
            f"{DOMAIN}_scan_completed",
            {"modules": [{"ip": m.ip, "mac": m.mac, **m.extra} for m in found]},
        )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SEND_COMMAND,
        handle_send_command,
        schema=vol.Schema(
            {
                vol.Required("property"): vol.In(sorted(AC_PROPERTIES)),
                vol.Required("value"): cv.string,
            }
        ),
    )
    hass.services.async_register(DOMAIN, SERVICE_REQUEST_STATUS_REFRESH, handle_refresh)
    hass.services.async_register(DOMAIN, SERVICE_SCAN_NETWORK, handle_scan)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one AC from a config entry."""
    store = _get_store(hass)
    requested_port = int(entry.options.get(CONF_SERVER_PORT, DEFAULT_SERVER_PORT))
    device = AehW4e1Device(_runtime_config(entry))
    signal_update = SIGNAL_UPDATE.format(domain=DOMAIN, entry_id=entry.entry_id)
    signal_available = SIGNAL_AVAILABLE.format(domain=DOMAIN, entry_id=entry.entry_id)
    device.set_callbacks(
        on_update=lambda name, value: async_dispatcher_send(hass, signal_update, name, value),
        on_availability=lambda available: async_dispatcher_send(hass, signal_available, available),
        on_lost=lambda: hass.async_create_task(_async_rediscover(hass, device)),
        on_heartbeat=lambda: async_dispatcher_send(hass, signal_available, device.available),
    )

    server, bound_port = await _async_start_server(hass, requested_port)
    # The device must advertise the *bound* port (OS-assigned when 0).
    device.config.server_port = bound_port
    server.register(device)
    await device.start(session=async_get_clientsession(hass))

    store["devices"][entry.entry_id] = device
    store.setdefault("server_by_entry", {})[entry.entry_id] = requested_port

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload one AC config entry."""
    store = _get_store(hass)
    device: AehW4e1Device | None = store["devices"].pop(entry.entry_id, None)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if device is not None:
        requested_port = store.get("server_by_entry", {}).pop(entry.entry_id, None)
        holder = store["servers"].get(requested_port) if requested_port is not None else None
        if holder is not None:
            holder[0].unregister(device)
        await device.stop()
        if requested_port is not None:
            await _async_stop_server_if_idle(hass, requested_port)
    return unload_ok


def async_get_device(hass: HomeAssistant, entry_id: str) -> AehW4e1Device | None:
    return _get_store(hass)["devices"].get(entry_id)


