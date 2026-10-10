"""Connection helpers."""

import asyncio

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import GoXLRClient
from .const import CONNECTION_ERRORS


class CannotConnect(HomeAssistantError):
    """Unable to connect to the daemon."""


async def setup_connection(hass, data, serial=None):
    client = GoXLRClient(
        async_get_clientsession(hass), data["host"], data["port"], serial
    )
    try:
        async with asyncio.timeout(10):
            await client.connect()
        return client
    except CONNECTION_ERRORS as error:
        await client.disconnect()
        raise CannotConnect from error
