"""Runtime state machine for one AEH-W4E1 device.

In Ayla LAN mode the air conditioner connects *to us*: we register with the
module via `POST/PUT /local_reg.json` (keep-alive every ~10 s) and the module
then polls `/local_lan/commands.json` for commands and pushes encrypted
property updates to `/local_lan/property/datapoint.json`.

This module is intentionally free of Home Assistant imports so it can be
exercised standalone; the integration package wires its callbacks to the
dispatcher and the entity platforms. An external aiohttp session can be
injected (Home Assistant's shared session) or one is created internally.
"""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
import heapq
import logging
import socket
import time
from typing import Any

import aiohttp

from .bitmap import BITMAP_PROPERTIES, SettingsBitmap
from .encryption import LanSession
from .protocol import (
    AC_PROPERTIES,
    AcWorkMode,
    AirFlow,
    EightHeat,
    Economy,
    FanSpeed,
    FastColdHeat,
    Power,
    PropertyError,
    Quiet,
    SleepMode,
    TemperatureUnit,
    build_read_command,
    build_write_command,
    convert_value,
    normalize_name,
)

_LOGGER = logging.getLogger(__name__)

# Command queue priorities: writes are dispatched before status polls.
PRIORITY_COMMAND = 10
PRIORITY_STATUS = 100

# Keep-alive retry behavior: up to 6 attempts with exponential backoff,
# then the device is considered unreachable and rediscovery may kick in.
MAX_FAILURES = 6
BACKOFF_BASE = 1.6
BACKOFF_MAX = 10.0

# How long after a positively-authenticated contact (key exchange or a
# validated datapoint) we consider an IP binding trustworthy for writes.
BINDING_TRUST_SECONDS = 900.0

# Delay before the first full status poll after startup (seconds).
FIRST_REFRESH_DELAY = 30.0

# t_control_value echoes: bare values 0..4 are command echoes (not real
# bitmaps) and must never be stored as the cached bitmap. Real bitmaps
# always carry present-flag bits and are far larger.
SLEEP_COMMAND_MAX = 4


@dataclass(order=True)
class _Command:
    priority: int
    order: int
    payload: dict = field(compare=False)
    updater: Callable[[], None] | None = field(compare=False)


@dataclass
class DeviceConfig:
    name: str
    host: str
    lanip_key: str
    lanip_key_id: int
    temp_unit: str = "C"  # Unit the device reports t_temp/f_temp_in in.
    device_port: int = 80  # Port of the module's own HTTP server (local_reg).
    server_port: int = 0  # Port of our LAN server the module connects to.
    local_ip: str = ""  # IP we advertise to the module; empty = auto-detect.
    refresh_interval: float = 600.0
    keepalive_interval: float = 10.0
    mac: str = ""
    dsn: str = ""
    model: str = ""
    sw_version: str = ""


