"""Original encoding/decoding of the AEH-W4E1 aggregated settings bitmap.

Devices equipped with the AEH-W4E1 module can report and accept the main
operating settings as a single 32-bit integer property named
`t_control_value`. Every field is stored at its own bit offset as
``((value << 1) | 1) << shift``: the low bit of the field acts as a *present*
flag and the value bits sit above it, so a write that only carries one field
leaves the other fields untouched inside the module.

The bit layout is a property of the protocol (verified against multiple
independent captures and implementations); the class below is our own way of
working with it.
"""

from dataclasses import dataclass

from .protocol import AcWorkMode, AirFlow, Economy, FanSpeed, FastColdHeat, Power, Quiet, TemperatureUnit

# Clears every *present* flag while keeping the encoded value bits.
_PRESENT_FLAG_MASK = 2868817502


@dataclass(frozen=True)
class _Field:
    """A bitmap field.

    `shift` is the position of the field's present-flag bit; the value is
    encoded in the `value_bits` bits above it. The temperature field is given
    7 value bits so the full Fahrenheit range (up to 86) is representable.
    """

    shift: int
    value_bits: int
    enum: type
    property_name: str

    @property
    def full_mask(self) -> int:
        return ((1 << (self.value_bits + 1)) - 1) << self.shift

    def read(self, bitmap: int):
        raw = (bitmap >> (self.shift + 1)) & ((1 << self.value_bits) - 1)
        return raw if self.enum is int else self.enum(raw)

    def write(self, bitmap: int, value) -> int:
        encoded = ((int(value) << 1) | 1) << self.shift
        return (bitmap & ~self.full_mask) | (encoded & self.full_mask)


_FIELDS: tuple[_Field, ...] = (
    _Field(0, 4, FanSpeed, "t_fan_speed"),
    _Field(5, 1, Power, "t_power"),
    _Field(8, 3, AcWorkMode, "t_work_mode"),
    _Field(12, 1, FastColdHeat, "t_temp_heatcold"),
    _Field(14, 1, Economy, "t_eco"),
    _Field(16, 7, int, "t_temp"),
    _Field(24, 1, AirFlow, "t_fan_power"),
    _Field(26, 1, AirFlow, "t_fan_leftright"),
    _Field(28, 1, Quiet, "t_fan_mute"),
    _Field(30, 1, TemperatureUnit, "t_temptype"),
)

_FIELDS_BY_PROPERTY = {field.property_name: field for field in _FIELDS}

# The set of property names that live inside the aggregated t_control_value
# bitmap. Anything else writable (t_sleep, t_temp_eight, t_backlight, ...)
# must be written to its own property even on bitmap-capable firmware.
BITMAP_PROPERTIES = frozenset(_FIELDS_BY_PROPERTY)


class SettingsBitmap:
    """Read and write the aggregated settings of a `t_control_value` value."""

    def __init__(self, raw: int) -> None:
        self._raw = int(raw)

    @property
    def raw(self) -> int:
        return self._raw

    def get(self, property_name: str):
        """Decode one field; plain ints are returned for the temperature."""
        field = _FIELDS_BY_PROPERTY[property_name]
        value = field.read(self._raw)
        return value if field.enum is int else int(value)

    def with_field(self, property_name: str, value) -> "SettingsBitmap":
        """Return a new bitmap with a single field updated.

        Only the target field's *present* flag survives, mirroring how the
        module interprets partial updates.
        """
        field = _FIELDS_BY_PROPERTY[property_name]
        cleared = self._raw & _PRESENT_FLAG_MASK
        return SettingsBitmap(field.write(cleared, value))

    def to_properties(self) -> dict[str, int]:
        """Decode every field into `{property_name: int_value}`."""
        return {field.property_name: int(field.read(self._raw)) for field in _FIELDS}
