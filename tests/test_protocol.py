"""Focused regression tests for command conversion and device identity."""

import time

import pytest

from custom_components.aeh_w4e1.ayla_cloud import APP_LABELS, SECRET_MAP
from custom_components.aeh_w4e1.bitmap import SettingsBitmap
from custom_components.aeh_w4e1.device import AehW4e1Device, DeviceConfig
from custom_components.aeh_w4e1.lan_server import LanServer
from custom_components.aeh_w4e1.protocol import AcWorkMode, PropertyError, convert_value


def _device(name: str, host: str, key_id: int) -> AehW4e1Device:
    return AehW4e1Device(
        DeviceConfig(
            name=name,
            host=host,
            lanip_key="GT2V4DKATESTKEY0",
            lanip_key_id=key_id,
        )
    )


def test_raw_command_enum_conversion():
    assert convert_value("t_power", "on") == 1
    assert convert_value("t_fan_speed", "LOW") == 6
    assert convert_value("t_work_mode", "cool") == 2
    assert convert_value("t_temp", "23.4") == 23


def test_invalid_command_value_has_domain_error():
    with pytest.raises(PropertyError, match="Invalid value"):
        convert_value("t_power", "definitely-not-a-state")
    with pytest.raises(PropertyError, match="Invalid value"):
        convert_value("t_temp", "warm")


def test_every_exposed_cloud_profile_has_secret_material():
    assert set(APP_LABELS) == set(SECRET_MAP)


def test_untrusted_ip_change_invalidates_binding():
    device = _device("Living room", "192.0.2.10", 1)
    device.last_contact = time.monotonic()
    device.available = True

    assert device.handle_peer_ip("192.0.2.20") is True
    assert device.config.host == "192.0.2.20"
    assert device.last_contact == 0
    assert device.available is False


def test_server_rebind_removes_stale_ip_and_unregisters_cleanly():
    authenticated_addresses: list[str] = []
    server = LanServer(
        0,
        callbacks={
            "ip_changed": lambda _device, ip: authenticated_addresses.append(ip),
        },
    )
    device = _device("Bedroom", "192.0.2.30", 2)
    server.register(device)

    # Rediscovery may learn the address before the module authenticates. The
    # later authenticated bind must still reach the persistence callback.
    device.handle_peer_ip("192.0.2.31")
    server._bind_ip(device, "192.0.2.31")
    assert "192.0.2.30" not in server._devices_by_ip
    assert server._devices_by_ip["192.0.2.31"] is device
    assert authenticated_addresses == ["192.0.2.31"]

    server.unregister(device)
    assert device not in server._devices_by_ip.values()
    assert server.device_count == 0


async def test_bitmap_hvac_start_sets_mode_before_power():
    device = _device("Studio", "192.0.2.40", 3)
    initial = SettingsBitmap(0).with_field("t_work_mode", int(AcWorkMode.HEAT))
    device._properties["t_control_value"] = initial.with_field("t_power", 0).raw
    device.last_contact = time.monotonic()

    await device.set_hvac_mode(AcWorkMode.COOL)

    assert device.pending_command_count == 2
    first = device.handle_commands_request()["data"]["properties"][0]["property"]["value"]
    second = device.handle_commands_request()["data"]["properties"][0]["property"]["value"]
    assert SettingsBitmap(first).get("t_work_mode") == int(AcWorkMode.COOL)
    assert SettingsBitmap(first).get("t_power") == 0
    assert first & (1 << 8)
    assert not first & (1 << 5)
    assert SettingsBitmap(second).get("t_work_mode") == int(AcWorkMode.COOL)
    assert SettingsBitmap(second).get("t_power") == 1
    assert second & (1 << 5)
    assert not second & (1 << 8)


async def test_legacy_hvac_start_sets_mode_before_power():
    device = _device("Legacy", "192.0.2.41", 4)
    device.last_contact = time.monotonic()

    await device.set_hvac_mode(AcWorkMode.COOL)

    first = device.handle_commands_request()["data"]["properties"][0]["property"]
    second = device.handle_commands_request()["data"]["properties"][0]["property"]
    assert (first["name"], first["value"]) == ("t_work_mode", int(AcWorkMode.COOL))
    assert (second["name"], second["value"]) == ("t_power", 1)
