"""Smoke-test every integration module against the installed Home Assistant API."""

import importlib

import pytest


@pytest.mark.parametrize(
    "module",
    (
        "ayla_cloud",
        "binary_sensor",
        "bitmap",
        "climate",
        "config_flow",
        "const",
        "device",
        "diagnostics",
        "encryption",
        "entity",
        "lan_server",
        "protocol",
        "scanner",
        "sensor",
        "switch",
    ),
)
def test_module_imports(module: str):
    importlib.import_module(f"custom_components.aeh_w4e1.{module}")
