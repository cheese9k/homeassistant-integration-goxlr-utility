"""Constants for GoXLR Utility."""

import re
from dataclasses import dataclass

from aiohttp import ClientError

DOMAIN = "goxlr_utility"
DEFAULT_PORT = 14564
FADERS = ("a", "b", "c", "d")
CONF_LIGHTS = "fader_lights"
CONF_SMOOTHING = "brightness_smoothing"
DEFAULT_SMOOTHING_SECONDS = 0.2
CONNECTION_ERRORS = (ClientError, OSError, TimeoutError, ConnectionError)


def attribute_key(key: str) -> str:
    """Convert daemon enum names to entity attribute names."""
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", key).lower()


@dataclass(frozen=True)
class MapItem:
    """Display and API names."""

    key: str
    name: str
    icon: str = "mdi:volume-high"


CHANNELS = (
    "Mic",
    "LineIn",
    "Console",
    "System",
    "Game",
    "Chat",
    "Sample",
    "Music",
    "Headphones",
    "MicMonitor",
    "LineOut",
)
BUTTONS = (
    "Bleep",
    "Cough",
    "EffectFx",
    "EffectHardTune",
    "EffectMegaphone",
    "EffectRobot",
    *(f"EffectSelect{i}" for i in range(1, 7)),
    *(f"Fader{i}Mute" for i in range(1, 5)),
    "SamplerBottomLeft",
    "SamplerBottomRight",
    "SamplerClear",
    "SamplerSelectA",
    "SamplerSelectB",
    "SamplerSelectC",
    "SamplerTopLeft",
    "SamplerTopRight",
)
NAME_MAP = {}
KEY_MAP = {}
for api_key in (*CHANNELS, *BUTTONS, "A", "B", "C", "D"):
    key = attribute_key(api_key)
    name = key.replace("_", " ").title()
    if key in FADERS:
        name = f"Fader {FADERS.index(key) + 1}"
    item = MapItem(api_key, name)
    NAME_MAP[key] = NAME_MAP[api_key] = item
    KEY_MAP[key] = api_key
