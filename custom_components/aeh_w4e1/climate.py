"""Climate platform for AEH-W4E1 air conditioners.

Maps the device's full feature set onto HA's climate model:
  - hvac modes: off (t_power), fan_only/heat/cool/dry/auto (t_work_mode)
  - target temperature (t_temp), fan speeds (t_fan_speed)
  - vertical swing (t_fan_power) and horizontal swing (t_fan_leftright)
  - presets: eco (t_eco), fast cool/heat (t_temp_heatcold), 8° heat
    (t_temp_eight), sleep curves 1-4 (t_sleep)
"""

import logging

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, PRECISION_WHOLE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import async_get_device
from .const import (
    CONF_TEMP_UNIT,
    TEMP_MAX_C,
    TEMP_MAX_F,
    TEMP_MIN_C,
    TEMP_MIN_F,
)
from .device import AehW4e1Device
from .entity import AehW4e1Base, device_unique_id
from .protocol import (
    AcWorkMode,
    AirFlow,
    Economy,
    EightHeat,
    FanSpeed,
    FastColdHeat,
    Power,
    SleepMode,
)

_LOGGER = logging.getLogger(__name__)

HVAC_MODE_BY_WORK_MODE = {
    AcWorkMode.FAN: HVACMode.FAN_ONLY,
    AcWorkMode.HEAT: HVACMode.HEAT,
    AcWorkMode.COOL: HVACMode.COOL,
    AcWorkMode.DRY: HVACMode.DRY,
    AcWorkMode.AUTO: HVACMode.AUTO,
}
HVAC_MODE_TO_WORK_MODE = {
    HVACMode.FAN_ONLY: AcWorkMode.FAN,
    HVACMode.HEAT: AcWorkMode.HEAT,
    HVACMode.COOL: AcWorkMode.COOL,
    HVACMode.DRY: AcWorkMode.DRY,
    HVACMode.AUTO: AcWorkMode.AUTO,
}

FAN_MODES = {
    "auto": FanSpeed.AUTO,
    "lower": FanSpeed.LOWER,
    "low": FanSpeed.LOW,
    "medium": FanSpeed.MEDIUM,
    "high": FanSpeed.HIGH,
    "higher": FanSpeed.HIGHER,
}
FAN_MODE_BY_SPEED = {speed: mode for mode, speed in FAN_MODES.items()}

SWING_ON = "on"
SWING_OFF = "off"
SWING_MODES = [SWING_OFF, SWING_ON]  # vertical louver (t_fan_power)
SWING_HORIZONTAL_MODES = [SWING_OFF, SWING_ON]  # horizontal louver (t_fan_leftright)

