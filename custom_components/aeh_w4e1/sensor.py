"""Sensor platform for AEH-W4E1 air conditioners."""

import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import async_get_device
from .const import CONF_TEMP_UNIT
from .device import AehW4e1Device
from .entity import AehW4e1Base, device_unique_id

_LOGGER = logging.getLogger(__name__)


def _build_descriptions(device: AehW4e1Device) -> list[SensorEntityDescription]:
    temp_unit = UnitOfTemperature.CELSIUS if device.config.temp_unit == "C" else UnitOfTemperature.FAHRENHEIT
    return [
        SensorEntityDescription(
            key="f_humidity",
            translation_key="humidity",
            device_class=SensorDeviceClass.HUMIDITY,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=PERCENTAGE,
        ),
        SensorEntityDescription(
            key="f_temp_in",
            translation_key="room_temperature",
            device_class=SensorDeviceClass.TEMPERATURE,
            state_class=SensorStateClass.MEASUREMENT,
            native_unit_of_measurement=temp_unit,
            suggested_display_precision=1,
        ),
        SensorEntityDescription(
            key="f_voltage",
            translation_key="voltage",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            state_class=SensorStateClass.MEASUREMENT,
        ),
        SensorEntityDescription(
            key="f_electricity",
            translation_key="electricity",
            entity_category=EntityCategory.DIAGNOSTIC,
            entity_registry_enabled_default=False,
            native_unit_of_measurement=PERCENTAGE,
            state_class=SensorStateClass.MEASUREMENT,
        ),
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device = async_get_device(hass, entry.entry_id)
    if device is None:
        return
    async_add_entities(
        AehW4e1Sensor(entry, device, description) for description in _build_descriptions(device)
    )


class AehW4e1Sensor(AehW4e1Base, SensorEntity):
    """A read-only `f_*` property exposed as a sensor."""

    def __init__(
        self,
        entry: ConfigEntry,
        device: AehW4e1Device,
        description: SensorEntityDescription,
    ) -> None:
        self._device = device
        self._entry_id = entry.entry_id
        self.entity_description = description
        self._attr_unique_id = f"{device_unique_id(device)}-{description.key}"

    @property
    def native_value(self):
        value = self._device.get(self.entity_description.key)
        if value is None:
            return None
        if isinstance(value, float):
            return round(value, 1)
        return value
