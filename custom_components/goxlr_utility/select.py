"""Live fader channel assignments."""

from homeassistant.components.select import SelectEntity

from .const import FADERS, NAME_MAP
from .entity import GoXLRUtilityEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities(
        [GoXLRFaderChannel(entry.runtime_data, entry.data, key) for key in FADERS]
    )


class GoXLRFaderChannel(GoXLRUtilityEntity, SelectEntity):
    _attr_icon = "mdi:swap-horizontal"

    def __init__(self, coordinator, data, key):
        super().__init__(
            coordinator, data, f"fader_{key}_channel", f"Fader {key.upper()} channel"
        )
        self.key = key
        self._key = f"{self._identifier}_fader_{key}_channel"

    @property
    def options(self):
        return [NAME_MAP[key].key for key in vars(self.coordinator.data.levels.volumes)]

    @property
    def current_option(self):
        return self.coordinator.fader_channel(self.key)

    async def async_select_option(self, option):
        await self.coordinator.async_command("SetFader", self.key.upper(), option)
