"""Config flow for the AEH-W4E1 integration.

Setup methods (one config entry per air conditioner):
  - cloud: one-time Ayla sign-in with the OEM app credentials to fetch the
    LAN keys; afterwards the integration is fully local (default).
  - manual: host + lanip_key + lanip_key_id (fully local, no cloud).
A reconfigure flow allows updating the device address/key without deleting
the entity.
"""

import asyncio
import ipaddress
import logging

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.data_entry_flow import AbortFlow
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .ayla_cloud import (
    APP_LABELS,
    AylaCloudClient,
    CloudAuthError,
    CloudDevice,
    CloudError,
    CloudNoDevicesError,
)
from .const import (
    CONF_APP,
    CONF_CLOUD_DEVICE,
    CONF_CLOUD_PASSWORD,
    CONF_CLOUD_USER,
    CONF_DEVICE_PORT,
    CONF_DSN,
    CONF_HOST,
    CONF_KEEPALIVE_INTERVAL,
    CONF_LANIP_KEY,
    CONF_LANIP_KEY_ID,
    CONF_LOCAL_IP,
    CONF_MAC,
    CONF_MODEL,
    CONF_REFRESH_INTERVAL,
    CONF_SCAN_NETWORK,
    CONF_SERVER_PORT,
    CONF_SETUP_METHOD,
    CONF_SW_VERSION,
    CONF_TEMP_UNIT,
    DEFAULT_DEVICE_PORT,
    DEFAULT_KEEPALIVE_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_REFRESH_INTERVAL,
    DEFAULT_SERVER_PORT,
    DOMAIN,
    MIN_KEEPALIVE_INTERVAL,
    MIN_REFRESH_INTERVAL,
    SETUP_METHOD_CLOUD,
    SETUP_METHOD_MANUAL,
)
from .scanner import MAX_SCAN_HOSTS

_LOGGER = logging.getLogger(__name__)

# hassfest requires selector option keys to match [a-z0-9-_]+, so the form
# uses lowercase keys and maps them to the "C"/"F" stored in config entries.
TEMP_UNIT_OPTIONS = {"celsius": "C", "fahrenheit": "F"}
TEMP_UNIT_KEYS = {unit: key for key, unit in TEMP_UNIT_OPTIONS.items()}


def _temp_unit_key(value: str) -> str:
    """Accept either a stored unit or a select key; return a select key."""
    return TEMP_UNIT_KEYS.get(value, value if value in TEMP_UNIT_OPTIONS else "celsius")

SETUP_METHODS = [
    SETUP_METHOD_CLOUD,
    SETUP_METHOD_MANUAL,
]


def _manual_schema(
    name: str = DEFAULT_NAME,
    host: str = "",
    lanip_key: str = "",
    lanip_key_id: str | int = "",
    temp_unit: str = "C",
    device_port: int = DEFAULT_DEVICE_PORT,
    include_port: bool = True,
):
    schema: dict = {
        vol.Required("name", default=name): str,
        vol.Required(CONF_HOST, description={"suggested_value": host}): str,
        vol.Required(CONF_LANIP_KEY, description={"suggested_value": lanip_key}): str,
        vol.Required(CONF_LANIP_KEY_ID, description={"suggested_value": str(lanip_key_id)}): str,
        vol.Required(CONF_TEMP_UNIT, default=_temp_unit_key(temp_unit)): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=list(TEMP_UNIT_OPTIONS), translation_key="temp_unit"
            )
        ),
    }
    if include_port:
        schema[vol.Required(CONF_DEVICE_PORT, default=device_port)] = int
    return vol.Schema(schema)


