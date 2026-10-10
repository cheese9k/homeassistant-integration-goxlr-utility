"""Audio channels with live volume and fader mute state."""

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)

from .const import NAME_MAP
from .entity import GoXLRUtilityEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        [
            GoXLRUtilityMediaPlayer(coordinator, entry.data, key)
            for key in vars(coordinator.data.levels.volumes)
        ]
    )


class GoXLRUtilityMediaPlayer(GoXLRUtilityEntity, MediaPlayerEntity):
    """A channel whose mute association follows profile changes."""

    _attr_device_class = MediaPlayerDeviceClass.SPEAKER

    def __init__(self, coordinator, data, key):
        super().__init__(coordinator, data, key, NAME_MAP[key].name)
        self.channel = NAME_MAP[key].key

    @property
    def supported_features(self):
        features = MediaPlayerEntityFeature.VOLUME_SET
        if self.coordinator.channel_fader(self.channel) is not None:
            features |= MediaPlayerEntityFeature.VOLUME_MUTE
        return features

    @property
    def state(self):
        return MediaPlayerState.IDLE

    @property
    def volume_level(self):
        return self.coordinator.channel_volume(self.channel) / 255

    @property
    def is_volume_muted(self):
        fader = self.coordinator.channel_fader(self.channel)
        return (
            fader is not None
            and getattr(self.coordinator.data.fader_status, fader).mute_state
            != "Unmuted"
        )

    async def async_mute_volume(self, mute):
        if (fader := self.coordinator.channel_fader(self.channel)) is not None:
            await self.coordinator.async_command(
                "SetFaderMuteState", fader.upper(), "MutedToX" if mute else "Unmuted"
            )

    async def async_set_volume_level(self, volume):
        await self.coordinator.async_set_volume(self.channel, volume * 255)
