"""Tests for the best-effort subnet scanner."""

from ipaddress import ip_network

import pytest
from aiohttp import ClientSession, web

from custom_components.aeh_w4e1.scanner import (
    DiscoveredModule,
    _probe_host,
    infer_network,
    scan_subnet,
)


async def _start_status_app(handlers: dict[str, object]) -> tuple[web.AppRunner, int]:
    app = web.Application()
    for path, handler in handlers.items():
        app.router.add_get(path, handler)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    return runner, runner.addresses[0][1]


async def test_probe_host_recognizes_ayla_fingerprint():
    async def ayla_status(request: web.Request) -> web.Response:
        return web.json_response(
            {"mac": "11:22:33:44:55:66", "lan_ip": "127.0.0.1", "dsn": "AC000W000000000"}
        )

    runner, port = await _start_status_app({"/status.json": ayla_status})
    try:
        async with ClientSession() as session:
            module = await _probe_host(session, "127.0.0.1", port)
            assert isinstance(module, DiscoveredModule)
            assert module.ip == "127.0.0.1"
            assert module.mac == "112233445566"
            assert module.extra["dsn"] == "AC000W000000000"
    finally:
        await runner.cleanup()


async def test_probe_host_rejects_non_ayla_payloads():
    async def printer_status(request: web.Request) -> web.Response:
        return web.json_response({"hostname": "printer", "status": "idle"})

    async def mac_only(request: web.Request) -> web.Response:
        return web.json_response({"mac": "aa:bb:cc:dd:ee:ff"})

    async def html_page(request: web.Request) -> web.Response:
        return web.Response(content_type="text/html", text="<html>hi</html>")

    runner, port = await _start_status_app(
        {
            "/status.json": printer_status,
            "/mac-only.json": mac_only,
            "/page": html_page,
        }
    )
    try:
        async with ClientSession() as session:
            # Printer: no `mac` key. Mac-only: no second Ayla-ish key.
            # HTML page: not JSON. None of them match the fingerprint.
            assert await _probe_host(session, "127.0.0.1", port) is None
    finally:
        await runner.cleanup()


async def test_scan_subnet_finds_and_filters_known_macs():
    """A /30 host range containing the fake module: discovery + known filter."""
    async def ayla_status(request: web.Request) -> web.Response:
        return web.json_response({"mac": "aa:bb:cc:dd:ee:ff", "model": "AEH-W4E1"})

    runner, port = await _start_status_app({"/status.json": ayla_status})
    try:
        # 127.0.0.0/30 -> hosts 127.0.0.1 and 127.0.0.2; our fake answers on .1
        network = ip_network("127.0.0.0/30", strict=False)
        async with ClientSession() as session:
            found = await scan_subnet(session, network, known_macs=None, port=port)
            assert [m.mac for m in found] == ["aabbccddeeff"]

            known = await scan_subnet(
                session, network, known_macs={"aabbccddeeff"}, port=port
            )
            assert known == []
    finally:
        await runner.cleanup()


def test_infer_network():
    network = infer_network("192.168.1.77")
    assert network is not None
    assert str(network) == "192.168.1.0/24"
    assert infer_network("not-an-ip") is None
