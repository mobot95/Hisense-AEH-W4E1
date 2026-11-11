"""One-time cloud bootstrap against the Ayla Networks API.

AEH-W4E1 modules derive their LAN encryption from a per-device `lanip_key`
that is only retrievable from the (Ayla-hosted) backend of the OEM app.
This client performs the same calls as the OEM mobile apps to fetch the
device list, local IPs and LAN keys. After setup, the integration operates
fully locally and never touches the cloud again.

App secrets and app-id mappings are derived from the AirCon add-on's
`app_mappings.py` (deiger/AirCon, GPL-3.0).
"""

import base64
from dataclasses import dataclass
import logging

import aiohttp

_LOGGER = logging.getLogger(__name__)

_USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 9.0; SM-G850F Build/LRX22G)"

AYLA_USER_SERVERS = {
    "us": "user-field.aylanetworks.com",
    "eu": "user-field-eu.aylanetworks.com",
    "cn": "user-field.ayla.com.cn",
}
AYLA_DEVICES_SERVERS = {
    "us": "ads-field.aylanetworks.com",
    "eu": "ads-eu.aylanetworks.com",
    "cn": "ads-field.ayla.com.cn",
}

SECRET_MAP = {
    "oem-us": b"\x1dgAPT\xd1\xa9\xec\xe2\xa2\x01\x19\xc0\x03X\x13j\xfc\xb5\x91",
    "mid-us": b"\xdeCx\xbe\x0cq8\x0b\x99\xb4Z\x93>\xfc\xcc\x9ag\x98\xf8\x14",
    "tornado-us": b"\x87O\xf2.&;X\xfb\xf6L\xfdRq'\x0f\t6\x0c\xfd)",
    "wwh-us": b"(\xcb9w\xc5\xc9\xb7\xab{*k8T!Yb\xaa\xcf\xd0\x85",
    "winia-us": b"\xeb_\xce\xb2\xc6\xff`\xa9\xfa\xa8r\x1c\x0bH\xf8\xe27\xa7U\xec",
    "york-us": b"\xc6A\x7fHyV<\xb2\xa2\xde<\x1f{c\xa9\rt\x9fy\xef",
    "beko-eu": (
        b"\xa9C\n\xdb\xf7+\x01\xe2X\ne\x85\x06\x89\xaa\x88ZP+\x07>~s{\xd3\x1f\x05"
        b"\x91&\x8c\x81\x84&\xe11\xef=s\"*\xa4"
    ),
    "oem-eu": (
        b"a\x1ez\xf5\xc4\x0f\x18~\xe5\xeb\xb1\x9f\xe4\xf5&B\xfe#\x88\xcb>\x06O,y"
        b"\xc1\x06c\x9d\x99J\xc2x\xac\xeb\x82\x93\xe5\r\x89d"
    ),
    "mid-eu": (
        b"\x05$\xe6\xecW\xa3\xd1B\xa0\x84\xab*\xf0\x04\x80\xce\xae\xe5`\xc4>w\xf8"
        b"\xc4\xf3X\xf6<\xd2\xd2I\x14!\xd0\x98\xed\xf2\xab\xae\xc6\x03"
    ),
    "haxxair": b"\xd8\xaf\x89--\x00\xabI\x93\x83j\xab\x9acX\xac^\x90f;",
    "fglair-cn": b"\xcd\xec\xe0\xed\x8e\xb4b\x90/\xcbq\xcf\xc3\x1b\xd6.wx:\x1e",
    "fglair-eu": b"\x82\x91[T\x14h\x88\x9f\x04\xdd\x05\x89\xf9\x04T,\xb2\xf7\x8fu",
    "fglair-us": b"U\xbf\x0c@\xbf\xe5\x16&\x10\xec2\xa37G\x82\x15|\xe7)\x91",
    "field-us": b"\xc8b\x08\xfa\xce8\xf8\xf1\x81\xa5\x81\x8fX\xb4\x80\xc0\xdc\xf5\ny",
    "huihe-us": b"\xa2\xbcZ3\xbch\xfa7.`\xbc\xef0\xa3p\xa1\xf0\xaf\xf4\xd4",
    "denali-us": b"\xf1\'\xb0K \xdbZ\xd84;\xeb\x02\xa2\xee\x008\xda\x95\xfd\x93",
    "hisense-eu": b"\xc0\xedK,\xff+X\xfa\xf6p\x87\xaa\xbcV\x88\xfbI\xb4\xcf\xad",
    "hisense-us": b"x\x04\xdf\xef6\x08\x8e\x06\n\x97\xfc\xed4m\xd8\xc7\xa3=\xce\x9f",
    "hismart-eu": b"0\x07\xe9\x04a\xa6e\xc4\x1c\x08+\"\r\x84w\x91\x8f\xa8)\x98",
    "hismart-us": b"\xd6+\x1f\xb0b\t\x19G\x87\x8c\xaak\xd0\xf8y\xf5\x933\xafp",
}

