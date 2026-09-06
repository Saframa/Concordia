"""
Selective Forwarding Unit (SFU) Package.

Exports:
    SFUServer: Main UDP SFU server.
    SFUConfig: Configuration dataclass.
    ClientRegistry: Thread-safe Copy-on-Write client registry.
    PacketType: Packet classification enum (AUDIO, CONTROL).
    ControlAction: Recognized control actions (CONNECT, DISCONNECT).
    discriminate_packet: Fast packet discrimination utility.
"""

from sfu.config import SFUConfig
from sfu.protocol import ControlAction, PacketType, discriminate_packet
from sfu.registry import ClientRegistry
from sfu.server import SFUServer


__all__ = [
    "SFUServer",
    "SFUConfig",
    "ClientRegistry",
    "PacketType",
    "ControlAction",
    "discriminate_packet",
]
