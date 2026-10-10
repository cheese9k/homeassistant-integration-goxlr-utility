"""Verify platforms and reconnection using real Home Assistant entities."""

import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

if sys.platform == "win32":
    pytest.skip(
        "Home Assistant integration tests require Linux", allow_module_level=True
    )

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.goxlr_utility.client import as_model
from custom_components.goxlr_utility.const import CHANNELS, DOMAIN

pytestmark = pytest.mark.usefixtures("enable_custom_integration")


@pytest.fixture
def mixer():
    return as_model(
        {
            "hardware": {
                "serial_number": "SERIAL",
                "usb_device": {
                    "manufacturer_name": "TC-Helicon",
                    "product_name": "GoXLR",
                    "version": [1, 0, 0],
                },
            },
            "levels": {"volumes": {channel: 100 for channel in CHANNELS}},
            "fader_status": {
                key: {"channel": channel, "mute_state": "Unmuted", "mute_type": "All"}
                for key, channel in zip(
                    "ABCD", ("Music", "Chat", "Mic", "System"), strict=True
                )
            },
            "lighting": {
                "simple": {"Accent": {"colour_one": "ffffff"}},
                "buttons": {},
                "faders": {},
            },
            "button_down": {"Bleep": False},
            "profile_name": "Default",
            "mic_profile_name": "Default",
        }
    )


@pytest.fixture
async def setup(hass, mixer):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="GoXLR",
        unique_id="SERIAL",
        data={"host": "localhost", "port": 14564},
    )
    entry.add_to_hass(hass)
    client = SimpleNamespace(
        connected=True,
        mixer=mixer,
        get_status=AsyncMock(),
        command=AsyncMock(),
        disconnect=AsyncMock(),
    )
    with patch(
        "custom_components.goxlr_utility.coordinator.setup_connection",
        return_value=client,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        yield entry, client
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_platform_states_and_dynamic_assignment(hass, setup):
    entry, client = setup
    registry = er.async_get(hass)
    number_id = registry.async_get_entity_id("number", DOMAIN, "SERIAL_fader_a_level")
    select_id = registry.async_get_entity_id("select", DOMAIN, "SERIAL_fader_a_channel")
    switch_id = registry.async_get_entity_id("switch", DOMAIN, "SERIAL_fader_a_mute")
    assert hass.states.get(number_id).state == "100"
    assert hass.states.get(select_id).state == "Music"
    assert hass.states.get(switch_id).state == "off"
    assert hass.states.get(number_id).attributes["channel"] == "Music"
    client.mixer.fader_status.a.channel = "Chat"
    client.mixer.levels.volumes.chat = 173
    entry.runtime_data._updated()
    await hass.async_block_till_done()
    assert hass.states.get(number_id).state == "173"
    assert hass.states.get(select_id).state == "Chat"
    await hass.services.async_call(
        "number", "set_value", {"entity_id": number_id, "value": 255}, blocking=True
    )
    client.command.assert_awaited_with("SetVolume", "Chat", 255)
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": switch_id}, blocking=True
    )
    client.command.assert_awaited_with("SetFaderMuteState", "A", "MutedToX")


async def test_disconnect_and_fresh_reconnect(hass, setup, mixer):
    entry, client = setup
    coordinator = entry.runtime_data
    registry = er.async_get(hass)
    number_id = registry.async_get_entity_id("number", DOMAIN, "SERIAL_fader_a_level")
    client.connected = False
    coordinator._disconnected()
    await hass.async_block_till_done()
    assert hass.states.get(number_id).state == "unavailable"
    with pytest.raises(HomeAssistantError):
        await coordinator.async_set_volume("Music", 40)
    fresh = as_model(
        {
            "fader_status": {"A": {"channel": "Chat"}},
            "levels": {"volumes": {"Chat": 199}},
        }
    )
    # Keep the other entity fields while replacing the data changed offline.
    mixer.fader_status.a = fresh.fader_status.a
    mixer.fader_status.a.mute_state = "Unmuted"
    mixer.fader_status.a.mute_type = "All"
    mixer.levels.volumes.chat = 199
    replacement = SimpleNamespace(
        connected=True,
        mixer=mixer,
        get_status=AsyncMock(),
        command=AsyncMock(),
        disconnect=AsyncMock(),
    )
    with patch(
        "custom_components.goxlr_utility.coordinator.setup_connection",
        return_value=replacement,
    ):
        await coordinator.async_refresh()
    await hass.async_block_till_done()
    replacement.get_status.assert_awaited_once()
    client.disconnect.assert_awaited_once()
    assert hass.states.get(number_id).state == "199"
    assert hass.states.get(number_id).attributes["channel"] == "Chat"
