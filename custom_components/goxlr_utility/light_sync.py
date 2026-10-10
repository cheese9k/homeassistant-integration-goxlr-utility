"""Debounced light/fader synchronization with motor and service echo suppression."""

from __future__ import annotations

import asyncio
import logging
from time import monotonic

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import Context, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event

from .const import CONF_LIGHTS

_LOGGER = logging.getLogger(__name__)
DEBOUNCE_SECONDS = 0.12
MOTOR_SETTLE_SECONDS = 1.5
LIGHT_ECHO_SECONDS = 3.0


class FaderLightSync:
    """One light target per physical fader; light wins at startup/reconnect."""

    def __init__(self, hass, coordinator, options):
        self.hass = hass
        self.coordinator = coordinator
        self.bindings = options.get(CONF_LIGHTS, {})
        self._unsubs = []
        self._timers = {}
        self._directions = {}
        self._tasks = set()
        self._observed = {}
        self._suppress_fader_until = {}
        self._light_echo = {}
        self._online = False
        self._stopped = False
        self._locks = {key: asyncio.Lock() for key in self.bindings}

    def start(self):
        if not self.bindings:
            return
        self._unsubs.append(self.coordinator.async_add_listener(self._mixer_updated))
        self._unsubs.append(
            async_track_state_change_event(
                self.hass, list(self.bindings.values()), self._light_updated
            )
        )
        self._mixer_updated()

    def stop(self):
        self._stopped = True
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()
        self._directions.clear()
        for task in self._tasks:
            task.cancel()

    def _schedule(self, fader, direction, delay=None):
        if self._stopped:
            return
        if (
            delay is None
            and fader in self._timers
            and direction == "fader_to_light"
            and self._directions.get(fader) == direction
        ):
            # Keep the next update deadline while a fader is moving. Read the
            # latest position at that deadline, so continuous motion stays live.
            return
        if timer := self._timers.pop(fader, None):
            timer.cancel()

        def run():
            self._timers.pop(fader, None)
            self._directions.pop(fader, None)
            task = self.hass.async_create_background_task(
                self._sync(fader, direction), f"GoXLR fader {fader} light sync"
            )
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

        self._directions[fader] = direction
        self._timers[fader] = self.hass.loop.call_later(
            DEBOUNCE_SECONDS if delay is None else delay, run
        )

    @callback
    def _mixer_updated(self):
        if not self.coordinator.last_update_success:
            self._online = False
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
            self._directions.clear()
            return
        reconnect = not self._online
        self._online = True
        for fader in self.bindings:
            channel = self.coordinator.fader_channel(fader)
            volume = self.coordinator.channel_volume(channel)
            previous = self._observed.get(fader)
            self._observed[fader] = (channel, volume)
            if reconnect or previous is None or previous[0] != channel:
                # Reassignment must not suddenly change the room's brightness.
                self._schedule(fader, "light_to_fader")
            elif previous[
                1
            ] != volume and monotonic() >= self._suppress_fader_until.get(fader, 0):
                self._schedule(fader, "fader_to_light")

    @staticmethod
    def _brightness(state):
        if state is None or state.state not in (STATE_ON, STATE_OFF):
            return None
        if state.state == STATE_OFF:
            return 0
        brightness = state.attributes.get("brightness")
        return round(brightness) if isinstance(brightness, (int, float)) else None

    @callback
    def _light_updated(self, event):
        state = event.data.get("new_state")
        brightness = self._brightness(state)
        if brightness is None:
            return
        old = event.data.get("old_state")
        if brightness == self._brightness(old):
            return
        for fader, entity_id in self.bindings.items():
            if entity_id != event.data["entity_id"]:
                continue
            echo = self._light_echo.get(fader)
            if (
                echo
                and monotonic() < echo[2]
                and (state.context.id == echo[0] or abs(brightness - echo[1]) <= 1)
            ):
                continue
            self._schedule(fader, "light_to_fader")

    async def _sync(self, fader, direction):
        async with self._locks[fader]:
            if self._stopped or not self.coordinator.last_update_success:
                return
            entity_id = self.bindings[fader]
            state = self.hass.states.get(entity_id)
            brightness = self._brightness(state)
            if brightness is None:
                return
            channel = self.coordinator.fader_channel(fader)
            volume = self.coordinator.channel_volume(channel)
            try:
                if direction == "light_to_fader":
                    if abs(volume - brightness) <= 1:
                        return
                    self._suppress_fader_until[fader] = (
                        monotonic() + MOTOR_SETTLE_SECONDS
                    )
                    await self.coordinator.async_set_volume(channel, brightness)
                    self._suppress_fader_until[fader] = (
                        monotonic() + MOTOR_SETTLE_SECONDS
                    )
                    # Reconcile the hardware's final position, including motor
                    # overshoot or a physical move during the suppression window.
                    if fader not in self._timers:
                        self._schedule(
                            fader,
                            "fader_to_light",
                            MOTOR_SETTLE_SECONDS + DEBOUNCE_SECONDS,
                        )
                else:
                    if monotonic() < self._suppress_fader_until.get(fader, 0):
                        return
                    if abs(volume - brightness) <= 1:
                        return
                    context = Context()
                    self._light_echo[fader] = (
                        context.id,
                        volume,
                        monotonic() + LIGHT_ECHO_SECONDS,
                    )
                    service = "turn_off" if volume == 0 else "turn_on"
                    data = {"entity_id": entity_id}
                    if volume:
                        data.update(brightness=volume, transition=0)
                    await self.hass.services.async_call(
                        "light", service, data, blocking=True, context=context
                    )
            except (HomeAssistantError, ValueError, ConnectionError, TimeoutError):
                self._light_echo.pop(fader, None)
                _LOGGER.exception(
                    "Unable to sync GoXLR fader %s with %s", fader.upper(), entity_id
                )
