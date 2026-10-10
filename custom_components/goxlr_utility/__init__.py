"""The GoXLR Utility integration."""

from __future__ import annotations

import asyncio
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .coordinator import GoXLRUtilityDataUpdateCoordinator
from .helper import CannotConnect
from .light_sync import FaderLightSync

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.LIGHT,
    Platform.MEDIA_PLAYER,
    Platform.NUMBER,
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Set up GoXLR Utility from a config entry."""
    coordinator = GoXLRUtilityDataUpdateCoordinator(
        hass,
        _LOGGER,
        entry=entry,
    )

    try:
        await coordinator.setup()
    except (asyncio.TimeoutError, CannotConnect) as exception:
        raise ConfigEntryNotReady(exception) from exception

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await coordinator.cleanup()
        raise

    entry.runtime_data = coordinator

    # Preserve existing entity IDs while making unique IDs device-specific.
    usb = coordinator.data.hardware.usb_device
    legacy_prefix = f"{usb.manufacturer_name}_{usb.product_name}_".lower()
    serial = coordinator.data.hardware.serial_number
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        if entity.unique_id.startswith(legacy_prefix):
            registry.async_update_entity(
                entity.entity_id,
                new_unique_id=f"{serial}_{entity.unique_id[len(legacy_prefix) :]}",
            )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    sync = FaderLightSync(hass, coordinator, entry.options)
    sync.start()
    entry.async_on_unload(sync.stop)

    # Reload entry when its updated.
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        coordinator: GoXLRUtilityDataUpdateCoordinator = entry.runtime_data
        await coordinator.cleanup()

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the config entry when it changed."""
    await hass.config_entries.async_reload(entry.entry_id)
