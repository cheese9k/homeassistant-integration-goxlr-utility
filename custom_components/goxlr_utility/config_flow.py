"""Config flow for GoXLR Utility integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_LIGHTS,
    CONF_SMOOTHING,
    DEFAULT_PORT,
    DEFAULT_SMOOTHING_SECONDS,
    DOMAIN,
    FADERS,
)
from .helper import CannotConnect, setup_connection

_LOGGER = logging.getLogger(__name__)


STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(
            CONF_PORT,
            default=DEFAULT_PORT,
        ): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
    }
)


async def validate_input(
    hass: HomeAssistant,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    websocket_client = await setup_connection(hass, data)

    try:
        await websocket_client.get_status()
        mixer = websocket_client.mixer
        if mixer is None:
            raise CannotConnect("No mixer found")
        return {
            "title": f"{mixer.hardware.usb_device.manufacturer_name} - {mixer.hardware.usb_device.product_name}",
            "identifier": mixer.hardware.serial_number,
        }
    finally:
        await websocket_client.disconnect()


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for GoXLR Utility."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlow()

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
            except (asyncio.TimeoutError, CannotConnect):
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info["identifier"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=info["title"],
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )


class OptionsFlow(config_entries.OptionsFlow):
    """Map physical faders to dimmable lights or light groups."""

    async def async_step_init(self, user_input=None):
        errors = {}
        existing = self.config_entry.options.get(CONF_LIGHTS, {})
        if user_input is not None:
            bindings = {
                fader: user_input[fader] for fader in FADERS if user_input.get(fader)
            }
            if len(set(bindings.values())) != len(bindings):
                errors["base"] = "duplicate_light"
            else:
                return self.async_create_entry(
                    title="",
                    data={
                        CONF_LIGHTS: bindings,
                        CONF_SMOOTHING: user_input.get(
                            CONF_SMOOTHING, DEFAULT_SMOOTHING_SECONDS
                        ),
                    },
                )
        schema = vol.Schema(
            {
                vol.Optional(
                    fader, description={"suggested_value": existing.get(fader)}
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="light")
                )
                for fader in FADERS
            }
            | {
                vol.Optional(
                    CONF_SMOOTHING,
                    default=self.config_entry.options.get(
                        CONF_SMOOTHING, DEFAULT_SMOOTHING_SECONDS
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0,
                        max=2,
                        step=0.1,
                        unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                )
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
