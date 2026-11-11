"""Shared bits for AEH-W4E1 entities."""

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect

from .const import DEFAULT_MODEL, DOMAIN, SIGNAL_AVAILABLE, SIGNAL_UPDATE
from .device import AehW4e1Device


def device_unique_id(device: AehW4e1Device) -> str:
    return device.config.dsn or device.config.mac or f"aehw4e1-{device.config.lanip_key_id}"


class AehW4e1Base:
    """Common device info, signal wiring and naming for AEH-W4E1 entities.

    The dispatcher subscription happens in `async_added_to_hass` (entity
    lifecycle): listeners are @callback so HA executes them inline in the
    event loop, and `async_on_remove` guarantees cleanup. Subscribing
    earlier would deliver signals to entities whose `hass` is not set yet
    ("Attribute hass is None") or already removed.
    """

    _attr_has_entity_name = True
    _device: AehW4e1Device
    _entry_id: str

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        signal_update = SIGNAL_UPDATE.format(domain=DOMAIN, entry_id=self._entry_id)
        signal_available = SIGNAL_AVAILABLE.format(domain=DOMAIN, entry_id=self._entry_id)

        @callback
        def _on_update(_name: str, _value) -> None:
            self.async_write_ha_state()

        @callback
        def _on_available(_available: bool) -> None:
            self.async_write_ha_state()

        self.async_on_remove(async_dispatcher_connect(self.hass, signal_update, _on_update))
        self.async_on_remove(async_dispatcher_connect(self.hass, signal_available, _on_available))

    @property
    def device_info(self) -> DeviceInfo:
        device = self._device
        return DeviceInfo(
            identifiers={(DOMAIN, device_unique_id(device))},
            name=device.config.name,
            manufacturer="Hisense",
            model=device.config.model or DEFAULT_MODEL,
            sw_version=device.config.sw_version or None,
        )

    @property
    def available(self) -> bool:
        return self._device.available
