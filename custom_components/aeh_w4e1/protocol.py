"""AEH-W4E1 (Ayla LAN mode) protocol definitions.

Property names, types and command payload builders, mirroring the protocol
spoken by Hisense ACs with an AEH-W4B1/AEH-W4E1 WiFi module.
"""

from dataclasses import dataclass
from enum import IntEnum
import random
import string


class Power(IntEnum):
    OFF = 0
    ON = 1


class AcWorkMode(IntEnum):
    FAN = 0
    HEAT = 1
    COOL = 2
    DRY = 3
    AUTO = 4


class FanSpeed(IntEnum):
    AUTO = 0
    LOWER = 5
    LOW = 6
    MEDIUM = 7
    HIGH = 8
    HIGHER = 9


class AirFlow(IntEnum):
    OFF = 0
    ON = 1


class Quiet(IntEnum):
    OFF = 0
    ON = 1


class Economy(IntEnum):
    OFF = 0
    ON = 1


class EightHeat(IntEnum):
    OFF = 0
    ON = 1


class FastColdHeat(IntEnum):
    OFF = 0
    ON = 1


class SleepMode(IntEnum):
    STOP = 0
    ONE = 1
    TWO = 2
    THREE = 3
    FOUR = 4


class TemperatureUnit(IntEnum):
    CELSIUS = 0
    FAHRENHEIT = 1


class Dimmer(IntEnum):
    # Note: the device semantics are inverted (ON is 0).
    ON = 0
    OFF = 1


class DoubleFrequency(IntEnum):
    OFF = 0
    ON = 1


@dataclass(frozen=True)
class PropDef:
    base_type: str
    py_type: type
    read_only: bool
    precision: float = 1


# All properties spoken by AEH-W4E1 air conditioners. Read-only (`f_*`)
# properties are only polled; writable (`t_*`) properties can be commanded.
AC_PROPERTIES: dict[str, PropDef] = {
    "f_electricity": PropDef("integer", int, True),
    "f_e_arkgrille": PropDef("boolean", int, True),
    "f_e_incoiltemp": PropDef("boolean", int, True),
    "f_e_incom": PropDef("boolean", int, True),
    "f_e_indisplay": PropDef("boolean", int, True),
    "f_e_ineeprom": PropDef("boolean", int, True),
    "f_e_inele": PropDef("boolean", int, True),
    "f_e_infanmotor": PropDef("boolean", int, True),
    "f_e_inhumidity": PropDef("boolean", int, True),
    "f_e_inkeys": PropDef("boolean", int, True),
    "f_e_inlow": PropDef("boolean", int, True),
    "f_e_intemp": PropDef("boolean", int, True),
    "f_e_invzero": PropDef("boolean", int, True),
    "f_e_outcoiltemp": PropDef("boolean", int, True),
    "f_e_outeeprom": PropDef("boolean", int, True),
    "f_e_outgastemp": PropDef("boolean", int, True),
    "f_e_outmachine2": PropDef("boolean", int, True),
    "f_e_outmachine": PropDef("boolean", int, True),
    "f_e_outtemp": PropDef("boolean", int, True),
    "f_e_outtemplow": PropDef("boolean", int, True),
    "f_e_push": PropDef("boolean", int, True),
    "f_filterclean": PropDef("boolean", int, True),
    "f_humidity": PropDef("integer", int, True),
    "f_power_display": PropDef("boolean", int, True),
    "f_temp_in": PropDef("decimal", float, True),
    "f_voltage": PropDef("integer", int, True),
    "t_backlight": PropDef("boolean", int, False),
    "t_control_value": PropDef("integer", int, False),
    "t_device_info": PropDef("boolean", int, False),
    "t_display_power": PropDef("boolean", int, False),
    "t_eco": PropDef("boolean", int, False),
    "t_fan_leftright": PropDef("boolean", int, False),
    "t_fan_mute": PropDef("boolean", int, False),
    "t_fan_power": PropDef("boolean", int, False),
    "t_fan_speed": PropDef("integer", int, False),
    "t_ftkt_start": PropDef("integer", int, False),
    "t_power": PropDef("boolean", int, False),
    "t_run_mode": PropDef("boolean", int, False),
    "t_setmulti_value": PropDef("integer", int, False),
    "t_sleep": PropDef("integer", int, False),
    "t_temp": PropDef("integer", int, False),
    "t_temptype": PropDef("boolean", int, False),
    "t_temp_eight": PropDef("boolean", int, False),
    "t_temp_heatcold": PropDef("boolean", int, False),
    "t_work_mode": PropDef("integer", int, False),
}

FAULT_PROPERTIES = [name for name in AC_PROPERTIES if name.startswith("f_e_")]

# Properties reported as enum names by the device layer (values are ints).
ENUM_PROPERTIES: dict[str, type[IntEnum]] = {
    "t_backlight": Dimmer,
    "t_eco": Economy,
    "t_fan_leftright": AirFlow,
    "t_fan_mute": Quiet,
    "t_fan_power": AirFlow,
    "t_power": Power,
    "t_run_mode": DoubleFrequency,
    "t_sleep": SleepMode,
    "t_temptype": TemperatureUnit,
    "t_temp_eight": EightHeat,
    "t_temp_heatcold": FastColdHeat,
}

# The device reports a typo'd name for voltage; normalize it.
_DEVICE_TYPOS = {"f_votage": "f_voltage"}


class ProtocolError(Exception):
    """Raised when a protocol payload is malformed."""


class PropertyError(Exception):
    """Raised when a property name/value cannot be used in a command."""


def normalize_name(name: str) -> str:
    """Fix known typos in property names sent by the device."""
    return _DEVICE_TYPOS.get(name, name)


def convert_value(name: str, value):
    """Coerce a raw (device or user) value to the property's python type.

    Accepts enum names ("ON"/"OFF") and floats for integer properties
    (e.g. temperatures converted by HA from Celsius).
    """
    prop = AC_PROPERTIES.get(name)
    if prop is None:
        raise PropertyError(f'Unknown property "{name}"')
    if isinstance(value, str):
        enum_cls = ENUM_PROPERTIES.get(name)
        if enum_cls is not None:
            try:
                return int(enum_cls[value])
            except KeyError as exc:
                raise PropertyError(f'Invalid value "{value}" for "{name}"') from exc
        if "." in value:
            value = round(float(value))
    if prop.py_type is float:
        return float(value)
    return prop.py_type(value)


def _to_payload_value(name: str, value) -> int:
    """Encode a typed value for the wire (precision applied, enums as ints)."""
    prop = AC_PROPERTIES[name]
    if prop.precision != 1:
        value = round(value / prop.precision)
    return int(value)


def build_write_command(name: str, value) -> dict:
    """Build a property-write command payload."""
    if name not in AC_PROPERTIES:
        raise PropertyError(f'Unknown property "{name}"')
    prop = AC_PROPERTIES[name]
    if prop.read_only:
        raise PropertyError(f'Cannot update read-only property "{name}"')
    return {
        "properties": [
            {
                "property": {
                    "base_type": prop.base_type,
                    "name": name,
                    "value": _to_payload_value(name, value),
                    "id": "".join(random.choices(string.ascii_letters + string.digits, k=8)),
                }
            }
        ]
    }


def build_read_command(name: str, cmd_id: int) -> dict:
    """Build a property-read command payload (status poll)."""
    return {
        "cmds": [
            {
                "cmd": {
                    "method": "GET",
                    "resource": f"property.json?name={name}",
                    "uri": "/local_lan/property/datapoint.json",
                    "data": "",
                    "cmd_id": cmd_id,
                }
            }
        ]
    }
