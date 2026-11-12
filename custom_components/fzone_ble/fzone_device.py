"""BLE Device handler for FZONE Aquarium Light."""
from __future__ import annotations

import asyncio
import logging
import time
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
        self._transition_task: asyncio.Task[None] | None = None

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

    def _cancel_transition(self) -> None:
        """Cancel any active background transition."""
        if self._transition_task and not self._transition_task.done():
            self._transition_task.cancel()
        self._transition_task = None

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
        transition: float | int | None = None,
    ) -> bool:
        """Turn on lamp with optional RGBW, brightness, and smooth transition."""
        self._cancel_transition()

        target_rgbw = rgbw if rgbw is not None else self._rgbw
        target_brightness = brightness if brightness is not None else (self._brightness if self._is_on else 255)

        if transition is not None and float(transition) > 0:
            self._transition_task = self.hass.async_create_task(
                self._async_run_transition(target_rgbw, target_brightness, float(transition))
            )
            return True

        return await self._async_apply_turn_on(target_rgbw, target_brightness)

    async def _async_apply_turn_on(
        self,
        target_rgbw: tuple[int, int, int, int],
        target_brightness: int,
    ) -> bool:
        """Apply state immediately without transition."""
        self._rgbw = target_rgbw
        self._brightness = target_brightness

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

    async def _async_run_transition(
        self,
        target_rgbw: tuple[int, int, int, int],
        target_brightness: int,
        transition_seconds: float,
    ) -> None:
        """Perform a smooth, gradual transition between current and target state."""
        start_time = time.monotonic()

        if not self._is_on:
            start_brightness = 0
            start_rgbw = target_rgbw
            p_power_on = build_fzone_packet(0x01, [0x01])
            p_mode_manual = build_fzone_packet(0x02, [0x00])
            p_rgbw_zero = build_manual_rgbw_packet(0, 0, 0, 0, co2=self._co2)
            await self.async_send_packet(p_power_on)
            await asyncio.sleep(0.04)
            await self.async_send_packet(p_mode_manual)
            await asyncio.sleep(0.04)
            await self.async_send_packet(p_rgbw_zero)
            self._is_on = True
            self._notify_callbacks()
        else:
            start_brightness = self._brightness
            start_rgbw = self._rgbw

        step_interval = 5.0 if transition_seconds >= 30.0 else max(0.5, transition_seconds / 20.0)

        _LOGGER.info(
            "[%s] Starting light transition over %.1fs: Brightness %d -> %d, RGBW %s -> %s (step: %.1fs)",
            self.address,
            transition_seconds,
            start_brightness,
            target_brightness,
            start_rgbw,
            target_rgbw,
            step_interval,
        )

        last_notify = start_time

        try:
            while True:
                await asyncio.sleep(step_interval)
                now = time.monotonic()
                elapsed = now - start_time
                progress = min(1.0, elapsed / transition_seconds)

                cur_brightness = round(start_brightness + (target_brightness - start_brightness) * progress)
                cur_r = round(start_rgbw[0] + (target_rgbw[0] - start_rgbw[0]) * progress)
                cur_g = round(start_rgbw[1] + (target_rgbw[1] - start_rgbw[1]) * progress)
                cur_b = round(start_rgbw[2] + (target_rgbw[2] - start_rgbw[2]) * progress)
                cur_w = round(start_rgbw[3] + (target_rgbw[3] - start_rgbw[3]) * progress)

                b_ratio = cur_brightness / 255.0
                r_pct = round((cur_r / 255.0) * b_ratio * 100)
                g_pct = round((cur_g / 255.0) * b_ratio * 100)
                b_pct = round((cur_b / 255.0) * b_ratio * 100)
                w_pct = round((cur_w / 255.0) * b_ratio * 100)

                self._brightness = cur_brightness
                self._rgbw = (cur_r, cur_g, cur_b, cur_w)

                p_rgbw = build_manual_rgbw_packet(r_pct, g_pct, b_pct, w_pct, co2=self._co2)
                await self.async_send_packet(p_rgbw)

                if (now - last_notify) >= 10.0 or progress >= 1.0:
                    self._notify_callbacks()
                    last_notify = now

                if progress >= 1.0:
                    break

            if target_brightness == 0:
                p_power_off = build_fzone_packet(0x01, [0x00])
                await self.async_send_packet(p_power_off)
                self._is_on = False
                self._notify_callbacks()

            _LOGGER.info("[%s] Light transition completed successfully.", self.address)

        except asyncio.CancelledError:
            _LOGGER.info("[%s] Light transition cancelled by new command.", self.address)
            raise
        except Exception as err:
            _LOGGER.error("[%s] Error during light transition: %s", self.address, err)

    async def async_turn_off(self, transition: float | int | None = None) -> bool:
        """Turn off lamp (Power OFF and 0% channels), with optional transition."""
        self._cancel_transition()

        if transition is not None and float(transition) > 0 and self._is_on:
            self._transition_task = self.hass.async_create_task(
                self._async_run_transition(self._rgbw, 0, float(transition))
            )
            return True

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
        self._cancel_transition()
        async with self._lock:
            if self._client:
                try:
                    await self._client.disconnect()
                except Exception:
                    pass
                self._client = None
