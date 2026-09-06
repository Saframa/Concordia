"""
SFU Configuration Module.

Handles host, port, buffer size, and socket timeout configuration with safe
environment variable fallbacks and defaults.
"""

from dataclasses import dataclass
import os
from typing import Optional


DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 50000
DEFAULT_BUFFER_SIZE = 65535
DEFAULT_SOCKET_TIMEOUT = 0.5


@dataclass(frozen=True)
class SFUConfig:
    """Configuration settings for the SFU Server."""

    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    buffer_size: int = DEFAULT_BUFFER_SIZE
    socket_timeout: float = DEFAULT_SOCKET_TIMEOUT

    @classmethod
    def from_env(
        cls,
        host: Optional[str] = None,
        port: Optional[int] = None,
        buffer_size: Optional[int] = None,
        socket_timeout: Optional[float] = None,
    ) -> "SFUConfig":
        """
        Build an SFUConfig instance resolving explicit values first,
        then environment variables (SFU_HOST, SFU_PORT, SFU_BUFFER_SIZE, SFU_SOCKET_TIMEOUT),
        and finally class defaults.
        """
        # Resolve host
        resolved_host = host
        if resolved_host is None:
            resolved_host = os.environ.get("SFU_HOST", DEFAULT_HOST).strip()
            if not resolved_host:
                resolved_host = DEFAULT_HOST

        # Resolve port
        resolved_port = port
        if resolved_port is None:
            env_port = os.environ.get("SFU_PORT")
            if env_port is not None:
                try:
                    resolved_port = int(env_port.strip())
                except ValueError:
                    resolved_port = DEFAULT_PORT
            else:
                resolved_port = DEFAULT_PORT

        # Resolve buffer_size
        resolved_buffer_size = buffer_size
        if resolved_buffer_size is None:
            env_buf = os.environ.get("SFU_BUFFER_SIZE")
            if env_buf is not None:
                try:
                    resolved_buffer_size = int(env_buf.strip())
                except ValueError:
                    resolved_buffer_size = DEFAULT_BUFFER_SIZE
            else:
                resolved_buffer_size = DEFAULT_BUFFER_SIZE

        # Resolve socket_timeout
        resolved_timeout = socket_timeout
        if resolved_timeout is None:
            env_timeout = os.environ.get("SFU_SOCKET_TIMEOUT")
            if env_timeout is not None:
                try:
                    resolved_timeout = float(env_timeout.strip())
                except ValueError:
                    resolved_timeout = DEFAULT_SOCKET_TIMEOUT
            else:
                resolved_timeout = DEFAULT_SOCKET_TIMEOUT

        return cls(
            host=resolved_host,
            port=resolved_port,
            buffer_size=resolved_buffer_size,
            socket_timeout=resolved_timeout,
        )
