"""Writable channel volumes and physical faders, in the daemon's 0..255 scale."""

from homeassistant.components.number import NumberEntity, NumberMode

from .const import FADERS, NAME_MAP
from .entity import GoXLRUtilityEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entities = [
        GoXLRVolume(coordinator, entry.data, key)
        for key in vars(coordinator.data.levels.volumes)
    ]
    entities.extend(
        GoXLRVolume(coordinator, entry.data, key, fader=True) for key in FADERS
    )
    async_add_entities(entities)


class GoXLRVolume(GoXLRUtilityEntity, NumberEntity):
    """A channel volume or a fader that follows its current assignment."""

    _attr_native_min_value = 0
    _attr_native_max_value = 255
    _attr_native_step = 1
    _attr_mode = NumberMode.SLIDER
    _attr_icon = "mdi:tune-vertical"

    def __init__(self, coordinator, data, key, fader=False):
        self.key = key
        self.fader = fader
        super().__init__(
            coordinator,
            data,
            f"{'fader' if fader else 'channel'}_{key}_level",
            f"{f'Fader {key.upper()}' if fader else NAME_MAP[key].name} level",
        )
        self._key = f"{self._identifier}_{'fader' if fader else 'channel'}_{key}_level"

    @property
    def channel(self):
        return (
            self.coordinator.fader_channel(self.key)
            if self.fader
            else NAME_MAP[self.key].key
        )

    @property
    def native_value(self):
        return self.coordinator.channel_volume(self.channel)

    @property
    def extra_state_attributes(self):
        attributes = {
            "channel": self.channel,
            "volume_percent": round(self.native_value / 255 * 100, 2),
        }
        if self.fader:
            fader = getattr(self.coordinator.data.fader_status, self.key)
            attributes.update(
                fader=self.key.upper(),
                mute_state=fader.mute_state,
                mute_type=fader.mute_type,
            )
        return attributes

    async def async_set_native_value(self, value):
        await self.coordinator.async_set_volume(self.channel, value)
