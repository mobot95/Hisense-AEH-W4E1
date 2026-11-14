"""Climate-entity compatibility and temperature-state tests."""

from types import SimpleNamespace

from homeassistant.const import UnitOfTemperature

from custom_components.aeh_w4e1.climate import AehW4e1Climate
from custom_components.aeh_w4e1.const import CONF_TEMP_UNIT
from custom_components.aeh_w4e1.device import AehW4e1Device, DeviceConfig


def _climate(temp_unit: str = "C") -> tuple[AehW4e1Climate, AehW4e1Device]:
    device = AehW4e1Device(
        DeviceConfig(
            name="Test AC",
            host="192.0.2.10",
            lanip_key="GT2V4DKATESTKEY0",
            lanip_key_id=1,
            temp_unit=temp_unit,
        )
    )
    entry = SimpleNamespace(entry_id="test-entry", data={CONF_TEMP_UNIT: temp_unit})
    return AehW4e1Climate(entry, device), device


def test_climate_uses_native_temperature_api():
    climate, device = _climate()
    device._properties["t_temp"] = 23
    device._properties["f_temp_in"] = 22.5

    assert climate.native_temperature_unit == UnitOfTemperature.CELSIUS
    assert climate.native_target_temperature == 23.0
    assert climate.native_current_temperature == 22.5
    assert "target_temperature" not in AehW4e1Climate.__dict__
    assert "current_temperature" not in AehW4e1Climate.__dict__


def test_climate_fahrenheit_range_and_unknown_temperatures():
    climate, _device = _climate("F")

    assert climate.native_temperature_unit == UnitOfTemperature.FAHRENHEIT
    assert climate.native_target_temperature is None
    assert climate.native_current_temperature is None
    assert climate.min_temp == 61
    assert climate.max_temp == 86
