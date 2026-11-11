"""Best-effort subnet scanner for Ayla-based modules.

The Ayla LAN protocol has no multicast/announcement mechanism: a module
only becomes reachable once a controller POSTs `local_reg.json` to it. For
network resilience (modules that changed IP after a DHCP lease renewal,
power cycle, or router reboot) we probe the local subnet for the module's
HTTP fingerprint and match candidates by MAC address.

The probe is empirical: Ayla modules answer plain HTTP on port 80 and their
status endpoint returns JSON containing at least a `mac` key. Anything else
(a router, a printer, a TV) does not, so the fingerprint is conservative.
`known_macs` filters candidates that are already configured, so scans stay
quiet in the common case.
"""

import asyncio
import ipaddress
import json
import logging
from dataclasses import dataclass
from ipaddress import IPv4Network

import aiohttp

_LOGGER = logging.getLogger(__name__)

PROBE_PATH = "/status.json"
PROBE_TIMEOUT = 1.2
MAX_CONCURRENT_PROBES = 64
MAX_SCAN_HOSTS = 1024


@dataclass(frozen=True)
class DiscoveredModule:
    ip: str
    mac: str
    extra: dict


def _looks_like_ayla_module(payload: bytes, content_type: str) -> dict | None:
    """Return the parsed JSON when a probe response looks like an Ayla module."""
    if "json" not in content_type.lower() and payload[:1] != b"{":
        return None
    try:
        data = json.loads(payload.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    mac = data.get("mac")
    if not mac or not isinstance(mac, str):
        return None
    # Conservative fingerprint: a `mac` plus at least one other Ayla-ish key.
    ayla_keys = {"lan_ip", "build", "model", "dsn", "version", "ssid", "key"}
    if ayla_keys & data.keys():
        return data
    return None


def _normalize_mac(mac: str) -> str:
    return mac.replace(":", "").replace("-", "").lower()


async def _probe_host(
    session: aiohttp.ClientSession, ip: str, port: int = 80
) -> DiscoveredModule | None:
    url = f"http://{ip}:{port}{PROBE_PATH}" if port != 80 else f"http://{ip}{PROBE_PATH}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=PROBE_TIMEOUT)) as resp:
            if resp.status != 200:
                return None
            payload = await resp.read()
            data = _looks_like_ayla_module(payload, resp.headers.get("Content-Type", ""))
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        return None
    if data is None:
        return None
    return DiscoveredModule(
        ip=ip,
        mac=_normalize_mac(str(data.get("mac"))),
        extra={k: v for k, v in data.items() if k != "mac"},
    )


async def scan_subnet(
    session: aiohttp.ClientSession,
    network: IPv4Network,
    known_macs: set[str] | None = None,
    port: int = 80,
) -> list[DiscoveredModule]:
    """Probe a CIDR range and return Ayla-like modules.

    `known_macs` (normalized, lowercase) are excluded from the results so
    periodic scans only surface *unconfigured* modules; pass None to get
    everything.
    """
    known = {m.lower() for m in (known_macs or set())}
    hosts = [str(h) for h in network.hosts()][:MAX_SCAN_HOSTS]
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_PROBES)

    async def bounded(ip: str) -> DiscoveredModule | None:
        async with semaphore:
            return await _probe_host(session, ip, port)

    results = await asyncio.gather(*(bounded(ip) for ip in hosts))
    found = [r for r in results if r is not None]
    if known:
        found = [r for r in found if r.mac not in known]
    _LOGGER.debug("Subnet scan of %s found %d candidate modules", network, len(found))
    return found


def infer_network(local_ip: str) -> IPv4Network | None:
    """Best-effort /24 network around the given local IP."""
    try:
        address = ipaddress.ip_address(local_ip)
    except ValueError:
        return None
    if address.version != 4:
        return None
    network = ipaddress.ip_network(f"{address}/24", strict=False)
    if isinstance(network, IPv4Network):
        return network
    return None
