"""
Core SFU UDP Server Module.

Implements SFUServer using standard library `socket` and `threading`.
Provides low-latency packet routing, fast-prefix discrimination,
thread-safe Copy-on-Write client registration, strict anti-echo forwarding,
Windows WSAECONNRESET resilience, and sub-5ms graceful shutdown.
"""

import errno
import json
import logging
import os
import signal
import socket
import subprocess
import threading
import time
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from sfu.config import DEFAULT_BUFFER_SIZE, DEFAULT_HOST, DEFAULT_PORT, DEFAULT_SOCKET_TIMEOUT, SFUConfig
from sfu.protocol import ControlAction, PacketType, discriminate_packet
from sfu.registry import ClientAddress, ClientRegistry


logger = logging.getLogger(__name__)


class SFUServer:
    """
    Selective Forwarding Unit (SFU) UDP Server.

    Receives audio datagrams from connected clients and forwards them intact
    to all other connected peers, with explicit connection/disconnection lifecycle.
    """

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        buffer_size: Optional[int] = None,
        socket_timeout: Optional[float] = None,
        config: Optional[SFUConfig] = None,
    ) -> None:
        """
        Initialize the SFUServer.

        Args:
            host: Bind host IP/interface. Defaults to SFU_HOST env or '0.0.0.0'.
            port: Bind UDP port (0 for dynamic ephemeral port). Defaults to SFU_PORT env or 50000.
            buffer_size: Max datagram receive buffer size. Defaults to 65535.
            socket_timeout: Socket recv timeout in seconds for loop exit check.
            config: Optional SFUConfig instance to override parameters.
        """
        resolved_config = config or SFUConfig.from_env(
            host=host,
            port=port,
            buffer_size=buffer_size,
            socket_timeout=socket_timeout,
        )

        self.host: str = resolved_config.host
        self.port: int = resolved_config.port
        self.buffer_size: int = resolved_config.buffer_size
        self.socket_timeout: float = resolved_config.socket_timeout

        self._registry = ClientRegistry()
        self._socket: Optional[socket.socket] = None
        self._bound_address: Optional[Tuple[str, int]] = None
        self._thread: Optional[threading.Thread] = None

        self._is_running = threading.Event()
        self._ready_event = threading.Event()

        # Telemetry counters
        self._stats_lock = threading.Lock()
        self._packets_received = 0
        self._audio_forwarded = 0
        self._control_packets = 0
        self._packets_dropped = 0
        
        # Caché de imágenes de perfil en memoria RAM
        self.avatar_cache: Dict[str, Dict[int, Any]] = {}

        # Estado de transmisiones de pantalla activas (username -> stream_url)
        self.active_screen_shares: Dict[str, str] = {}
        self._mediamtx_process: Optional[subprocess.Popen] = None

        # Estado de micrófono y audio de los participantes (username -> {"is_muted": bool, "is_deafened": bool})
        self.user_states: Dict[str, Dict[str, bool]] = {}

    @property
    def server_address(self) -> Tuple[str, int]:
        """
        Returns the bound (host, port) tuple.
        If port=0 was passed, resolves to the actual dynamic ephemeral port allocated by the OS.
        """
        if self._bound_address is not None:
            return self._bound_address
        return (self.host, self.port)

    @property
    def bound_port(self) -> int:
        """Return the actual bound UDP port."""
        return self.server_address[1]

    @property
    def registered_clients(self) -> FrozenSet[ClientAddress]:
        """Return an immutable snapshot of all registered client addresses."""
        return self._registry.clients

    @property
    def client_count(self) -> int:
        """Return the count of currently registered clients."""
        return len(self._registry)

    @property
    def is_running(self) -> bool:
        """Return True if the server receiver loop is active."""
        return self._is_running.is_set()

    def is_registered(self, addr: ClientAddress) -> bool:
        """Check if an address is currently registered."""
        return self._registry.is_registered(addr)

    def get_stats(self) -> Dict[str, int]:
        """Return a copy of the operational counters."""
        with self._stats_lock:
            return {
                "packets_received": self._packets_received,
                "audio_forwarded": self._audio_forwarded,
                "control_packets": self._control_packets,
                "packets_dropped": self._packets_dropped,
                "active_clients": len(self._registry),
            }

    def start(self) -> None:
        """
        Bind the UDP socket and start the background receiver daemon thread.
        Blocks until the socket is bound and the receiver thread is ready.
        """
        if self._is_running.is_set():
            logger.warning("SFUServer is already running.")
            return

        self._ready_event.clear()

        # Create and configure the UDP socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except OSError:
            pass

        try:
            sock.bind((self.host, self.port))
        except Exception:
            sock.close()
            raise

        self._socket = sock
        self._bound_address = sock.getsockname()
        self._socket.settimeout(self.socket_timeout)

        self._is_running.set()

        self._thread = threading.Thread(
            target=self._run_receiver_loop,
            daemon=True,
            name=f"SFU-Receiver-{self.bound_port}",
        )
        self._thread.start()

        # Wait for receiver loop readiness
        if not self._ready_event.wait(timeout=2.0):
            logger.warning("SFUServer receiver loop took longer than expected to initialize.")

        # Iniciar MediaMTX para retransmisión RTSP si el binario existe
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bin_dir = os.path.join(base_dir, "bin")
        mediamtx_bin = os.path.join(bin_dir, "mediamtx.exe")
        mediamtx_cfg = os.path.join(bin_dir, "mediamtx.yml")
        if os.path.exists(mediamtx_bin):
            try:
                # Escribir configuración libre de conflictos de puertos (TCP directo, RTP en 8002/8003)
                mediamtx_content = (
                    "api: no\n"
                    "rtmp: no\n"
                    "hls: no\n"
                    "webrtc: no\n"
                    "srt: no\n"
                    "rtspTransports: [tcp]\n"
                    "rtspAddress: :8554\n"
                    "rtpAddress: :8002\n"
                    "rtcpAddress: :8003\n"
                    "paths:\n"
                    "  all_others:\n"
                )
                with open(mediamtx_cfg, "w", encoding="utf-8") as f:
                    f.write(mediamtx_content)
                logger.info("Created robust mediamtx.yml with TCP transport on 8554.")

                creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                self._mediamtx_process = subprocess.Popen(
                    [mediamtx_bin, mediamtx_cfg],
                    cwd=bin_dir,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags
                )
                logger.info("MediaMTX RTSP relay server started in background (PID: %d)", self._mediamtx_process.pid)
            except Exception as exc:
                logger.warning("Could not start MediaMTX: %s", exc)

        logger.info("SFUServer started on %s:%d", self.server_address[0], self.bound_port)

    def stop(self, timeout: float = 2.0) -> None:
        """
        Gracefully stop the SFUServer.
        Signals the receiver loop, dispatches a loopback wakeup datagram to unblock recvfrom,
        joins the receiver thread (<50ms latency), and closes the socket.
        """
        if not self._is_running.is_set():
            return

        self._is_running.clear()
        bound_port = self.bound_port
        bind_host = self.server_address[0]

        # Send loopback wake-up datagram to immediately unblock recvfrom
        wake_host = "127.0.0.1" if bind_host in ("0.0.0.0", "") else bind_host
        try:
            wake_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            wake_sock.sendto(b"", (wake_host, bound_port))
            wake_sock.close()
        except Exception:
            pass

        # Wait for receiver thread to exit
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            self._thread = None

        # Close the socket
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

        # Terminar subproceso MediaMTX si está activo
        if self._mediamtx_process:
            try:
                self._mediamtx_process.terminate()
                self._mediamtx_process.wait(timeout=1.0)
            except Exception:
                try:
                    self._mediamtx_process.kill()
                except Exception:
                    pass
            self._mediamtx_process = None
            logger.info("MediaMTX stopped.")

        logger.info("SFUServer stopped.")

    def run(self) -> None:
        """
        Blocking entry point for standalone execution.
        Handles SIGINT and SIGTERM gracefully until interrupted.
        """
        self.start()

        stop_called = threading.Event()

        def _signal_handler(signum: int, frame: Any) -> None:
            logger.info("Signal %d received, stopping SFUServer...", signum)
            stop_called.set()

        # Register signals where available
        original_sigint = signal.getsignal(signal.SIGINT)
        original_sigterm = signal.getsignal(signal.SIGTERM)

        try:
            signal.signal(signal.SIGINT, _signal_handler)
            signal.signal(signal.SIGTERM, _signal_handler)
        except (ValueError, AttributeError):
            # Non-main thread or unsupported platform
            pass

        try:
            while not stop_called.is_set() and self._is_running.is_set():
                stop_called.wait(timeout=0.5)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received, stopping SFUServer...")
        finally:
            self.stop()
            try:
                signal.signal(signal.SIGINT, original_sigint)
                signal.signal(signal.SIGTERM, original_sigterm)
            except (ValueError, AttributeError):
                pass

    def __enter__(self) -> "SFUServer":
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.stop()

    def _run_receiver_loop(self) -> None:
        """Main UDP receiver and direct in-line forwarding loop running in daemon thread."""
        self._ready_event.set()
        
        last_broadcast = time.time()

        while self._is_running.is_set():
            # Periodic room state broadcast to heal dropped UDP packets
            if time.time() - last_broadcast > 5.0:
                self._broadcast_room_state()
                last_broadcast = time.time()
                
            try:
                if self._socket is None:
                    break
                data, addr = self._socket.recvfrom(self.buffer_size)
            except (TimeoutError, socket.timeout):
                # Normal periodic check for self._is_running
                continue
            except ConnectionResetError:
                # Absorb Windows WSAECONNRESET (WinError 10054)
                # Occurs when a previously sent UDP packet reached an unreachable client port
                continue
            except OSError as exc:
                # Socket closed during graceful stop()
                if not self._is_running.is_set():
                    break

                winerror = getattr(exc, "winerror", None)
                wsa_msgsize = getattr(errno, "WSAEMSGSIZE", 10040)
                if exc.errno == wsa_msgsize or winerror == 10040:
                    with self._stats_lock:
                        self._packets_dropped += 1
                    logger.warning(
                        "Received datagram exceeding buffer_size (%d bytes) [WSAEMSGSIZE 10040]; discarded.",
                        self.buffer_size,
                    )
                    continue

                wsa_notsock = getattr(errno, "WSAENOTSOCK", 10038)
                if exc.errno in (errno.EBADF, wsa_notsock) or winerror == 10038:
                    logger.warning("Socket closed unexpectedly in receiver loop: %s", exc)
                    break

                logger.error("Unexpected socket error in receiver loop: %s", exc, exc_info=True)
                continue

            if not self._is_running.is_set():
                break

            with self._stats_lock:
                self._packets_received += 1

            try:
                self._process_packet(data, addr)
            except Exception as exc:
                logger.error(
                    "Unhandled exception processing packet from %s: %s",
                    addr,
                    exc,
                    exc_info=True,
                )

    def _process_packet(self, data: bytes, addr: ClientAddress) -> None:
        """Classify and route incoming datagram."""
        packet_type, payload = discriminate_packet(data)

        if packet_type == PacketType.CONTROL:
            with self._stats_lock:
                self._control_packets += 1
            self._handle_control(payload, addr)
        else:
            self._forward_audio(data, addr)

    def _handle_control(self, payload: Optional[Dict[str, Any]], addr: ClientAddress) -> None:
        """Process connection lifecycle control message."""
        if not payload:
            return

        action = payload.get("action") or payload.get("type")

        if action == ControlAction.CONNECT.value:
            username = payload.get("username", "Unknown")
            newly_added = self._registry.register(addr, username)
            if newly_added:
                logger.info("Client connected: %s as %s (total clients: %d)", addr, username, len(self._registry))
                if username not in self.user_states:
                    self.user_states[username] = {"is_muted": False, "is_deafened": False}
                self._broadcast_room_state()
                
                # Enviar todas las imágenes cacheadas al cliente recién conectado
                import json
                if self._socket is not None:
                    for uname, chunks in self.avatar_cache.items():
                        for chunk_id, chunk_data in chunks.items():
                            try:
                                msg = json.dumps(chunk_data).encode('utf-8')
                                self._socket.sendto(msg, addr)
                            except Exception:
                                pass
                # Enviar transmisiones de pantalla activas al cliente recién conectado
                if self._socket is not None:
                    for s_user, s_url in self.active_screen_shares.items():
                        try:
                            s_msg = json.dumps({
                                "action": "screen_share_start",
                                "username": s_user,
                                "stream_url": s_url
                            }).encode('utf-8')
                            self._socket.sendto(s_msg, addr)
                        except Exception:
                            pass
            else:
                logger.debug("Idempotent connect from %s", addr)

        elif action == ControlAction.DISCONNECT.value:
            client_username = self._registry.clients.get(addr)
            removed = self._registry.unregister(addr)
            if removed:
                logger.info("Client disconnected: %s (total clients: %d)", addr, len(self._registry))
                if client_username and client_username in self.user_states:
                    del self.user_states[client_username]
                self._broadcast_room_state()
                if client_username and client_username in self.active_screen_shares:
                    del self.active_screen_shares[client_username]
                    import json
                    if self._socket is not None:
                        stop_msg = json.dumps({
                            "action": "screen_share_stop",
                            "username": client_username
                        }).encode('utf-8')
                        for peer in self._registry.clients.keys():
                            try:
                                self._socket.sendto(stop_msg, peer)
                            except Exception:
                                pass
            else:
                logger.debug("Idempotent disconnect from unregistered %s", addr)

        elif action == "user_status_update":
            sender_name = payload.get("username")
            if sender_name:
                is_muted = bool(payload.get("is_muted", False))
                is_deafened = bool(payload.get("is_deafened", False))
                self.user_states[sender_name] = {"is_muted": is_muted, "is_deafened": is_deafened}
                import json
                if self._socket is not None:
                    msg = json.dumps(payload).encode('utf-8')
                    for peer in self._registry.get_recipients(addr):
                        try:
                            self._socket.sendto(msg, peer)
                        except Exception:
                            pass

        elif action == "screen_share_start":
            sender_name = payload.get("username")
            stream_url = payload.get("stream_url")
            if sender_name and stream_url:
                self.active_screen_shares[sender_name] = stream_url
                import json
                if self._socket is not None:
                    msg = json.dumps(payload).encode('utf-8')
                    for peer in self._registry.get_recipients(addr):
                        try:
                            self._socket.sendto(msg, peer)
                        except Exception:
                            pass

        elif action == "screen_share_stop":
            sender_name = payload.get("username")
            if sender_name and sender_name in self.active_screen_shares:
                del self.active_screen_shares[sender_name]
            import json
            if self._socket is not None:
                msg = json.dumps(payload).encode('utf-8')
                for peer in self._registry.get_recipients(addr):
                    try:
                        self._socket.sendto(msg, peer)
                    except Exception:
                        pass

        elif action == "avatar_chunk":
            # Guardar en memoria caché y retransmitir a la sala
            sender_name = payload.get("username")
            chunk_id = payload.get("chunk_id")
            if sender_name and chunk_id is not None:
                if sender_name not in self.avatar_cache:
                    self.avatar_cache[sender_name] = {}
                self.avatar_cache[sender_name][chunk_id] = payload
                
                import json
                if self._socket is not None:
                    msg = json.dumps(payload).encode('utf-8')
                    # Retransmitir a los demás clientes
                    for peer in self._registry.get_recipients(addr):
                        try:
                            self._socket.sendto(msg, peer)
                        except Exception:
                            pass
        else:
            logger.warning("Unrecognized control action '%s' from %s", action, addr)

    def _broadcast_room_state(self) -> None:
        """Send a room_state JSON control message to all registered clients."""
        import json
        if self._socket is None:
            return
        
        users = self._registry.get_all_usernames()
        msg = json.dumps({
            "action": "room_state",
            "users": users,
            "user_states": self.user_states
        }).encode('utf-8')
        
        # Broadcast to all currently registered clients
        for addr in self._registry.clients:
            try:
                self._socket.sendto(msg, addr)
            except Exception:
                pass

    def _forward_audio(self, data: bytes, sender: ClientAddress) -> None:
        """
        Forward raw audio payload to all registered clients except the sender.
        
        Strict Anti-Echo Enforcement:
        - Drops packet if sender is unregistered.
        - Excludes sender from recipient list.
        - Strictly NO audio decoding, transcoding, or mixing.
        """
        if not self._registry.is_registered(sender):
            with self._stats_lock:
                self._packets_dropped += 1
            logger.debug("Dropped audio from unregistered sender %s", sender)
            return

        recipients = self._registry.get_recipients(sender)
        if not recipients:
            # Sender is registered, but either alone in room or no other peers
            return

        if self._socket is None:
            return

        forward_count = 0
        for recipient in recipients:
            try:
                self._socket.sendto(data, recipient)
                forward_count += 1
            except ConnectionResetError:
                # Windows WSAECONNRESET on sendto
                continue
            except OSError as e:
                logger.debug("Failed to forward audio to %s: %s", recipient, e)
                continue

        with self._stats_lock:
            self._audio_forwarded += forward_count
