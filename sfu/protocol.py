"""
SFU Protocol and Packet Discrimination Module.

Provides fast-prefix sniffing and robust validation to discriminate between
JSON control messages and raw binary audio packets.
"""

from enum import Enum
import json
import logging
from typing import Any, Dict, Optional, Tuple


logger = logging.getLogger(__name__)


class PacketType(str, Enum):
    """Classification of packets arriving at the SFU server."""

    AUDIO = "audio"
    CONTROL = "control"


class ControlAction(str, Enum):
    """Recognized control actions."""

    CONNECT = "connect"
    DISCONNECT = "disconnect"


def discriminate_packet(data: bytes) -> Tuple[PacketType, Optional[Dict[str, Any]]]:
    """
    Discriminates between JSON control messages and raw audio payloads.

    Algorithm:
    1. Fast-prefix check: Datagram must be >= 10 bytes and start with '{' and end with '}'.
       (Supports trailing whitespace/newlines if stripped).
    2. If check passes, attempts UTF-8 decode and JSON parsing.
    3. If valid JSON dictionary, classifies as CONTROL.
    4. Any decoding failure, syntax error, non-dict JSON, or non-matching datagram
       is classified as AUDIO without payload mutation.

    Returns:
        (PacketType.CONTROL, payload_dict) if packet is a JSON control frame.
        (PacketType.AUDIO, None) if packet is raw audio payload.
    """
    if len(data) >= 10:
        # Check raw bytes directly first for maximum speed
        if (data.startswith(b"{") and data.endswith(b"}")) or (
            data.lstrip().startswith(b"{") and data.rstrip().endswith(b"}")
        ):
            try:
                text = data.decode("utf-8")
                obj = json.loads(text)
                if isinstance(obj, dict):
                    return PacketType.CONTROL, obj
            except (ValueError, RecursionError, TypeError):
                # Malformed JSON, pathological nesting, or binary audio payload colliding with braces
                pass

    return PacketType.AUDIO, None
