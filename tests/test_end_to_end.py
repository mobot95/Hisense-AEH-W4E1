"""End-to-end test: a fake AEH-W4E1 module speaking the full Ayla LAN
protocol (local_reg registration, key exchange, command polling, datapoint
pushes) against the integration's LanServer and device runtime."""

import asyncio
import base64
import json
import secrets
import string
import time
from typing import Any

from aiohttp import ClientSession, web

from custom_components.aeh_w4e1.device import AehW4e1Device, DeviceConfig
from custom_components.aeh_w4e1.encryption import LanEncryption
from custom_components.aeh_w4e1.lan_server import LanServer
from custom_components.aeh_w4e1.protocol import AC_PROPERTIES

LAN_KEY = "GT2V4DKATESTKEY0"
LAN_KEY_ID = 4242


async def _wait_until(condition, timeout=5.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        await asyncio.sleep(interval)
    return False


class FakeAcModule:
    """Simulates the WiFi module side of the Ayla LAN protocol."""

    def __init__(self, server_port: int) -> None:
        self.server_port = server_port
        self.received_writes: list[tuple[str, Any]] = []
        self.pushed_properties: dict[str, Any] = {}
        self.local_reg_calls = 0
        self._registered = asyncio.Event()
        self._updates_seq = 0
        self._session: ClientSession | None = None
        self._runner: web.AppRunner | None = None
        self._port = 0
        self._task: asyncio.Task | None = None
        self._app_enc: LanEncryption | None = None
        self._dev_enc: LanEncryption | None = None

    async def start(self) -> None:
        app = web.Application()
        # Real modules accept both POST (first registration) and PUT (keep-alive).
        app.router.add_route("POST", "/local_reg.json", self._handle_local_reg)
        app.router.add_route("PUT", "/local_reg.json", self._handle_local_reg)
        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        site = web.TCPSite(self._runner, "127.0.0.1", 0)
        await site.start()
        self._port = self._runner.addresses[0][1]
        self._session = ClientSession()
        self._task = asyncio.create_task(self._module_loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
        if self._session:
            await self._session.close()
        if self._runner:
            await self._runner.cleanup()

    async def _handle_local_reg(self, request: web.Request) -> web.Response:
        body = await request.json()
        assert body["local_reg"]["ip"] == "127.0.0.1"
        assert body["local_reg"]["port"] == self.server_port
        assert body["local_reg"]["uri"] == "/local_lan"
        self.local_reg_calls += 1
        self._registered.set()
        return web.Response(status=202)

    async def _module_loop(self) -> None:
        await self._registered.wait()
        await self._key_exchange()
        while True:
            await asyncio.sleep(0.05)
            try:
                await self._poll_commands()
            except asyncio.CancelledError:
                raise
            except Exception as ex:  # keep the module loop alive
                await asyncio.sleep(0.2)

    async def _key_exchange(self) -> None:
        random_1 = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(16))
        time_1 = int(time.time() * 1000) % 2**40
        async with self._session.post(
            f"http://127.0.0.1:{self.server_port}/local_lan/key_exchange.json",
            json={
                "key_exchange": {
                    "ver": 1,
                    "proto": 1,
                    "key_id": LAN_KEY_ID,
                    "random_1": random_1,
                    "time_1": time_1,
                }
            },
        ) as resp:
            assert resp.status == 200, await resp.text()
            reply = await resp.json()
        random_2, time_2 = reply["random_2"], str(reply["time_2"])
        key = LAN_KEY.encode()
        # Device -> server messages use the "dev" direction.
        self._dev_enc = LanEncryption(
            key, (random_2 + random_1 + time_2 + str(time_1)).encode()
        )
        # Server -> device messages use the "app" direction.
        self._app_enc = LanEncryption(
            key, (random_1 + random_2 + str(time_1) + time_2).encode()
        )

    async def _poll_commands(self) -> None:
        async with self._session.get(
            f"http://127.0.0.1:{self.server_port}/local_lan/commands.json"
        ) as resp:
            if resp.status != 200:
                return
            encrypted = await resp.json()
        plain = json.loads(self._app_enc.decrypt_signed(encrypted))
        payload = plain.get("data") or {}
        # Ayla write format: {"properties": [{"property": {...}}]}
        for wrapper in payload.get("properties", []):
            prop = wrapper["property"]
            self.received_writes.append((prop["name"], prop["value"]))
        for cmd in payload.get("cmds", []):
            resource = cmd["cmd"]["resource"]
            name = resource.split("name=")[1]
            if name in self.pushed_properties:
                await self._push_datapoint(name, self.pushed_properties[name])

    async def _push_datapoint(self, name: str, value: Any) -> None:
        self._updates_seq += 1
        body = {
            "seq_no": self._updates_seq,
            "data": {
                "name": name,
                "value": value,
                "base_type": AC_PROPERTIES[name].base_type,
                "ack": False,
                "id": "abcd1234",
            },
        }
        async with self._session.post(
            f"http://127.0.0.1:{self.server_port}/local_lan/property/datapoint.json",
            json=self._dev_enc.encrypt_signed(json.dumps(body).encode()),
        ) as resp:
            assert resp.status == 200, await resp.text()

    async def push_property(self, name: str, value: Any) -> None:
        """Unsolicited state push, like a real module does on local changes."""
        self.pushed_properties[name] = value
        await self._push_datapoint(name, value)


async def _start_lan_server() -> tuple[LanServer, web.AppRunner, int]:
    server = LanServer(0)
    runner = web.AppRunner(server.app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = runner.addresses[0][1]
    return server, runner, port


def _make_device(server_port: int, device_port: int) -> AehW4e1Device:
    config = DeviceConfig(
        name="Test AC",
        host="127.0.0.1",
        lanip_key=LAN_KEY,
        lanip_key_id=LAN_KEY_ID,
        temp_unit="C",
        device_port=device_port,
        server_port=server_port,
        local_ip="127.0.0.1",
        refresh_interval=600,
        keepalive_interval=1,
    )
    return AehW4e1Device(config)


async def test_full_lan_conversation():
    server, runner, server_port = await _start_lan_server()
    module = FakeAcModule(server_port)
    await module.start()
    device = _make_device(server_port, module._port)
    server.register(device)

    updates: list[tuple[str, Any]] = []
    availability: list[bool] = []
    device.set_callbacks(
        on_update=lambda name, value: updates.append((name, value)),
        on_availability=availability.append,
    )
    await device.start()
    try:
        # 1. The module registers and the device becomes available.
        assert await _wait_until(lambda: device.available), "device never became available"
        assert availability[-1] is True
        assert module.local_reg_calls >= 1

        # 2. A command reaches the fake module through the encrypted channel.
        await device.send_command("t_power", "OFF")
        assert await _wait_until(
            lambda: any(n == "t_power" for n, _ in module.received_writes)
        ), f"module never received the t_power write: {module.received_writes}"
        power_write = next(v for n, v in module.received_writes if n == "t_power")
        assert power_write == 0  # OFF, encoded as boolean base type value 0

        # 3. Optimistic state: the runtime reflects the queued write.
        assert device.get("t_power") == 0

        # 4. The module pushes sensor values (unsolicited, like a real module
        # reporting a remote-control change); the runtime applies them.
        await module.push_property("f_temp_in", 81.5)
        await module.push_property("f_humidity", 55)
        assert await _wait_until(lambda: device.get("f_humidity") == 55)
        assert device.get("f_temp_in") == 81.5
        assert ("f_humidity", 55) in updates
        assert ("f_temp_in", 81.5) in updates

        # 5. Status refresh queues GETs; the module answers and state updates.
        device.queue_status_refresh()
        module.pushed_properties["t_temp"] = 24
        assert await _wait_until(lambda: device.get("t_temp") == 24)

        # 6. A second write flows after the first (queue keeps working).
        await device.send_command("t_temp", 20)
        assert await _wait_until(
            lambda: any(n == "t_temp" for n, _ in module.received_writes)
        )
        temp_write = next(
            v for n, v in reversed(module.received_writes) if n == "t_temp"
        )
        assert temp_write == 20
        assert device.get("t_temp") == 20
    finally:
        await device.stop()
        await module.stop()
        await runner.cleanup()


async def test_unknown_module_gets_404():
    server, runner, server_port = await _start_lan_server()
    session = ClientSession()
    try:
        async with session.post(
            f"http://127.0.0.1:{server_port}/local_lan/key_exchange.json",
            json={
                "key_exchange": {
                    "ver": 1,
                    "proto": 1,
                    "key_id": 1,
                    "random_1": "abcdef0123456789",
                    "time_1": 1,
                }
            },
        ) as resp:
            assert resp.status == 404
    finally:
        await session.close()
        await runner.cleanup()


async def test_property_update_with_bad_signature_rejected():
    server, runner, server_port = await _start_lan_server()
    module = FakeAcModule(server_port)
    await module.start()
    device = _make_device(server_port, module._port)
    server.register(device)
    await device.start()
    try:
        assert await _wait_until(lambda: device.available)

        # Tamper with a valid datapoint push: value must not be applied.
        await module.push_property("f_humidity", 55)
        assert await _wait_until(lambda: device.get("f_humidity") == 55)

        device_updates: list = []
        device.set_callbacks(
            on_update=lambda name, value: device_updates.append((name, value)),
            on_availability=lambda available: None,
        )
        module._updates_seq += 1
        tampered = {
            "seq_no": module._updates_seq,
            "data": {"name": "f_humidity", "value": 99, "base_type": "integer", "ack": False},
        }
        encrypted = dict(module._dev_enc.encrypt_signed(json.dumps(tampered).encode()))
        encrypted["sign"] = "AAAA" + encrypted["sign"][4:]
        async with module._session.post(
            f"http://127.0.0.1:{server_port}/local_lan/property/datapoint.json",
            json=encrypted,
        ) as resp:
            assert resp.status == 400
        assert device.get("f_humidity") == 55
    finally:
        await device.stop()
        await module.stop()
        await runner.cleanup()
