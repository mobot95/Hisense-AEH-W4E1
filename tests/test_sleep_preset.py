"""Regression tests for sleep preset handling on bitmap-capable firmware.

The AEH-W4E1 (Smart-1 and friends) reports the aggregated `t_control_value`
bitmap for the main settings, but the sleep curve (`t_sleep`) is a separate
property: it must always be written to its own property, never as a bare
`t_control_value`. A bare `t_control_value` write makes the module echo a
non-bitmap value, which must be ignored rather than decoded.
"""

import asyncio
import time

from custom_components.aeh_w4e1.device import AehW4e1Device, DeviceConfig
from custom_components.aeh_w4e1.protocol import SleepMode


def _make_device() -> AehW4e1Device:
    config = DeviceConfig(
        name="Test AC",
        host="127.0.0.1",
        lanip_key="GT2V4DKATESTKEY0",
        lanip_key_id=4242,
    )
    device = AehW4e1Device(config)
    # Simulate a bitmap-capable module: the aggregated bitmap is known.
    device._properties["t_control_value"] = 3015232
    device.last_contact = time.monotonic()
    return device


def _queued_writes(device: AehW4e1Device) -> list[tuple[str, int]]:
    writes: list[tuple[str, int]] = []
    for command in device._commands:
        for wrapper in command.payload.get("properties", []):
            prop = wrapper["property"]
            writes.append((prop["name"], prop["value"]))
    return writes


async def _cancel_retry(device: AehW4e1Device) -> None:
    if device._sleep_retry_task is not None:
        device._sleep_retry_task.cancel()
        await asyncio.gather(device._sleep_retry_task, return_exceptions=True)


async def test_set_sleep_writes_t_sleep_property():
    device = _make_device()
    try:
        await device.set_sleep(SleepMode.ONE)
        writes = _queued_writes(device)
        assert ("t_sleep", 1) in writes
        # The bare t_control_value channel must never be used for sleep.
        assert all(name != "t_control_value" for name, _ in writes)
        # The runtime state is updated optimistically.
        assert device.get("t_sleep") == 1
    finally:
        await _cancel_retry(device)


async def test_clear_sleep_writes_t_sleep_zero():
    device = _make_device()
    device._properties["t_sleep"] = 3
    try:
        await device.set_sleep(SleepMode.STOP)
        writes = _queued_writes(device)
        assert ("t_sleep", 0) in writes
        assert all(name != "t_control_value" for name, _ in writes)
        assert device.get("t_sleep") == 0
    finally:
        await _cancel_retry(device)


async def test_non_bitmap_control_value_echo_is_ignored():
    device = _make_device()
    # A command echo with an invalid fan-speed field must not crash the
    # decoder nor overwrite the cached bitmap.
    device._apply_update("t_control_value", 808321603)
    assert device.get("t_control_value") == 3015232