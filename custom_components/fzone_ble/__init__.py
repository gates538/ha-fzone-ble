"""The FZONE BLE Aquarium Light integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_MAC, CONF_NAME, DEFAULT_NAME, DOMAIN
from .fzone_device import FzoneBLEDevice
from .models import FzoneData

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up FZONE BLE from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    address = entry.data[CONF_MAC]
    name = entry.data.get(CONF_NAME, DEFAULT_NAME)

    _LOGGER.info("Setting up FZONE BLE lamp: %s (%s)", name, address)

    device = FzoneBLEDevice(hass, address, name)
    hass.data[DOMAIN][entry.entry_id] = FzoneData(device=device)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data: FzoneData = hass.data[DOMAIN].pop(entry.entry_id)
        await data.device.async_disconnect()

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)