SECRET_ID_MAP = {
    "haxxair": "HAXXAIR",
    "field-us": "pactera-field-f624d97f-us",
    "fglair-cn": "FGLairField-cn",
    "fglair-eu": "FGLair-eu",
    "fglair-us": "CJIOSP",
    "huihe-us": "huihe-d70b5148-field-us",
    "denali-us": "DenaliAire",
    "hisense-eu": "Hisense",
    "hisense-us": "APP1",
    "hismart-eu": "Hismart",
    "hismart-us": "App1",
}

SECRET_ID_EXTRA_MAP = {
    "denali-us": "iA",
    "hisense-eu": "mw",
    "hisense-us": "pg",
    "hismart-eu": "fA",
    "hismart-us": "Lg",
}

# OEM apps whose devices report temperatures in Celsius.
CELSIUS_BASED_APPS = {"fglair-eu", "hisense-eu", "hismart-eu", "hismart-us"}

APP_LABELS = {
    "hisense-eu": "HiSmart Life (Hisense EU)",
    "hisense-us": "HiSmart Home (Hisense US)",
    "hismart-eu": "Smart-Living",
    "hismart-us": "AI-Home",
    "field-us": "HiSmart Air",
    "fglair-eu": "FGLair (Fujitsu)",
    "fglair-us": "FGLair (Fujitsu)",
    "fglair-cn": "FGLair (Fujitsu)",
    "oem-eu": "Hi-Smart AC",
    "oem-us": "Hisense (OEM US)",
    "mid-eu": "WiFi AC",
    "mid-us": "Smiling Air",
    "beko-eu": "Beko",
    "tornado-us": "Tornado WiFi",
    "winia-us": "Winia HomeSmart",
    "wwh-us": "Westinghouse",
    "york-us": "YORK Smart",
    "denali-us": "Denali Aire",
    "huihe-us": "SunHome",
    "haxxair": "HAXXAIR",
}


class CloudError(Exception):
    """Base class for cloud bootstrap errors."""


class CloudAuthError(CloudError):
    """Wrong credentials."""


class CloudConnectionError(CloudError):
    """The Ayla backend could not be reached."""


@dataclass
class CloudDevice:
    name: str
    dsn: str
    oem_model: str
    sw_version: str
    mac: str
    lan_ip: str
    lanip_key: str
    lanip_key_id: int
    temp_unit: str  # "C" or "F"


def temp_unit_for_app(app: str) -> str:
    return "C" if app in CELSIUS_BASED_APPS else "F"


def _app_ids(app: str) -> tuple[str, str]:
    prefix = SECRET_ID_MAP.get(app, f"a-Hisense-{app}-field")
    if app in SECRET_ID_EXTRA_MAP:
        app_id = "-".join((prefix, SECRET_ID_EXTRA_MAP[app], "id"))
    else:
        app_id = "-".join((prefix, "id"))
    secret = (
        base64.b64encode(SECRET_MAP[app]).decode("utf-8").rstrip("=").replace("+", "-")
        .replace("/", "_")
    )
    return app_id, f"{prefix}-{secret}"


