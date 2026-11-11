"""Local LAN HTTP server that AEH-W4E1 modules connect to.

Endpoints (Ayla LAN mode):
  - POST /local_lan/key_exchange.json       (module -> us)
  - GET  /local_lan/commands.json           (module polls us)
  - POST /local_lan/property/datapoint.json (module pushes updates)
        plus /ack and /node/ variants.

Devices are matched primarily by `lanip_key_id` at key exchange (the
authoritative identity), secondarily by source IP, and finally — for
datapoint pushes — by attempting decryption with each registered device's
session keys, which re-binds the IP map when modules have swapped addresses.
The server itself is Home Assistant-free and testable standalone; the
integration binds it to a port chosen per the port policy (OS-assigned by
default) and wires the callbacks to the issue registry.
"""

import logging
from collections.abc import Callable

from aiohttp import web

from .const import COMMANDS_PATH, DATAPONT_PATHS, KEY_EXCHANGE_PATH
from .device import AehW4e1Device

_LOGGER = logging.getLogger(__name__)

Callbacks = dict[str, Callable]


class LanServer:
    """Shared aiohttp application serving all configured devices on one port."""

    def __init__(self, port: int, callbacks: Callbacks | None = None) -> None:
        self.port = port
        self.bound_port = port  # updated by the binder (0 = OS-assigned)
        self._callbacks = callbacks or {}
        self._devices_by_key_id: dict[int, AehW4e1Device] = {}
        self._devices_by_ip: dict[str, AehW4e1Device] = {}

        self.app = web.Application()
        self.app.add_routes(
            [
                web.post(KEY_EXCHANGE_PATH, self._key_exchange_handler),
                web.get(COMMANDS_PATH, self._commands_handler),
                *(web.post(path, self._datapoint_handler) for path in DATAPONT_PATHS),
            ]
        )

    # ------------------------------------------------------------ registration

    @property
    def device_count(self) -> int:
        return len(self._devices_by_key_id)

    def register(self, device: AehW4e1Device) -> None:
        self._devices_by_key_id[device.config.lanip_key_id] = device
        if device.config.host:
            self._devices_by_ip.setdefault(device.config.host, device)

    def unregister(self, device: AehW4e1Device) -> None:
        if self._devices_by_key_id.get(device.config.lanip_key_id) is device:
            self._devices_by_key_id.pop(device.config.lanip_key_id, None)
        if self._devices_by_ip.get(device.config.host) is device:
            self._devices_by_ip.pop(device.config.host, None)

    def _bind_ip(self, device: AehW4e1Device, ip: str) -> None:
        """Re-bind the source-IP map after a positively identified contact."""
        current = self._devices_by_ip.get(ip)
        if current is device:
            return
        if current is not None:
            _LOGGER.warning(
                "IP %s moved from %s to %s", ip, current.config.name, device.config.name
            )
            self._devices_by_ip.pop(ip, None)
        self._devices_by_ip[ip] = device
        device.handle_peer_ip(ip)

    # ---------------------------------------------------------------- handlers

    async def _key_exchange_handler(self, request: web.Request) -> web.Response:
        data = await request.json()
        key = data.get("key_exchange", {})
        try:
            key_id = int(key["key_id"])
        except (KeyError, TypeError, ValueError):
            _LOGGER.warning("Malformed key exchange from %s", request.remote)
            return web.Response(status=400, text="Invalid key exchange")
        device = self._devices_by_key_id.get(key_id)
        if device is None:
            # Unknown module: it may belong to another host, or its key was
            # replaced. Reply 404 as the module expects for unknown ids.
            _LOGGER.info("Key exchange from %s with unknown key_id %s", request.remote, key_id)
            if callback := self._callbacks.get("unknown_key_id"):
                callback(key_id, request.remote)
            return web.Response(status=404, text="Unknown key id")
        try:
            reply = device.handle_key_exchange(key)
        except (ValueError, KeyError, TypeError) as ex:
            _LOGGER.error("Invalid key exchange from %s: %s", request.remote, ex)
            return web.Response(status=400, text="Invalid key exchange")
        self._bind_ip(device, request.remote)
        return web.json_response(reply)

    async def _commands_handler(self, request: web.Request) -> web.Response:
        device = self._devices_by_ip.get(request.remote)
        if device is None:
            # Single-device servers can serve by elimination; on multi-device
            # setups an unknown source cannot be trusted with commands.
            if len(self._devices_by_key_id) == 1:
                device = next(iter(self._devices_by_key_id.values()))
            else:
                _LOGGER.debug("Commands poll from unknown IP %s", request.remote)
                return web.Response(status=404, text="Unknown device")
        return web.json_response(device.session.encrypt_message(device.handle_commands_request()))

    async def _datapoint_handler(self, request: web.Request) -> web.Response:
        data = await request.json()
        device = self._devices_by_ip.get(request.remote)
        decrypted = None
        if device is not None:
            decrypted = device.try_decrypt_update(data)
        if decrypted is None:
            # Source-IP mapping stale (IPs swapped): try every device session;
            # a valid signature is cryptographic proof of identity.
            for candidate in self._devices_by_key_id.values():
                decrypted = candidate.try_decrypt_update(data)
                if decrypted is not None:
                    device = candidate
                    _LOGGER.info(
                        "Datapoint from %s attributed to %s by signature",
                        request.remote,
                        candidate.config.name,
                    )
                    break
        if decrypted is None or device is None:
            _LOGGER.error(
                "Failed to decrypt/validate datapoint from %s", request.remote
            )
            if callback := self._callbacks.get("invalid_datapoint"):
                callback(request.remote)
            return web.Response(status=400, text="Invalid signature")
        self._bind_ip(device, request.remote)
        try:
            device.handle_property_update(decrypted)
        except Exception:  # noqa: BLE001 - never break the module's poll loop
            _LOGGER.exception("Failed to handle property update")
        return web.Response(status=200)