class AehW4e1Device:
    """State, command queue and LAN keep-alive loop for a single AC unit."""

    def __init__(self, config: DeviceConfig) -> None:
        self.config = config
        self.session = LanSession(config.lanip_key, config.lanip_key_id)
        self._on_update: Callable[[str, Any], None] = lambda name, value: None
        self._on_availability: Callable[[bool], None] = lambda available: None
        self._on_heartbeat: Callable[[], None] = lambda: None
        self._on_lost: Callable[[], None] = lambda: None

        self._properties: dict[str, Any] = {
            # Control-value capable models signal it by reporting the bitmap;
            # until then commands use the individual t_* properties.
            "t_control_value": None,
        }
        self._commands: list[_Command] = []
        self._command_order = 0
        self._command_seq_no = 0
        self._cmd_id = 0
        self._updates_seq_no = 0

        self.available = False
        self.last_contact = 0.0  # monotonic ts of last authenticated contact
        self._lost_reported = False
        self._last_reg = 0.0
        self._local_ip = config.local_ip
        self._wake = asyncio.Event()
        self._sleep_retry_task: asyncio.Task | None = None
        self._sleep_retry_target: int | None = None
        self._sleep_retry_cancelled = False
        self._session: aiohttp.ClientSession | None = None
        self._owns_session = False
        self._tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------------ setup

    @property
    def uses_control_value(self) -> bool:
        return self._properties.get("t_control_value") is not None

    @property
    def binding_is_trusted(self) -> bool:
        """True when the current host IP was confirmed by an encrypted exchange."""
        return (
            self.last_contact > 0
            and time.monotonic() - self.last_contact < BINDING_TRUST_SECONDS
        )

    def set_callbacks(
        self,
        on_update: Callable[[str, Any], None],
        on_availability: Callable[[bool], None],
        on_lost: Callable[[], None] | None = None,
        on_heartbeat: Callable[[], None] | None = None,
    ) -> None:
        self._on_update = on_update
        self._on_availability = on_availability
        if on_lost is not None:
            self._on_lost = on_lost
        if on_heartbeat is not None:
            self._on_heartbeat = on_heartbeat

    async def start(self, session: aiohttp.ClientSession | None = None) -> None:
        """Start the runtime tasks, sharing an existing aiohttp session if given."""
        if session is not None:
            self._session = session
            self._owns_session = False
        else:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=10, connect=5)
            )
            self._owns_session = True
        if not self._local_ip:
            self._local_ip = await asyncio.to_thread(_detect_local_ip, self.config.host)
        self._tasks = [
            asyncio.create_task(self._keepalive_loop(), name=f"{self.config.name}-keepalive"),
            asyncio.create_task(self._refresh_loop(), name=f"{self.config.name}-refresh"),
        ]

    async def stop(self) -> None:
        if self._sleep_retry_task is not None:
            self._sleep_retry_task.cancel()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
        if self._session and self._owns_session:
            await self._session.close()
        self._session = None

    # -------------------------------------------------------- state accessors

    def get(self, name: str) -> Any:
        return self._properties.get(name)

    @property
    def properties_snapshot(self) -> dict[str, Any]:
        return dict(self._properties)

    def get_power(self) -> int:
        control = self.get("t_control_value")
        if control:
            return SettingsBitmap(control).get("t_power")
        return int(self.get("t_power") or 0)

    def get_work_mode(self) -> int:
        control = self.get("t_control_value")
        if control:
            return SettingsBitmap(control).get("t_work_mode")
        return int(self.get("t_work_mode") or 0)

    def get_temperature(self) -> int | None:
        control = self.get("t_control_value")
        if control:
            return SettingsBitmap(control).get("t_temp")
        return self.get("t_temp")

    def get_fan_speed(self) -> int:
        control = self.get("t_control_value")
        if control:
            return SettingsBitmap(control).get("t_fan_speed")
        return int(self.get("t_fan_speed") or 0)

    # ------------------------------------------------------- command queueing

    async def send_command(self, name: str, value) -> None:
        """Queue a property write.

        Models that use `t_control_value` expect the main settings encoded in
        the bitmap; properties outside the bitmap (t_sleep, t_temp_eight,
        t_backlight, ...) are always written to their own property.
        """
        prop = AC_PROPERTIES.get(name)
        if prop is None:
            raise PropertyError(f'Unknown property "{name}"')
        if prop.read_only:
            raise PropertyError(f'Cannot update read-only property "{name}"')

        typed_value = convert_value(name, value)
        if (
            name != "t_control_value"
            and self.uses_control_value
            and name in BITMAP_PROPERTIES
        ):
            await self._send_via_bitmap(name, typed_value)
            return

        payload = build_write_command(name, typed_value)
        self._enqueue(PRIORITY_COMMAND, payload, self._make_optimistic_updater(name, typed_value))
        # Apply the optimistic state immediately: the UI reflects the click
        # right away, and the module confirms/corrects via datapoint pushes
        # when it executes the command.
        self._apply_update(name, typed_value)

    def _make_optimistic_updater(self, name: str, typed_value) -> Callable[[], None]:
        def updater() -> None:
            self._apply_update(name, typed_value)

        return updater

    async def _send_via_bitmap(self, name: str, value) -> None:
        control = self.get("t_control_value") or 0
        updated = SettingsBitmap(control).with_field(name, value)
        await self.send_command("t_control_value", updated.raw)

    def queue_status_refresh(self) -> None:
        """Queue GET commands for every property (device answers via datapoint)."""
        if len(self._commands) > 10:
            _LOGGER.debug(
                "%s: skipping status refresh, command queue is backed up", self.config.name
            )
            return
        for name in AC_PROPERTIES:
            command = build_read_command(name, self._cmd_id)
            self._cmd_id += 1
            self._enqueue(PRIORITY_STATUS, command, None)

    def _enqueue(self, priority: int, payload: dict, updater: Callable[[], None] | None) -> None:
        heapq.heappush(self._commands, _Command(priority, self._command_order, payload, updater))
        self._command_order += 1
        # Wake the keep-alive loop so the module is notified right away.
        self._wake.set()

    # ------------------------------------------------------- high-level setters

    async def set_power(self, value: Power) -> None:
        await self.send_command("t_power", int(value))

    async def set_temperature(self, value: int) -> None:
        await self.send_command("t_temp", int(value))

    async def set_work_mode(self, value: AcWorkMode) -> None:
        await self.send_command("t_work_mode", int(value))

    async def set_fan_speed(self, value: FanSpeed) -> None:
        await self.send_command("t_fan_speed", int(value))

    async def set_fan_vertical(self, value: AirFlow) -> None:
        await self.send_command("t_fan_power", int(value))

    async def set_fan_horizontal(self, value: AirFlow) -> None:
        await self.send_command("t_fan_leftright", int(value))

    async def set_fan_mute(self, value: Quiet) -> None:
        await self.send_command("t_fan_mute", int(value))

    async def set_eco(self, value: Economy) -> None:
        await self.send_command("t_eco", int(value))

    async def set_fast_heat_cold(self, value: FastColdHeat) -> None:
        await self.send_command("t_temp_heatcold", int(value))
        if value == FastColdHeat.ON:
            # The module ignores conflicting settings while fast cool/heat is
            # active; reset them, as the OEM app does.
            await self.send_command("t_fan_speed", int(FanSpeed.AUTO))
            await self.send_command("t_fan_mute", int(Quiet.OFF))
            await self.send_command("t_sleep", int(SleepMode.STOP))
            await self.send_command("t_temp_eight", int(EightHeat.OFF))

    async def set_sleep(self, value: SleepMode) -> None:
        """Select/clear a sleep curve via the ``t_sleep`` property.

        On the Smart-1 firmware (and the AEH-W4E1 family in general) the
        sleep curve is a property of its own: it is *not* part of the
        ``t_control_value`` bitmap. Writing a bare ``t_control_value`` value
        (0..4) does not move the curve and makes the module echo a
        non-bitmap value, so ``t_sleep`` is the only correct channel for
        both setting and clearing.
        """
        target = int(value)
        updater = self._make_sleep_updater(target)
        self._enqueue(PRIORITY_COMMAND, build_write_command("t_sleep", target), updater)
        # Immediate optimistic update: the UI reflects the preset right away.
        updater()
        # The module can take tens of seconds to come back and poll: keep
        # re-sending the write until the device confirms the target value.
        self._schedule_sleep_confirmation(target)

    def _schedule_sleep_confirmation(self, target: int) -> None:
        """Re-send the sleep write until the device confirms the target value."""
        self._sleep_retry_target = target
        self._sleep_retry_cancelled = False
        if self._sleep_retry_task is not None:
            self._sleep_retry_task.cancel()
        self._sleep_retry_task = asyncio.create_task(self._sleep_retry_loop(target))

    async def _sleep_retry_loop(self, target: int) -> None:
        # The firmware can ignore sleep writes for a while right after a
        # sleep-set (verified on hardware), so retries span ~2.5 minutes.
        # The task is cancelled as soon as a device datapoint confirms the
        # target value; the optimistic state alone never counts as success.
        try:
            for delay in (10, 30, 50):
                await asyncio.sleep(delay)
                if self._sleep_retry_cancelled:
                    return
                _LOGGER.info(
                    "%s: device has not confirmed t_sleep=%s yet, retrying",
                    self.config.name,
                    target,
                )
                self._enqueue(
                    PRIORITY_COMMAND, build_write_command("t_sleep", target), None
                )
        except asyncio.CancelledError:
            raise

    def _make_sleep_updater(self, value: int) -> Callable[[], None]:
        def updater() -> None:
            if self._properties.get("t_sleep") != value:
                self._properties["t_sleep"] = value
            self._on_update("t_sleep", value)

        return updater

    async def set_backlight(self, value: int) -> None:
        await self.send_command("t_backlight", int(value))

    # ---------------------------------------------------------- LAN callbacks

    def handle_peer_ip(self, ip: str) -> None:
        """Learn the device's current IP from its connections (DHCP changes)."""
        if ip and ip != self.config.host:
            _LOGGER.info(
                "%s: device IP changed from %s to %s", self.config.name, self.config.host, ip
            )
            self.config.host = ip
            self._last_reg = 0.0  # re-register at the new address promptly
            self._wake.set()

    def mark_authenticated_contact(self) -> None:
        """Record a positively-authenticated contact (used by IP trust rules).

        The first authenticated contact triggers an immediate full status
        poll so entities get real data seconds after the module connects
        instead of waiting for the periodic refresh.
        """
        first_contact = self.last_contact == 0
        self.last_contact = time.monotonic()
        self._lost_reported = False
        if first_contact:
            self.queue_status_refresh()

    def handle_key_exchange(self, key: dict) -> dict:
        """Process a key_exchange request; returns our random_2/time_2 reply."""
        reply = self.session.start_exchange(key)
        self.mark_authenticated_contact()
        _LOGGER.debug("%s: key exchange completed", self.config.name)
        return reply

    def handle_commands_request(self) -> dict:
        """Serve a commands.json poll: one queued command (or empty data).

        Property writes are only served while the IP binding is trustworthy
        (recently confirmed by an authenticated exchange); this prevents a
        stale IP map from delivering a write to the wrong unit when several
        devices share one server. Status polls are always safe to serve.
        """
        payload: dict = {}
        if self._commands:
            command = heapq.heappop(self._commands)
            if "properties" in command.payload and not self.binding_is_trusted:
                # Stale binding: hold writes back until the module re-authenticates.
                heapq.heappush(self._commands, command)
            else:
                payload = command.payload
                if command.updater:
                    command.updater()
                for prop_wrapper in payload.get("properties", []):
                    prop = prop_wrapper["property"]
                    _LOGGER.info(
                        "%s: command delivered to module: %s=%s",
                        self.config.name,
                        prop["name"],
                        prop["value"],
                    )
        self._command_seq_no += 1
        return {"seq_no": self._command_seq_no, "data": payload}

    def handle_property_update(self, decrypted: dict) -> bool:
        """Apply a decrypted datapoint update from the device."""
        self.mark_authenticated_contact()
        seq_no = decrypted.get("seq_no")
        if not self._is_update_valid(seq_no):
            return False
        data = decrypted.get("data") or {}
        if not data:
            _LOGGER.debug("%s: unsupported update message %s", self.config.name, seq_no)
            return False
        name = normalize_name(str(data["name"]))
        if name not in AC_PROPERTIES:
            _LOGGER.warning("%s: ignoring unknown property %s", self.config.name, name)
            return False
        prop = AC_PROPERTIES[name]
        try:
            value = prop.py_type(data["value"])
        except (TypeError, ValueError):
            _LOGGER.warning("%s: bad value %r for %s", self.config.name, data["value"], name)
            return False
        if name in ("t_sleep", "t_control_value"):
            _LOGGER.info(
                "%s: device reports %s=%s",
                self.config.name,
                name,
                value,
            )
        if name == "t_sleep" and value == self._sleep_retry_target:
            self._sleep_retry_cancelled = True
            if self._sleep_retry_task is not None:
                self._sleep_retry_task.cancel()
                self._sleep_retry_task = None
        self._apply_update(name, value)
        return True

    def try_decrypt_update(self, payload: dict) -> dict | None:
        """Attempt to decrypt/validate a datapoint payload with this device's keys.

        Used by the LAN server to (re)attribute messages to devices when the
        source IP mapping may be stale.
        """
        try:
            return self.session.decrypt_message(payload)
        except Exception:  # noqa: BLE001 - wrong device simply fails to decrypt
            return None

    def _apply_update(self, name: str, value) -> None:
        prop = AC_PROPERTIES[name]
        if prop.precision != 1:
            value = round(value * prop.precision)

        if name == "t_control_value":
            if value == self._properties.get(name):
                # Still notify: repeat commands keep the UI coherent.
                self._on_update(name, value)
                return
            # Bare values 0..4 are command echoes, not real bitmaps; a real
            # bitmap is far larger and must decode cleanly. Anything that
            # does not decode is ignored so it cannot corrupt the cached
            # state (the next status refresh restores the authoritative one).
            if value > SLEEP_COMMAND_MAX:
                try:
                    decoded = SettingsBitmap(value).to_properties()
                except ValueError:
                    _LOGGER.info(
                        "%s: ignored non-bitmap t_control_value: %s",
                        self.config.name,
                        value,
                    )
                    return
                self._properties[name] = value
                for decoded_name, decoded_value in decoded.items():
                    if decoded_value != self._properties.get(decoded_name):
                        self._properties[decoded_name] = decoded_value
                        self._on_update(decoded_name, decoded_value)
            self._on_update(name, value)
            return

        if value == self._properties.get(name):
            # Still notify: write commands are optimistic and the entities
            # should render the requested state immediately.
            self._on_update(name, value)
            return
        self._properties[name] = value
        self._on_update(name, value)

    def _is_update_valid(self, cur_update_no) -> bool:
        if cur_update_no is None:
            return False
        # The device occasionally resets its sequence counter; accept that.
        if self._updates_seq_no > cur_update_no and cur_update_no > 0:
            _LOGGER.warning(
                "%s: stale update %s (last %s)",
                self.config.name,
                cur_update_no,
                self._updates_seq_no,
            )
            return False
        self._updates_seq_no = cur_update_no
        return True

    # ------------------------------------------------------------------ loops

    def _set_available(self, available: bool) -> None:
        if self.available != available:
            self.available = available
            self._on_availability(available)

    async def _keepalive_loop(self) -> None:
        failures = 0
        while True:
            now = time.monotonic()
            queue_size = len(self._commands)
            due = (
                queue_size > 0
                or not self.available
                or now - self._last_reg >= self.config.keepalive_interval
            )
            if not due:
                # Idle and healthy: sleep until a command arrives or the
                # next keep-alive falls due.
                self._wake.clear()
                remaining = max(0.1, self.config.keepalive_interval - (now - self._last_reg))
                try:
                    await asyncio.wait_for(self._wake.wait(), timeout=remaining)
                except asyncio.TimeoutError:
                    pass
                continue

            notify = int(queue_size > 0)
            # POST = fresh registration (resets a wedged LAN session on the
            # module); PUT = keep-alive of a healthy, authenticated session.
            # A module whose binding is not confirmed ignores identical PUTs,
            # so it is always re-kicked with a POST until it key-exchanges.
            method = "PUT" if (self.available and self.binding_is_trusted) else "POST"
            dsn_query = f"?dsn={self.config.dsn}" if self.config.dsn else ""
            url = f"http://{self.config.host}:{self.config.device_port}/local_reg.json{dsn_query}"
            body = {
                "local_reg": {
                    "ip": self._local_ip,
                    "notify": notify,
                    "port": self.config.server_port,
                    "uri": "/local_lan",
                }
            }
            try:
                assert self._session is not None
                async with self._session.request(method, url, json=body) as resp:
                    if resp.status in (200, 202):
                        self._last_reg = time.monotonic()
                        failures = 0
                        self._set_available(True)
                        # Heartbeat: entities re-evaluate on every successful
                        # registration, so a transient error can never leave
                        # them stuck in "unavailable".
                        self._on_heartbeat()
                        self._wake.clear()
                        # While commands are pending, re-notify quickly so the
                        # module keeps polling; otherwise wait for the next
                        # keep-alive or an explicit wake-up.
                        if len(self._commands) > 0:
                            await asyncio.sleep(0.2)
                        else:
                            try:
                                await asyncio.wait_for(
                                    self._wake.wait(),
                                    timeout=self.config.keepalive_interval,
                                )
                            except asyncio.TimeoutError:
                                pass
                        continue
                    text = await resp.text()
                    _LOGGER.error(
                        "%s: local_reg failed: %s, %s (a 403 usually means the "
                        "advertised IP is on a different subnet than the module)",
                        self.config.name,
                        resp.status,
                        text[:120],
                    )
                    raise ConnectionError(f"local_reg failed: {resp.status}")
            except (
                aiohttp.ClientError,
                asyncio.TimeoutError,
                ConnectionError,
                AssertionError,
            ) as ex:
                failures += 1
                delay = min(BACKOFF_BASE**failures, BACKOFF_MAX)
                _LOGGER.debug(
                    "%s: failed to register (attempt %d): %s; retrying in %.1fs",
                    self.config.name,
                    failures,
                    ex,
                    delay,
                )
                if failures >= MAX_FAILURES:
                    self._set_available(False)
                    if not self._lost_reported:
                        self._lost_reported = True
                        self._on_lost()
                await asyncio.sleep(delay)

    async def _refresh_loop(self) -> None:
        # First full poll shortly after startup, then on the configured interval.
        await asyncio.sleep(min(FIRST_REFRESH_DELAY, self.config.refresh_interval))
        self.queue_status_refresh()
        while True:
            await asyncio.sleep(self.config.refresh_interval)
            self.queue_status_refresh()


def _detect_local_ip(target: str) -> str:
    """Best-effort detection of the LAN IP that can reach the device."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(0.5)
        sock.connect((target, 9))
        return sock.getsockname()[0]
    except OSError:
        try:
            sock.connect(("10.255.255.255", 1))
            return sock.getsockname()[0]
        except OSError:
            return ""
    finally:
        sock.close()