class AehW4e1ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the AEH-W4E1 config flow."""

    VERSION = 1

    def __init__(self) -> None:
        self._cloud_devices: list[CloudDevice] = []
        self._cloud_app = ""

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        if user_input is not None:
            method = user_input[CONF_SETUP_METHOD]
            if method == SETUP_METHOD_MANUAL:
                return await self.async_step_manual()
            return await self.async_step_cloud()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SETUP_METHOD): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=SETUP_METHODS,
                            translation_key="setup_method",
                        )
                    )
                }
            ),
        )

    def _check_key_id(self, lanip_key_id: int, exclude_entry_id: str | None = None) -> str | None:
        for entry in self._async_current_entries():
            if entry.entry_id == exclude_entry_id:
                continue
            try:
                current_key_id = int(entry.data.get(CONF_LANIP_KEY_ID, -1))
            except (TypeError, ValueError):
                continue
            if current_key_id == lanip_key_id:
                return "already_configured"
        return None

    async def _validate_host(self, host: str, port: int) -> str | None:
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=5)
        except (OSError, TimeoutError, ValueError):
            return "cannot_connect"
        else:
            writer.close()
            await writer.wait_closed()
        return None

    async def _create_entry(self, data: dict, title: str) -> ConfigFlowResult:
        lanip_key_id = int(data[CONF_LANIP_KEY_ID])
        if error := self._check_key_id(lanip_key_id):
            raise AbortFlow(reason=error)
        await self.async_set_unique_id(
            data.get(CONF_DSN) or data.get(CONF_MAC) or f"aehw4e1-{lanip_key_id}"
        )
        self._abort_if_unique_id_configured()
        return self.async_create_entry(title=title, data=data)

    # ------------------------------------------------------------- manual

    async def async_step_manual(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            lanip_key = user_input[CONF_LANIP_KEY].strip()
            if not lanip_key:
                errors[CONF_LANIP_KEY] = "invalid_lan_key"
            try:
                lanip_key_id = int(user_input[CONF_LANIP_KEY_ID])
            except (TypeError, ValueError):
                errors[CONF_LANIP_KEY_ID] = "invalid_key_id"
            else:
                if error := self._check_key_id(lanip_key_id):
                    raise AbortFlow(reason=error)
                device_port = int(user_input.get(CONF_DEVICE_PORT, DEFAULT_DEVICE_PORT))
                if not 1 <= device_port <= 65535:
                    errors[CONF_DEVICE_PORT] = "invalid_port"
                elif errors:
                    pass
                elif error := await self._validate_host(host, device_port):
                    errors[CONF_HOST] = error
                else:
                    return await self._create_entry(
                        {
                            "name": user_input["name"].strip() or DEFAULT_NAME,
                            CONF_HOST: host,
                            CONF_DEVICE_PORT: device_port,
                            CONF_LANIP_KEY: lanip_key,
                            CONF_LANIP_KEY_ID: lanip_key_id,
                            CONF_TEMP_UNIT: TEMP_UNIT_OPTIONS[user_input[CONF_TEMP_UNIT]],
                            CONF_SETUP_METHOD: SETUP_METHOD_MANUAL,
                        },
                        user_input["name"].strip() or host,
                    )
        return self.async_show_form(step_id="manual", data_schema=_manual_schema(), errors=errors)

    # -------------------------------------------------------- reconfigure

    async def async_step_reconfigure(self, user_input=None) -> ConfigFlowResult:
        """Update address, key or naming of an existing entry."""
        entry = self.config_entry
        errors: dict[str, str] = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            lanip_key = user_input[CONF_LANIP_KEY].strip()
            if not lanip_key:
                errors[CONF_LANIP_KEY] = "invalid_lan_key"
            try:
                lanip_key_id = int(user_input[CONF_LANIP_KEY_ID])
            except (TypeError, ValueError):
                errors[CONF_LANIP_KEY_ID] = "invalid_key_id"
            else:
                if error := self._check_key_id(lanip_key_id, entry.entry_id):
                    raise AbortFlow(reason=error)
                device_port = int(user_input.get(CONF_DEVICE_PORT, DEFAULT_DEVICE_PORT))
                if not 1 <= device_port <= 65535:
                    errors[CONF_DEVICE_PORT] = "invalid_port"
                    return self.async_show_form(
                        step_id="reconfigure",
                        data_schema=_manual_schema(
                            name=user_input["name"],
                            host=host,
                            lanip_key=lanip_key,
                            lanip_key_id=lanip_key_id,
                            temp_unit=user_input[CONF_TEMP_UNIT],
                            device_port=device_port,
                        ),
                        errors=errors,
                    )
                if errors:
                    return self.async_show_form(
                        step_id="reconfigure",
                        data_schema=_manual_schema(
                            name=user_input["name"],
                            host=host,
                            lanip_key=lanip_key,
                            lanip_key_id=lanip_key_id,
                            temp_unit=user_input[CONF_TEMP_UNIT],
                            device_port=device_port,
                        ),
                        errors=errors,
                    )
                # Reachability is not enforced here: the module may legitimately
                # be offline while the user fixes its configuration.
                return self.async_update_reload_and_abort(
                    entry,
                    data={
                        **entry.data,
                        "name": user_input["name"].strip() or DEFAULT_NAME,
                        CONF_HOST: host,
                        CONF_DEVICE_PORT: device_port,
                        CONF_LANIP_KEY: lanip_key,
                        CONF_LANIP_KEY_ID: lanip_key_id,
                        CONF_TEMP_UNIT: TEMP_UNIT_OPTIONS[user_input[CONF_TEMP_UNIT]],
                    },
                    reason="reconfigure_successful",
                )
        data = entry.data
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_manual_schema(
                name=data.get("name", DEFAULT_NAME),
                host=data.get(CONF_HOST, ""),
                lanip_key=data.get(CONF_LANIP_KEY, ""),
                lanip_key_id=data.get(CONF_LANIP_KEY_ID, ""),
                temp_unit=data.get(CONF_TEMP_UNIT, "C"),
                device_port=data.get(CONF_DEVICE_PORT, DEFAULT_DEVICE_PORT),
            ),
            errors=errors,
        )

    # -------------------------------------------------------------- cloud

    async def async_step_cloud(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            app = user_input[CONF_APP]
            client = AylaCloudClient(async_get_clientsession(self.hass))
            try:
                self._cloud_devices = await client.fetch_devices(
                    app,
                    user_input[CONF_CLOUD_USER],
                    user_input[CONF_CLOUD_PASSWORD],
                )
            except CloudAuthError:
                errors["base"] = "invalid_auth"
            except CloudNoDevicesError:
                errors["base"] = "no_devices"
            except CloudError:
                errors["base"] = "cannot_connect"
            else:
                self._cloud_app = app
                return await self.async_step_cloud_device()
        schema = vol.Schema(
            {
                vol.Required(CONF_APP): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=sorted(APP_LABELS),
                        translation_key="app",
                    )
                ),
                vol.Required(CONF_CLOUD_USER): str,
                vol.Required(CONF_CLOUD_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                ),
            }
        )
        return self.async_show_form(step_id="cloud", data_schema=schema, errors=errors)

    async def async_step_cloud_device(self, user_input=None) -> ConfigFlowResult:
        if user_input is None:
            return self.async_show_form(
                step_id="cloud_device",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_CLOUD_DEVICE): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    selector.SelectOptionDict(
                                        value=device.dsn,
                                        label=f"{device.name} ({device.lan_ip})",
                                    )
                                    for device in self._cloud_devices
                                ]
                            )
                        )
                    }
                ),
            )
        cloud = next(d for d in self._cloud_devices if d.dsn == user_input[CONF_CLOUD_DEVICE])
        if not cloud.lan_ip:
            raise AbortFlow(reason="no_lan_ip")
        return await self._create_entry(
            {
                "name": cloud.name,
                CONF_HOST: cloud.lan_ip,
                CONF_DEVICE_PORT: DEFAULT_DEVICE_PORT,
                CONF_LANIP_KEY: cloud.lanip_key,
                CONF_LANIP_KEY_ID: cloud.lanip_key_id,
                CONF_TEMP_UNIT: cloud.temp_unit,
                CONF_MAC: cloud.mac,
                CONF_MODEL: cloud.oem_model,
                CONF_SW_VERSION: cloud.sw_version,
                CONF_DSN: cloud.dsn,
                CONF_APP: self._cloud_app,
                CONF_SETUP_METHOD: SETUP_METHOD_CLOUD,
            },
            cloud.name,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return AehW4e1OptionsFlowHandler()


class AehW4e1OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options: server port, advertised IP, intervals, scanning."""

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            server_port = int(user_input[CONF_SERVER_PORT])
            refresh_interval = int(user_input[CONF_REFRESH_INTERVAL])
            keepalive_interval = int(user_input[CONF_KEEPALIVE_INTERVAL])
            local_ip = user_input[CONF_LOCAL_IP].strip()
            scan_network = user_input[CONF_SCAN_NETWORK].strip()
            if not 0 <= server_port <= 65535:
                errors[CONF_SERVER_PORT] = "invalid_port"
            if refresh_interval < MIN_REFRESH_INTERVAL:
                errors[CONF_REFRESH_INTERVAL] = "invalid_refresh_interval"
            if keepalive_interval < MIN_KEEPALIVE_INTERVAL:
                errors[CONF_KEEPALIVE_INTERVAL] = "invalid_keepalive_interval"
            if local_ip:
                try:
                    if ipaddress.ip_address(local_ip).version != 4:
                        raise ValueError
                except ValueError:
                    errors[CONF_LOCAL_IP] = "invalid_local_ip"
            if scan_network:
                try:
                    network = ipaddress.ip_network(scan_network, strict=False)
                    if network.version != 4:
                        raise ValueError
                except ValueError:
                    errors[CONF_SCAN_NETWORK] = "invalid_scan_network"
                else:
                    if network.num_addresses > MAX_SCAN_HOSTS + 2:
                        errors[CONF_SCAN_NETWORK] = "scan_network_too_large"
            if not errors:
                return self.async_create_entry(
                    title="",
                    data={
                        **user_input,
                        CONF_LOCAL_IP: local_ip,
                        CONF_SCAN_NETWORK: scan_network,
                    },
                )
        options = self.config_entry.options
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SERVER_PORT,
                        default=options.get(CONF_SERVER_PORT, DEFAULT_SERVER_PORT),
                    ): int,
                    vol.Required(
                        CONF_LOCAL_IP,
                        default=options.get(CONF_LOCAL_IP, ""),
                        description={"suggested_value": options.get(CONF_LOCAL_IP, "")},
                    ): str,
                    vol.Required(
                        CONF_REFRESH_INTERVAL,
                        default=options.get(CONF_REFRESH_INTERVAL, DEFAULT_REFRESH_INTERVAL),
                    ): int,
                    vol.Required(
                        CONF_KEEPALIVE_INTERVAL,
                        default=options.get(CONF_KEEPALIVE_INTERVAL, DEFAULT_KEEPALIVE_INTERVAL),
                    ): int,
                    vol.Required(
                        CONF_SCAN_NETWORK,
                        default=options.get(CONF_SCAN_NETWORK, ""),
                        description={"suggested_value": options.get(CONF_SCAN_NETWORK, "")},
                    ): str,
                }
            ),
            errors=errors,
        )