def _servers_for_app(app: str) -> tuple[str, str]:
    region = app[-2:]
    if region not in AYLA_USER_SERVERS:
        region = "us"
    return AYLA_USER_SERVERS[region], AYLA_DEVICES_SERVERS[region]


class AylaCloudClient:
    """Minimal Ayla REST client for the setup phase."""

    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self._token: str | None = None

    async def _request(self, method: str, url: str, **kwargs):
        try:
            resp = await self._session.request(method, url, **kwargs)
        except (aiohttp.ClientError, TimeoutError) as ex:
            raise CloudConnectionError(str(ex)) from ex
        return resp

    async def sign_in(self, app: str, user: str, password: str) -> None:
        user_server, _ = _servers_for_app(app)
        app_id, app_secret = _app_ids(app)
        query = {
            "user": {
                "email": user,
                "password": password,
                "application": {"app_id": app_id, "app_secret": app_secret},
            }
        }
        headers = {
            "Accept": "application/json",
            "Connection": "Keep-Alive",
            "Authorization": "none",
            "Content-Type": "application/json",
            "User-Agent": _USER_AGENT,
            "Accept-Encoding": "gzip",
        }
        resp = await self._request(
            "POST", f"https://{user_server}/users/sign_in.json", json=query, headers=headers
        )
        if resp.status in (401, 404):
            raise CloudAuthError(f"Sign-in rejected ({resp.status})")
        if resp.status != 200:
            raise CloudConnectionError(f"Sign-in failed: HTTP {resp.status}")
        data = await resp.json()
        self._token = data.get("access_token")
        if not self._token:
            raise CloudConnectionError("No access token in sign-in response")

    def _auth_headers(self) -> dict:
        headers = {
            "Accept": "application/json",
            "Connection": "Keep-Alive",
            "Authorization": f"auth_token {self._token}",
            "User-Agent": _USER_AGENT,
            "Accept-Encoding": "gzip",
        }
        return headers

    async def _get_devices(self, app: str) -> list[dict]:
        _, devices_server = _servers_for_app(app)
        resp = await self._request(
            "GET",
            f"https://{devices_server}/apiv1/devices.json",
            headers=self._auth_headers(),
        )
        if resp.status in (401, 404):
            raise CloudAuthError(f"Device list rejected ({resp.status})")
        if resp.status != 200:
            raise CloudConnectionError(f"Device list failed: HTTP {resp.status}")
        devices = await resp.json()
        if not devices:
            raise CloudError("No device is configured in the app: associate the A/C first")
        return devices

    async def _get_lan(self, app: str, dsn: str) -> dict:
        _, devices_server = _servers_for_app(app)
        resp = await self._request(
            "GET",
            f"https://{devices_server}/apiv1/dsns/{dsn}/lan.json",
            headers=self._auth_headers(),
        )
        if resp.status != 200:
            raise CloudConnectionError(f"LAN key fetch failed for {dsn}: HTTP {resp.status}")
        return (await resp.json()).get("lanip") or {}

    async def fetch_devices(self, app: str, user: str, password: str) -> list[CloudDevice]:
        """Sign in and return every AC associated with the account."""
        await self.sign_in(app, user, password)
        result: list[CloudDevice] = []
        for entry in await self._get_devices(app):
            device = entry.get("device") or {}
            dsn = device.get("dsn")
            if not dsn:
                continue
            lan = await self._get_lan(app, dsn)
            if not lan.get("lanip_key"):
                _LOGGER.warning("No LAN key for device %s (%s), skipping", dsn, device.get("product_name"))
                continue
            result.append(
                CloudDevice(
                    name=device.get("product_name") or dsn,
                    dsn=dsn,
                    oem_model=device.get("oem_model") or "",
                    sw_version=device.get("sw_version") or "",
                    mac=(device.get("mac") or "").replace(":", ""),
                    lan_ip=device.get("lan_ip") or "",
                    lanip_key=lan["lanip_key"],
                    lanip_key_id=int(lan.get("lanip_key_id", 0)),
                    temp_unit=temp_unit_for_app(app),
                )
            )
        return result
