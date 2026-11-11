"""Binary sensor platform for AEH-W4E1 air conditioners."""

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import async_get_device
from .device import AehW4e1Device
from .entity import AehW4e1Base, device_unique_id
from .protocol import FAULT_PROPERTIES

_LOGGER = logging.getLogger(__name__)

_FAULT_LABELS = {
    "f_e_arkgrille": "Cabinet grille protection alarm",
    "f_e_incoiltemp": "Indoor coil temperature sensor fault",
    "f_e_incom": "Indoor/outdoor communication fault",
    "f_e_indisplay": "Display panel communication fault",
    "f_e_ineeprom": "Indoor EEPROM error",
    "f_e_inele": "Indoor power panel communication fault",
    "f_e_infanmotor": "Indoor fan motor fault",
    "f_e_inhumidity": "Indoor humidity sensor fault",
    "f_e_inkeys": "Keyboard plate communication fault",
    "f_e_inlow": "Indoor low pressure fault",
    "f_e_intemp": "Indoor temperature sensor fault",
    "f_e_invzero": "Indoor voltage zero-cross detection fault",
    "f_e_outcoiltemp": "Outdoor coil temperature sensor fault",
    "f_e_outeeprom": "Outdoor EEPROM error",
    "f_e_outgastemp": "Exhaust temperature sensor fault",
    "f_e_outmachine2": "Outdoor unit 2 fault",
    "f_e_outmachine": "Outdoor unit fault",
    "f_e_outtemp": "Outdoor ambient temperature sensor fault",
    "f_e_outtemplow": "Outdoor low temperature fault",
    "f_e_push": "WiFi/indoor control communication fault",
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device = async_get_device(hass, entry.entry_id)
    if device is None:
        return
    entities = [
        AehW4e1BinarySensor(
            entry,
            device,
            BinarySensorEntityDescription(
                key="f_filterclean",
                translation_key="filter_dirty",
            ),
        ),
        AehW4e1FaultBinarySensor(entry, device),
    ]
    async_add_entities(entities)


class AehW4e1BinarySensor(AehW4e1Base, BinarySensorEntity):
    """A boolean `f_*` property exposed as a binary sensor."""

    def __init__(
        self,
        entry: ConfigEntry,
        device: AehW4e1Device,
        description: BinarySensorEntityDescription,
    ) -> None:
        self._device = device
        self._entry_id = entry.entry_id
        self.entity_description = description
        self._attr_unique_id = f"{device_unique_id(device)}-{description.key}"

    @property
    def is_on(self) -> bool:
        return bool(self._device.get(self.entity_description.key))


class AehW4e1FaultBinarySensor(AehW4e1Base, BinarySensorEntity):
    """Aggregated fault indicator: on when any `f_e_*` sensor reports a fault."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, entry: ConfigEntry, device: AehW4e1Device) -> None:
        self._device = device
        self._entry_id = entry.entry_id
        self._attr_translation_key = "fault"
        self._attr_unique_id = f"{device_unique_id(device)}-fault"

    @property
    def is_on(self) -> bool:
        return any(bool(self._device.get(name)) for name in FAULT_PROPERTIES)

    @property
    def extra_state_attributes(self) -> dict:
        faults = {
            name: _FAULT_LABELS.get(name, name)
            for name in FAULT_PROPERTIES
            if bool(self._device.get(name))
        }
        return {"faults": faults} if faults else {"faults": {}}
