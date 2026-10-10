"""Live fader mute controls."""

from homeassistant.components.switch import SwitchEntity

from .const import FADERS
from .entity import GoXLRUtilityEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [GoXLRFaderMute(entry.runtime_data, entry.data, key) for key in FADERS]
    )


class GoXLRFaderMute(GoXLRUtilityEntity, SwitchEntity):
    _attr_icon = "mdi:volume-off"

    def __init__(self, coordinator, data, key):
        super().__init__(
            coordinator, data, f"fader_{key}_mute", f"Fader {key.upper()} mute"
        )
        self.key = key
        self._key = f"{self._identifier}_fader_{key}_mute"

    @property
    def is_on(self):
        return (
            getattr(self.coordinator.data.fader_status, self.key).mute_state
            != "Unmuted"
        )

    @property
    def extra_state_attributes(self):
        fader = getattr(self.coordinator.data.fader_status, self.key)
        return {
            "channel": fader.channel,
            "mute_state": fader.mute_state,
            "mute_type": fader.mute_type,
        }

    async def async_turn_on(self, **kwargs):
        await self.coordinator.async_command(
            "SetFaderMuteState", self.key.upper(), "MutedToX"
        )

    async def async_turn_off(self, **kwargs):
        await self.coordinator.async_command(
            "SetFaderMuteState", self.key.upper(), "Unmuted"
        )
