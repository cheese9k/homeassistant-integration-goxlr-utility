"""Load protocol modules without booting Home Assistant (also works on Windows)."""

import importlib
import sys
from enum import IntFlag
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest


@pytest.fixture
def modules(monkeypatch):
    package = ModuleType("_goxlr_unit")
    package.__path__ = [
        str(Path(__file__).parents[2] / "custom_components" / "goxlr_utility")
    ]
    monkeypatch.setitem(sys.modules, "_goxlr_unit", package)
    # Isolate only HA boundary modules; aiohttp and JSON Patch are real dependencies.
    const = ModuleType("homeassistant.const")
    const.STATE_ON, const.STATE_OFF = "on", "off"
    const.EVENT_HOMEASSISTANT_STOP = "homeassistant_stop"
    core = ModuleType("homeassistant.core")
    core.Context = lambda: SimpleNamespace(id=uuid4().hex)
    core.callback = lambda fn: fn
    exceptions = ModuleType("homeassistant.exceptions")
    exceptions.HomeAssistantError = type("HomeAssistantError", (Exception,), {})
    event = ModuleType("homeassistant.helpers.event")
    event.async_track_state_change_event = Mock(return_value=lambda: None)
    light = ModuleType("homeassistant.components.light")
    light.LightEntityFeature = IntFlag("LightEntityFeature", {"TRANSITION": 32})
    for name, value in (
        ("homeassistant.const", const),
        ("homeassistant.core", core),
        ("homeassistant.exceptions", exceptions),
        ("homeassistant.helpers.event", event),
        ("homeassistant.components.light", light),
    ):
        if sys.platform == "win32":
            monkeypatch.setitem(sys.modules, name, value)
    loaded = SimpleNamespace(
        client=importlib.import_module("_goxlr_unit.client"),
        sync=importlib.import_module("_goxlr_unit.light_sync"),
    )
    yield loaded
    for name in list(sys.modules):
        if name.startswith("_goxlr_unit."):
            del sys.modules[name]
