"""Light platform for FZONE BLE Aquarium Light."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_RGBW_COLOR,
    ATTR_RGB_COLOR,
    ATTR_HS_COLOR,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_WHITE,
    ColorMode,
    LightEntity,
)
import homeassistant.util.color as color_util
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .fzone_device import FzoneBLEDevice
from .models import FzoneData

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the FZONE BLE light platform."""
    data: FzoneData = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([FzoneLightEntity(data.device, entry)])


class FzoneLightEntity(LightEntity):
    """Representation of an FZONE BLE Aquarium Light."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_color_mode = ColorMode.RGBW
    _attr_supported_color_modes = {ColorMode.RGBW}
    _attr_should_poll = False

    def __init__(self, device: FzoneBLEDevice, entry: ConfigEntry) -> None:
        """Initialize the light entity."""
        self._device = device
        self._entry = entry
        self._attr_unique_id = f"{device.address}_light"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device.address)},
            name=device.name,
            manufacturer="FZONE",
            model="SmartAqua BRITE (F102)",
            sw_version="1.0.0",
        )

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._device.is_on

    @property
    def brightness(self) -> int:
        """Return the brightness of this light between 0..255."""
        return self._device.brightness

    @property
    def rgbw_color(self) -> tuple[int, int, int, int]:
        """Return the RGBW color value [0..255, 0..255, 0..255, 0..255]."""
        return self._device.rgbw_color

    @property
    def rgb_color(self) -> tuple[int, int, int]:
        """Return the RGB color representation."""
        return (self._device.rgbw_color[0], self._device.rgbw_color[1], self._device.rgbw_color[2])

    @property
    def available(self) -> bool:
        """Return True so entity is always actionable in UI."""
        return True

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on, converting any UI color format to RGBW."""
        rgbw = kwargs.get(ATTR_RGBW_COLOR)
        if rgbw is None and ATTR_RGB_COLOR in kwargs:
            r, g, b = kwargs[ATTR_RGB_COLOR]
            rgbw = (int(r), int(g), int(b), 0)
        elif rgbw is None and ATTR_HS_COLOR in kwargs:
            hs = kwargs[ATTR_HS_COLOR]
            r, g, b = color_util.color_hs_to_RGB(hs[0], hs[1])
            rgbw = (int(r), int(g), int(b), 0)
        elif rgbw is None and ATTR_COLOR_TEMP_KELVIN in kwargs:
            r, g, b = color_util.color_temperature_kelvin_to_rgb(kwargs[ATTR_COLOR_TEMP_KELVIN])
            rgbw = (int(r), int(g), int(b), 255)
        elif rgbw is None and ATTR_WHITE in kwargs:
            w = int(kwargs[ATTR_WHITE])
            rgbw = (0, 0, 0, w)

        brightness = kwargs.get(ATTR_BRIGHTNESS)

        await self._device.async_turn_on(rgbw=rgbw, brightness=brightness)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._device.async_turn_off()
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        self._device.register_callback(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        self._device.remove_callback(self.async_write_ha_state)
