"""Config flow for FZONE BLE Aquarium Light integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.const import CONF_ADDRESS, CONF_NAME
from homeassistant.data_entry_flow import FlowResult

from .const import CONF_MAC, DEFAULT_NAME, DOMAIN, SERVICE_UUID

_LOGGER = logging.getLogger(__name__)


class FzoneBLEConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for FZONE BLE."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, str] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle bluetooth discovery."""
        _LOGGER.debug(
            "Discovered FZONE BLE device: %s (%s)",
            discovery_info.name,
            discovery_info.address,
        )
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or DEFAULT_NAME,
            "address": discovery_info.address,
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm discovery."""
        assert self._discovery_info is not None
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_info.name or DEFAULT_NAME,
                data={
                    CONF_MAC: self._discovery_info.address,
                    CONF_NAME: self._discovery_info.name or DEFAULT_NAME,
                },
            )

        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": self._discovery_info.name or DEFAULT_NAME,
                "address": self._discovery_info.address,
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle user step (manual MAC or device picker)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_MAC].strip().upper()
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()

            name = user_input.get(CONF_NAME, DEFAULT_NAME)
            return self.async_create_entry(
                title=name,
                data={
                    CONF_MAC: address,
                    CONF_NAME: name,
                },
            )

        # Look for nearby discovered devices
        current_addresses = self._async_current_ids()
        for discovery in async_discovered_service_info(self.hass, connectable=True):
            if discovery.address in current_addresses:
                continue
            name = discovery.name or discovery.address
            if (
                "SmartAqua" in name
                or "BRITE" in name
                or "F102" in name
                or "FZONE" in name
                or "FZ_" in name
                or SERVICE_UUID in discovery.service_uuids
            ):
                self._discovered_devices[discovery.address] = f"{name} ({discovery.address})"

        if self._discovered_devices:
            schema = vol.Schema(
                {
                    vol.Required(CONF_MAC): vol.In(self._discovered_devices),
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                }
            )
        else:
            schema = vol.Schema(
                {
                    vol.Required(CONF_MAC): str,
                    vol.Optional(CONF_NAME, default=DEFAULT_NAME): str,
                }
            )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )
