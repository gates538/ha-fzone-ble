"""Models for the FZONE BLE integration."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fzone_device import FzoneBLEDevice


@dataclass
class FzoneData:
    """Runtime data for FZONE BLE."""

    device: FzoneBLEDevice
