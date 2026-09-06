"""
SFU Server CLI Entrypoint.

Executable CLI runner and top-level module for the Selective Forwarding Unit.

Usage:
    python sfu_server.py [--host HOST] [--port PORT] [--log-level LEVEL] [-v]
"""

import argparse
import logging
import os
import sys

from sfu import ClientRegistry, ControlAction, PacketType, SFUConfig, SFUServer, discriminate_packet


__all__ = [
    "SFUServer",
    "SFUConfig",
    "ClientRegistry",
    "PacketType",
    "ControlAction",
    "discriminate_packet",
    "main",
]


def setup_logging(level_name: str) -> None:
    """Configure structured console logging."""
    level = getattr(logging, level_name.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def parse_args(args=None) -> argparse.Namespace:
    """Parse command line arguments with environment variable fallbacks."""
    default_host = os.environ.get("SFU_HOST", "0.0.0.0")
    default_port = int(os.environ.get("SFU_PORT", "50000"))
    default_log = os.environ.get("SFU_LOG_LEVEL", "INFO")

    parser = argparse.ArgumentParser(
        description="Selective Forwarding Unit (SFU) UDP Server for real-time voice chat."
    )
    parser.add_argument(
        "--host",
        type=str,
        default=default_host,
        help=f"Host address to bind to (default: {default_host} or SFU_HOST env)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=default_port,
        help=f"UDP port to bind to (default: {default_port} or SFU_PORT env, 0 for dynamic)",
    )
    parser.add_argument(
        "--buffer-size",
        type=int,
        default=65535,
        help="UDP socket receive buffer size (default: 65535)",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=default_log,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help=f"Log verbosity level (default: {default_log})",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose DEBUG logging (shorthand for --log-level DEBUG)",
    )

    return parser.parse_args(args)


def main() -> int:
    """CLI execution entrypoint."""
    args = parse_args()
    log_level = "DEBUG" if args.verbose else args.log_level
    setup_logging(log_level)

    logger = logging.getLogger("sfu_server")
    logger.info("Initializing SFU Server on %s:%d...", args.host, args.port)

    server = SFUServer(
        host=args.host,
        port=args.port,
        buffer_size=args.buffer_size,
    )

    try:
        server.run()
        return 0
    except Exception as exc:
        logger.error("Fatal server error: %s", exc, exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
