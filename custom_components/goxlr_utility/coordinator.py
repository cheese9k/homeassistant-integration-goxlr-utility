"""Push state with periodic connection health and snapshot recovery."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .client import GoXLRClient
from .const import CONNECTION_ERRORS, DOMAIN, attribute_key
from .helper import CannotConnect, setup_connection


class GoXLRUtilityDataUpdateCoordinator(DataUpdateCoordinator):
    """Own the socket and publish authoritative daemon state."""

    def __init__(self, hass, logger, *, entry):
        super().__init__(
            hass, logger, name=DOMAIN, update_interval=timedelta(seconds=10)
        )
        self.entry = entry
        self.client: GoXLRClient | None = None
        self.unsub = None
        self._closing = False
        self._command_lock = asyncio.Lock()

    async def setup(self):
        self._closing = False
        self.client = await setup_connection(
            self.hass, self.entry.data, self.entry.unique_id
        )
        self.client.on_update = self._updated
        self.client.on_disconnect = self._disconnected
        if self.unsub is None:
            self.unsub = self.hass.bus.async_listen_once(
                EVENT_HOMEASSISTANT_STOP, self._stop
            )

    async def _stop(self, event):
        await self.cleanup()

    def _updated(self):
        mixer = self.client.mixer
        if mixer is None:
            self.async_set_update_error(
                UpdateFailed("Configured GoXLR is disconnected")
            )
        else:
            self.async_set_updated_data(mixer)

    def _disconnected(self):
        if not self._closing:
            self.async_set_update_error(UpdateFailed("GoXLR WebSocket disconnected"))

    async def cleanup(self):
        self._closing = True
        if self.unsub:
            self.unsub()
            self.unsub = None
        if self.client:
            await self.client.disconnect()
            self.client = None

    async def _async_update_data(self):
        try:
            if self.client is None or not self.client.connected:
                await self.cleanup()
                await self.setup()
            await self.client.get_status()
            mixer = self.client.mixer
            if mixer is None:
                raise UpdateFailed("Configured GoXLR mixer not found")
            return mixer
        except (*CONNECTION_ERRORS, CannotConnect, ValueError) as error:
            await self.cleanup()
            raise UpdateFailed(str(error)) from error

    def fader_channel(self, fader):
        return getattr(self.data.fader_status, fader).channel

    def channel_volume(self, channel):
        return getattr(self.data.levels.volumes, attribute_key(channel))

    def channel_fader(self, channel):
        return next(
            (
                key
                for key, value in vars(self.data.fader_status).items()
                if value.channel == channel
            ),
            None,
        )

    async def async_command(self, name, *args):
        """Serialize writes and reconcile acknowledgements with a snapshot."""
        async with self._command_lock:
            if (
                not self.last_update_success
                or self.client is None
                or not self.client.connected
            ):
                raise HomeAssistantError("GoXLR is unavailable")
            try:
                await self.client.command(name, *args)
                await self.async_request_refresh()
            except (*CONNECTION_ERRORS, ValueError) as error:
                raise HomeAssistantError(f"GoXLR command failed: {error}") from error

    async def async_set_volume(self, channel, value):
        await self.async_command("SetVolume", channel, max(0, min(255, round(value))))
