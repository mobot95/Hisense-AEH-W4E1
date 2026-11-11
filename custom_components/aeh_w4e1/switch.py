"""Switch platform for AEH-W4E1 air conditioners."""

import logging

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import async_get_device
from .device import AehW4e1Device
from .entity import AehW4e1Base, device_unique_id
from .protocol import DoubleFrequency

_LOGGER = logging.getLogger(__name__)


def _build_descriptions() -> list[SwitchEntityDescription]:
    return [
        SwitchEntityDescription(
            key="t_backlight",
            translation_key="backlight",
        ),
        SwitchEntityDescription(
            key="t_fan_mute",
            translation_key="silent_mode",
        ),
        SwitchEntityDescription(
            key="t_display_power",
            translation_key="display_power",
            entity_category=EntityCategory.CONFIG,
            entity_registry_enabled_default=False,
        ),
        SwitchEntityDescription(
            key="t_run_mode",
            translation_key="double_frequency",
            entity_category=EntityCategory.CONFIG,
            entity_registry_enabled_default=False,
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
        AehW4e1Switch(entry, device, description) for description in _build_descriptions()
    )


class AehW4e1Switch(AehW4e1Base, SwitchEntity):
    """A boolean `t_*` property exposed as a switch."""

    def __init__(
        self,
        entry: ConfigEntry,
        device: AehW4e1Device,
        description: SwitchEntityDescription,
    ) -> None:
        self._device = device
        self._entry_id = entry.entry_id
        self.entity_description = description
        self._attr_unique_id = f"{device_unique_id(device)}-{description.key}"

    @property
    def is_on(self) -> bool:
        key = self.entity_description.key
        raw = int(self._device.get(key) or 0)
        if key == "t_backlight":
            # Dimmer semantics are inverted on the device (ON is encoded as 0).
            return raw == 0
        return bool(raw)

    async def async_turn_on(self) -> None:
        key = self.entity_description.key
        if key == "t_backlight":
            # Dimmer semantics are inverted on the device (ON = 0).
            await self._device.send_command(key, 0)
        elif key == "t_run_mode":
            await self._device.send_command(key, int(DoubleFrequency.ON))
        else:
            await self._device.send_command(key, 1)

    async def async_turn_off(self) -> None:
        key = self.entity_description.key
        if key == "t_backlight":
            await self._device.send_command(key, 1)
        elif key == "t_run_mode":
            await self._device.send_command(key, int(DoubleFrequency.OFF))
        else:
            await self._device.send_command(key, 0)
