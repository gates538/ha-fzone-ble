"""BLE Device handler for FZONE Aquarium Light."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

from .const import CHARACTERISTIC_UUID, CHARACTERISTIC_NOTIFY_UUID
from .fzone_protocol import (
    build_channel_brightness_packet,
    build_chihiros_packet,
    build_fzone_packet,
    build_manual_rgbw_packet,
    build_switch_manual_packet,
)

_LOGGER = logging.getLogger(__name__)

CHUNK_SIZE = 20
CHUNK_DELAY = 0.02  # 20ms between chunks


class FzoneBLEDevice:
    """Manages BLE connection and state for a single FZONE lamp."""

    def __init__(self, hass: HomeAssistant, address: str, name: str) -> None:
        """Initialize the FZONE BLE device."""
        self.hass = hass
        self.address = address.upper()
        self.name = name

        self._client: BleakClient | None = None
        self._lock = asyncio.Lock()

        # State tracking
        self._is_on: bool = False
        self._brightness: int = 255
        self._rgbw: tuple[int, int, int, int] = (255, 255, 255, 255)
        self._co2: bool = False
        self._available: bool = True

        self._callbacks: list[Any] = []
        self._write_char: str | None = None
        self._notify_char: str | None = None
        self._seq: int = 1

    def _next_seq(self) -> int:
        """Increment sequence counter, skipping reserved byte 0x5a."""
        self._seq = (self._seq + 1) & 0xFFFF
        if (self._seq & 0xFF) == 0x5A:
            self._seq += 1
        return self._seq

    @property
    def is_on(self) -> bool:
        """Return True if the light is on."""
        return self._is_on

    @property
    def brightness(self) -> int:
        """Return current brightness (0..255)."""
        return self._brightness

    @property
    def rgbw_color(self) -> tuple[int, int, int, int]:
        """Return current RGBW tuple (0..255)."""
        return self._rgbw

    @property
    def available(self) -> bool:
        """Return True if device is considered available."""
        return self._available

    def register_callback(self, callback: Any) -> None:
        """Register a state change listener."""
        self._callbacks.append(callback)

    def remove_callback(self, callback: Any) -> None:
        """Remove a registered callback."""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _notify_callbacks(self) -> None:
        """Trigger registered listeners."""
        for cb in self._callbacks:
            try:
                cb()
            except Exception as ex:  # pylint: disable=broad-except
                _LOGGER.debug("Error calling callback for %s: %s", self.name, ex)

    def _notification_handler(self, sender: Any, data: bytearray) -> None:
        """Handle incoming BLE notifications."""
        _LOGGER.debug("[%s] Notification received: %s", self.address, data.hex(" "))

    async def _ensure_connected(self) -> BleakClient:
        """Ensure active BLE connection to the lamp."""
        if self._client and self._client.is_connected:
            return self._client

        _LOGGER.debug("[%s] Searching for BLE device in Home Assistant Bluetooth cache...", self.address)
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.address, connectable=True
        )
        if ble_device is None:
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, self.address, connectable=False
            )

        client: BleakClient
        if ble_device is not None:
            _LOGGER.debug("[%s] Found BLE device: %s. Connecting via Bluetooth Proxy / local adapter...", self.address, ble_device)
            client = await establish_connection(
                BleakClient,
                ble_device,
                self.name,
                max_attempts=3,
                use_services_cache=True,
            )
        else:
            _LOGGER.debug("[%s] Device not in cache. Attempting direct BleakClient connection...", self.address)
            client = BleakClient(self.address, timeout=15.0)
            await client.connect()

        self._client = client

        # Dynamic GATT service and characteristic detection
        write_char = None
        notify_char = None

        for service in client.services:
            for char in service.characteristics:
                props = char.properties
                if "write" in props or "write-without-response" in props:
                    if "ae01" in char.uuid.lower() or "6e400002" in char.uuid.lower():
                        write_char = char.uuid
                    elif write_char is None:
                        write_char = char.uuid
                if "notify" in props:
                    if "ae02" in char.uuid.lower() or "6e400003" in char.uuid.lower():
                        notify_char = char.uuid
                    elif notify_char is None:
                        notify_char = char.uuid

        self._write_char = write_char or CHARACTERISTIC_UUID
        self._notify_char = notify_char or CHARACTERISTIC_NOTIFY_UUID
        _LOGGER.debug("[%s] Selected GATT chars: write=%s, notify=%s", self.address, self._write_char, self._notify_char)

        if self._notify_char:
            try:
                await client.start_notify(self._notify_char, self._notification_handler)
            except Exception as ex:
                _LOGGER.debug("[%s] Optional notification subscription skipped: %s", self.address, ex)

        return client

    async def async_send_packet(self, packet: bytes) -> bool:
        """Send a formatted packet to the lamp over BLE UART characteristic."""
        async with self._lock:
            try:
                client = await self._ensure_connected()
                write_uuid = self._write_char or CHARACTERISTIC_UUID
                _LOGGER.debug("[%s] Sending %d bytes to %s: %s", self.address, len(packet), write_uuid, packet.hex(" "))

                total_len = len(packet)
                if total_len <= CHUNK_SIZE:
                    try:
                        await client.write_gatt_char(write_uuid, packet, response=True)
                    except Exception:
                        await client.write_gatt_char(write_uuid, packet, response=False)
                else:
                    for i in range(0, total_len, CHUNK_SIZE):
                        chunk = packet[i : i + CHUNK_SIZE]
                        try:
                            await client.write_gatt_char(write_uuid, chunk, response=True)
                        except Exception:
                            await client.write_gatt_char(write_uuid, chunk, response=False)
                        if i + CHUNK_SIZE < total_len:
                            await asyncio.sleep(CHUNK_DELAY)

                return True
            except Exception as err:
                _LOGGER.error("[%s] Error sending command to FZONE lamp: %s", self.address, err)
                if self._client:
                    try:
                        await self._client.disconnect()
                    except Exception:
                        pass
                    self._client = None
                return False

    async def async_turn_on(
        self,
        rgbw: tuple[int, int, int, int] | None = None,
        brightness: int | None = None,
    ) -> bool:
        """Turn on lamp with optional RGBW and brightness."""
        if rgbw is not None:
            self._rgbw = rgbw
        if brightness is not None:
            self._brightness = brightness

        b_ratio = self._brightness / 255.0
        r_pct = round((self._rgbw[0] / 255.0) * b_ratio * 100)
        g_pct = round((self._rgbw[1] / 255.0) * b_ratio * 100)
        b_pct = round((self._rgbw[2] / 255.0) * b_ratio * 100)
        w_pct = round((self._rgbw[3] / 255.0) * b_ratio * 100)

        # Fallback to white if all 0 but turning ON
        if (r_pct + g_pct + b_pct + w_pct) == 0 and self._brightness > 0:
            w_pct = max(1, round(b_ratio * 100))

        # Always update local state optimistically
        self._is_on = True
        self._notify_callbacks()

        p_power_on = build_fzone_packet(0x01, [0x01])
        p_mode_manual = build_fzone_packet(0x02, [0x00])
        p_rgbw = build_manual_rgbw_packet(r_pct, g_pct, b_pct, w_pct, co2=self._co2)

        _LOGGER.debug("[%s] Executing turn_on: R=%d%%, G=%d%%, B=%d%%, W=%d%%", self.address, r_pct, g_pct, b_pct, w_pct)
        await self.async_send_packet(p_power_on)
        await asyncio.sleep(0.04)
        await self.async_send_packet(p_mode_manual)
        await asyncio.sleep(0.04)
        return await self.async_send_packet(p_rgbw)

    async def async_turn_off(self) -> bool:
        """Turn off lamp (Power OFF and 0% channels)."""
        self._is_on = False
        self._notify_callbacks()

        p_power_off = build_fzone_packet(0x01, [0x00])
        p_rgbw_off = build_manual_rgbw_packet(0, 0, 0, 0, co2=self._co2)

        _LOGGER.debug("[%s] Executing turn_off", self.address)
        await self.async_send_packet(p_power_off)
        await asyncio.sleep(0.04)
        return await self.async_send_packet(p_rgbw_off)

    async def async_disconnect(self) -> None:
        """Disconnect BLE client."""
        async with self._lock:
            if self._client:
                try:
                    await self._client.disconnect()
                except Exception:
                    pass
                self._client = None