PRESET_NONE = "none"
PRESET_ECO = "eco"
PRESET_FAST_HEAT_COOL = "fast_heat_cool"
PRESET_EIGHT_HEAT = "eight_deg_heat"
SLEEP_PRESETS = {
    SleepMode.ONE: "sleep_1",
    SleepMode.TWO: "sleep_2",
    SleepMode.THREE: "sleep_3",
    SleepMode.FOUR: "sleep_4",
}
SLEEP_BY_PRESET = {preset: mode for mode, preset in SLEEP_PRESETS.items()}
PRESET_MODES = [
    PRESET_NONE,
    PRESET_ECO,
    PRESET_FAST_HEAT_COOL,
    PRESET_EIGHT_HEAT,
    *SLEEP_PRESETS.values(),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    device = async_get_device(hass, entry.entry_id)
    if device is None:
        return
    async_add_entities([AehW4e1Climate(entry, device)])


class AehW4e1Climate(AehW4e1Base, ClimateEntity):
    """Climate entity driven by the locally-pushed device state."""

    _attr_hvac_modes = [HVACMode.OFF, *HVAC_MODE_TO_WORK_MODE]
    _attr_fan_modes = list(FAN_MODES)
    _attr_swing_modes = SWING_MODES
    _attr_swing_horizontal_modes = SWING_HORIZONTAL_MODES
    _attr_preset_modes = PRESET_MODES
    _attr_precision = PRECISION_WHOLE
    _attr_target_temperature_step = 1
    _attr_translation_key = "ac"

    def __init__(self, entry: ConfigEntry, device: AehW4e1Device) -> None:
        self._device = device
        self._entry_id = entry.entry_id
        is_celsius = entry.data.get(CONF_TEMP_UNIT, "C") == "C"
        self._attr_temperature_unit = (
            UnitOfTemperature.CELSIUS if is_celsius else UnitOfTemperature.FAHRENHEIT
        )
        self._attr_min_temp = TEMP_MIN_C if is_celsius else TEMP_MIN_F
        self._attr_max_temp = TEMP_MAX_C if is_celsius else TEMP_MAX_F
        self._attr_unique_id = f"{device_unique_id(device)}-climate"
        self._attr_supported_features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.FAN_MODE
            | ClimateEntityFeature.SWING_MODE
            | ClimateEntityFeature.SWING_HORIZONTAL_MODE
            | ClimateEntityFeature.PRESET_MODE
        )

    # ------------------------------------------------------------------ state

    @property
    def hvac_mode(self) -> HVACMode:
        if self._device.get_power() != int(Power.ON):
            return HVACMode.OFF
        try:
            work_mode = AcWorkMode(self._device.get_work_mode())
        except ValueError:
            return HVACMode.AUTO
        return HVAC_MODE_BY_WORK_MODE.get(work_mode, HVACMode.AUTO)

    @property
    def target_temperature(self) -> float | None:
        temp = self._device.get_temperature()
        return float(temp) if temp else None

    @property
    def current_temperature(self) -> float | None:
        temp = self._device.get("f_temp_in")
        return round(float(temp), 1) if temp is not None else None

    @property
    def fan_mode(self) -> str | None:
        try:
            return FAN_MODE_BY_SPEED.get(FanSpeed(self._device.get_fan_speed()))
        except ValueError:
            return None

    @property
    def swing_mode(self) -> str:
        vertical = int(self._device.get("t_fan_power") or 0) == int(AirFlow.ON)
        return SWING_ON if vertical else SWING_OFF

    @property
    def swing_horizontal_mode(self) -> str:
        horizontal = int(self._device.get("t_fan_leftright") or 0) == int(AirFlow.ON)
        return SWING_ON if horizontal else SWING_OFF

    @property
    def preset_mode(self) -> str | None:
        if int(self._device.get("t_eco") or 0) == int(Economy.ON):
            return PRESET_ECO
        if int(self._device.get("t_temp_heatcold") or 0) == int(FastColdHeat.ON):
            return PRESET_FAST_HEAT_COOL
        if int(self._device.get("t_temp_eight") or 0) == int(EightHeat.ON):
            return PRESET_EIGHT_HEAT
        try:
            sleep = SleepMode(int(self._device.get("t_sleep") or 0))
        except ValueError:
            return PRESET_NONE
        return SLEEP_PRESETS.get(sleep, PRESET_NONE)

    # --------------------------------------------------------------- commands

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._device.set_power(Power.OFF)
            return
        if self._device.get_power() != int(Power.ON):
            await self._device.set_power(Power.ON)
        await self._device.set_work_mode(HVAC_MODE_TO_WORK_MODE[hvac_mode])

    async def async_set_temperature(self, **kwargs) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        await self._device.set_temperature(round(float(temperature)))

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        await self._device.set_fan_speed(FAN_MODES[fan_mode])

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        value = AirFlow.ON if swing_mode == SWING_ON else AirFlow.OFF
        await self._device.set_fan_vertical(value)

    async def async_set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
        value = AirFlow.ON if swing_horizontal_mode == SWING_ON else AirFlow.OFF
        await self._device.set_fan_horizontal(value)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        current = self.preset_mode
        _LOGGER.info(
            "%s: preset requested '%s' (current '%s', t_sleep=%s)",
            self._device.config.name,
            preset_mode,
            current,
            self._device.get("t_sleep"),
        )
        if preset_mode == current:
            return
        # Clear whichever special mode is currently active.
        if current == PRESET_ECO:
            await self._device.set_eco(Economy.OFF)
        elif current == PRESET_FAST_HEAT_COOL:
            await self._device.set_fast_heat_cold(FastColdHeat.OFF)
        elif current == PRESET_EIGHT_HEAT:
            await self._device.send_command("t_temp_eight", int(EightHeat.OFF))
        elif current in SLEEP_BY_PRESET:
            await self._device.set_sleep(SleepMode.STOP)

        if preset_mode == PRESET_ECO:
            await self._device.set_eco(Economy.ON)
        elif preset_mode == PRESET_FAST_HEAT_COOL:
            await self._device.set_fast_heat_cold(FastColdHeat.ON)
        elif preset_mode == PRESET_EIGHT_HEAT:
            await self._device.send_command("t_temp_eight", int(EightHeat.ON))
        elif (sleep := SLEEP_BY_PRESET.get(preset_mode)) is not None:
            await self._device.set_sleep(sleep)
