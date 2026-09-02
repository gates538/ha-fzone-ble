"""Protocol generator and parser for FZONE / Chihiros BLE aquarium lights."""
from __future__ import annotations

from .const import CMD_MANUAL, CMD_PREVIEW, CMD_QUERY, CMD_VERSION


def build_chihiros_packet(
    cmd_id: int, mode: int, params: list[int], seq: int = 1
) -> bytes:
    """Build a framed Chihiros/FZONE BLE packet with XOR checksum.

    Frame format:
    [cmd_id] [0x01] [length] [seq_hi] [seq_lo] [mode] [params...] [xor_checksum]
    length = len(params) + 5
    """
    length = len(params) + 5
    msg_hi = (seq >> 8) & 0xFF
    msg_lo = seq & 0xFF

    # Skip reserved byte 0x5a in sequence numbers
    if msg_hi == 0x5A:
        msg_hi = 0x5B
    if msg_lo == 0x5A:
        msg_lo = 0x5B

    clean_params = [0x59 if (p & 0xFF) == 0x5A else (p & 0xFF) for p in params]
    frame = [cmd_id, 0x01, length, msg_hi, msg_lo, mode] + clean_params

    # Checksum: XOR of byte 1 through end
    chk = frame[1]
    for b in frame[2:]:
        chk ^= b
    chk &= 0xFF

    # If checksum would be 0x5a, increment sequence and rebuild
    if chk == 0x5A:
        return build_chihiros_packet(cmd_id, mode, params, seq + 1)

    frame.append(chk)
    return bytes(frame)


def build_switch_manual_packet(seq: int = 1) -> bytes:
    """Switch to manual control mode: 0x5A / 0x05 / [0x0B, 0xFF, 0xFF]."""
    return build_chihiros_packet(0x5A, 0x05, [0x0B, 0xFF, 0xFF], seq)


def build_channel_brightness_packet(
    channel: int, brightness: int, seq: int = 1
) -> bytes:
    """Set brightness (0..100) for a specific channel (0..3).

    Channel: 0=Red/White, 1=Green, 2=Blue, 3=White
    """
    ch = max(0, min(3, int(channel)))
    br = max(0, min(100, int(brightness)))
    return build_chihiros_packet(0x5A, 0x07, [ch, br], seq)


def build_fzone_packet(cmd_type: int, payload: list[int] | bytes) -> bytes:
    """Build a framed FZONE BLE packet with 8-bit checksum.
    
    Structure: [0x55] [0xAA] [0x06] [LEN_HI] [LEN_LO] [CMD_TYPE] [PAYLOAD...] [CHECKSUM]
    """
    length = len(payload) + 1  # includes cmd_type
    header = [0x55, 0xAA, 0x06, (length >> 8) & 0xFF, length & 0xFF, cmd_type]
    packet = header + list(payload)
    checksum = sum(packet) % 256
    packet.append(checksum)
    return bytes(packet)


def build_manual_rgbw_packet(
    r: int,
    g: int,
    b: int,
    w: int,
    co2: bool = False,
    mode_id: int = 1,
    extra_channels: list[int] | None = None,
) -> bytes:
    """Build a Manual Mode (0x03) RGBW channel packet.
    
    Channels r, g, b, w are in percentage (0..100).
    """
    r_val = max(0, min(100, int(r)))
    g_val = max(0, min(100, int(g)))
    b_val = max(0, min(100, int(b)))
    w_val = max(0, min(100, int(w)))

    # Extra channels 5..8 (default to 0)
    ch5, ch6, ch7, ch8 = 0, 0, 0, 0
    if extra_channels and len(extra_channels) >= 4:
        ch5, ch6, ch7, ch8 = [max(0, min(100, int(x))) for x in extra_channels[:4]]

    payload = [
        mode_id & 0xFF,
        r_val,
        g_val,
        b_val,
        w_val,
        ch5,
        ch6,
        ch7,
        ch8,
        1 if co2 else 0,
    ]
    return build_fzone_packet(CMD_MANUAL, payload)


def build_preview_packet(
    enable: bool,
    duration_min: int,
    r: int,
    g: int,
    b: int,
    w: int,
) -> bytes:
    """Build temporary preview packet (0x0C)."""
    payload = [
        1 if enable else 0,
        max(1, min(255, int(duration_min))),
        max(0, min(100, int(r))),
        max(0, min(100, int(g))),
        max(0, min(100, int(b))),
        max(0, min(100, int(w))),
        0, 0, 0, 0,
    ]
    return build_fzone_packet(CMD_PREVIEW, payload)


def build_query_status_packet() -> bytes:
    """Build status query packet (0x0E)."""
    return build_fzone_packet(CMD_QUERY, [])


def build_query_version_packet() -> bytes:
    """Build version query packet (0x12)."""
    return build_fzone_packet(CMD_VERSION, [])
