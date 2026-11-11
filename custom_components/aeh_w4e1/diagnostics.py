"""Diagnostics support for the AEH-W4E1 integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from . import async_get_device

TO_REDACT_ENTRY = {"lanip_key", "host", "dsn", "mac"}
TO_REDACT_RUNTIME = {"host", "lanip_key", "mac", "dsn", "local_ip"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry, with sensitive data redacted."""
    device = async_get_device(hass, entry.entry_id)
    runtime: dict[str, Any] | None = None
    if device is not None:
        runtime = {
            "available": device.available,
            "uses_control_value": device.uses_control_value,
            "binding_is_trusted": device.binding_is_trusted,
            "pending_commands": len(device._commands),
            "properties": device.properties_snapshot,
            "config": async_redact_data(
                dict(vars(device.config)), TO_REDACT_RUNTIME
            ),
        }
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT_ENTRY),
            "options": dict(entry.options),
        },
        "runtime": runtime,
    }
