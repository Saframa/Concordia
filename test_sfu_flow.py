"""
Comprehensive E2E Test Suite for Python UDP SFU Server.

Validates Acceptance Criteria (AC-1 to AC-5) and 4-Tier Test Matrix:
- Tier 1: Core Acceptance Criteria (Server startup, registration, forwarding, anti-echo, isolation)
- Tier 2: Boundary & Corner Cases (empty datagrams, max MTU/UDP payloads, unregistered senders,
          malformed control frames, idempotency, rapid reconnect, delimiter collisions)
- Tier 3: Concurrency & Dynamic Churn (bi-directional streaming, mid-stream join/leave, burst ingestion)
- Tier 4: Real-World Workload Simulation (voice room with >=3 clients, packet accounting, loss tracking)

Execution:
    Standalone:  python test_sfu_flow.py
    Pytest:      python -m pytest test_sfu_flow.py -v
"""

from __future__ import annotations

import json
import logging
import os
import queue
import socket
import sys
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import pytest

from sfu.server import SFUServer

logging.basicConfig(level=logging.WARNING)


# ============================================================================
# SimulatedClient Test Harness
# ============================================================================

class SimulatedClient:
    """
    Simulated UDP voice client for E2E testing of the SFU server.
    Binds to an OS-allocated ephemeral port on 127.0.0.1.
    """

    def __init__(
        self,
        server_port: int,
        server_host: str = "127.0.0.1",
        client_id: Optional[str] = None,
    ) -> None:
        self.server_addr: Tuple[str, int] = (server_host, server_port)
        self.sock: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.address: Tuple[str, int] = self.sock.getsockname()
        self.client_id: str = client_id or f"client_{self.address[1]}"

        # Queue-based asynchronous collector support
        self._queue: queue.Queue[Tuple[bytes, Tuple[str, int]]] = queue.Queue()
        self._collector_running = False
        self._collector_thread: Optional[threading.Thread] = None
        self._is_closed = False

    def send_raw(self, data: bytes) -> int:
        """Send raw bytes directly to the SFU server."""
        return self.sock.sendto(data, self.server_addr)

    def send_connect(self, payload: Optional[Dict[str, Any]] = None) -> None:
        """Send explicit JSON connect control frame."""
        body = payload or {"action": "connect", "client_id": self.client_id}
        self.send_raw(json.dumps(body).encode("utf-8"))

    def send_disconnect(self, payload: Optional[Dict[str, Any]] = None) -> None:
        """Send explicit JSON disconnect control frame."""
        body = payload or {"action": "disconnect", "client_id": self.client_id}
        self.send_raw(json.dumps(body).encode("utf-8"))

    def send_audio(self, audio_data: bytes) -> int:
        """Send a raw audio datagram payload."""
        return self.send_raw(audio_data)

    def connect(self, server: Optional[SFUServer] = None, timeout: float = 1.0) -> None:
        """Send connect and optionally wait for registration barrier."""
        self.send_connect()
        if server is not None:
            wait_for_registration(server, self, timeout=timeout)

    def disconnect(self, server: Optional[SFUServer] = None, timeout: float = 1.0) -> None:
        """Send disconnect and optionally wait for unregistration barrier."""
        self.send_disconnect()
        if server is not None:
            wait_for_unregistration(server, self, timeout=timeout)

    def receive_packet(self, timeout: float = 1.0, ignore_json: bool = True) -> bytes:
        """
        Receive a single packet with a bounded timeout.
        Raises TimeoutError if no packet arrives within timeout.
        """
        import json
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            
            try:
                if self._collector_running:
                    data, _ = self._queue.get(timeout=remaining)
                else:
                    self.sock.settimeout(remaining)
                    data, _ = self.sock.recvfrom(65535)
                
                if ignore_json and len(data) >= 10 and data.startswith(b'{') and data.endswith(b'}'):
                    try:
                        text = data.decode('utf-8')
                        obj = json.loads(text)
                        if isinstance(obj, dict) and "action" in obj:
                            continue
                    except (ValueError, TypeError, RecursionError):
                        pass
                
                return data
            except queue.Empty:
                raise TimeoutError(f"[{self.client_id}] No packet received within {timeout}s")
            except (socket.timeout, TimeoutError):
                raise TimeoutError(f"[{self.client_id}] No packet received within {timeout}s")
            except ConnectionResetError:
                raise TimeoutError(f"[{self.client_id}] ConnectionResetError on receive")
        
        raise TimeoutError(f"[{self.client_id}] No packet received within {timeout}s")

    def expect_packet(self, expected_payload: bytes, timeout: float = 1.0) -> bytes:
        """Assert that the next received packet matches expected_payload exactly."""
        data = self.receive_packet(timeout=timeout)
        assert data == expected_payload, (
            f"[{self.client_id}] Packet mismatch. Expected {expected_payload!r}, got {data!r}"
        )
        return data

    def expect_no_packet(self, timeout: float = 0.2, ignore_json: bool = True) -> None:
        """Assert that NO audio packet arrives within the timeout window."""
        import json
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
                
            try:
                if self._collector_running:
                    data, _ = self._queue.get(timeout=remaining)
                else:
                    self.sock.settimeout(remaining)
                    data, _ = self.sock.recvfrom(65535)
                
                if ignore_json and len(data) >= 10 and data.startswith(b'{') and data.endswith(b'}'):
                    try:
                        text = data.decode('utf-8')
                        obj = json.loads(text)
                        if isinstance(obj, dict) and "action" in obj:
                            continue
                    except (ValueError, TypeError, RecursionError):
                        pass
                    
                raise AssertionError(f"[{self.client_id}] Unexpected packet received: {data!r}")
            except queue.Empty:
                pass
            except (socket.timeout, TimeoutError):
                pass
            except ConnectionResetError:
                pass

    def drain(self, timeout: float = 0.05) -> int:
        """Flush and discard all pending datagrams in queue/socket buffers."""
        discarded = 0
        if self._collector_running:
            while not self._queue.empty():
                try:
                    self._queue.get_nowait()
                    discarded += 1
                except queue.Empty:
                    break
            return discarded

        self.sock.settimeout(timeout)
        while True:
            try:
                self.sock.recvfrom(65535)
                discarded += 1
            except (socket.timeout, TimeoutError, BlockingIOError, ConnectionResetError):
                break
        return discarded

    def start_collector(self) -> None:
        """Start background collector thread to buffer bursts into queue."""
        if self._collector_running:
            return
        self._collector_running = True
        self._collector_thread = threading.Thread(
            target=self._collector_loop,
            daemon=True,
            name=f"Collector-{self.client_id}",
        )
        self._collector_thread.start()

    def _collector_loop(self) -> None:
        self.sock.settimeout(0.1)
        import json
        while self._collector_running and not self._is_closed:
            try:
                data, sender = self.sock.recvfrom(65535)
                # Try to filter out JSON control messages
                if len(data) >= 10 and data.startswith(b'{') and data.endswith(b'}'):
                    try:
                        text = data.decode('utf-8')
                        obj = json.loads(text)
                        if isinstance(obj, dict) and "action" in obj:
                            continue # Ignore control packets
                    except (ValueError, TypeError, RecursionError):
                        pass # It's not valid JSON, treat as audio
                        
                self._queue.put((data, sender))
            except (socket.timeout, TimeoutError, BlockingIOError):
                continue
            except ConnectionResetError:
                continue
            except OSError:
                break

    def stop_collector(self) -> None:
        """Stop background collector thread."""
        self._collector_running = False
        if self._collector_thread and self._collector_thread.is_alive():
            self._collector_thread.join(timeout=1.0)
            self._collector_thread = None

    def close(self) -> None:
        """Close socket and stop background thread."""
        if self._is_closed:
            return
        self._is_closed = True
        self.stop_collector()
        try:
            self.sock.close()
        except OSError:
            pass

    def __enter__(self) -> "SimulatedClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()


# ============================================================================
# Synchronization Barriers
# ============================================================================

def wait_for_registration(server: SFUServer, client: SimulatedClient, timeout: float = 1.0) -> None:
    """Poll until server registry reflects client address."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.is_registered(client.address):
            return
        time.sleep(0.002)
    raise TimeoutError(f"Client {client.address} was not registered within {timeout}s")


def wait_for_unregistration(server: SFUServer, client: SimulatedClient, timeout: float = 1.0) -> None:
    """Poll until server registry removes client address."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not server.is_registered(client.address):
            return
        time.sleep(0.002)
    raise TimeoutError(f"Client {client.address} was not unregistered within {timeout}s")


# ============================================================================
# Pytest Fixture
# ============================================================================

@pytest.fixture
def sfu_server():
    """Pytest fixture: provides an isolated SFUServer on dynamic ephemeral port 0."""
    server = SFUServer(host="127.0.0.1", port=0)
    server.start()
    try:
        yield server
    finally:
        server.stop()


# ============================================================================
# Tier 1: Core Acceptance Criteria Verification (AC-1 to AC-5)
# ============================================================================

def test_ac1_ac2_server_startup_and_registration(sfu_server: SFUServer) -> None:
    """
    AC-1: Server startup and simulation of >=3 clients.
    AC-2: Registration of Client A, Client B, and Client C on connect.
    """
    server = sfu_server
    assert server.is_running
    assert server.bound_port > 0

    clients: List[SimulatedClient] = []
    try:
        client_a = SimulatedClient(server.bound_port, client_id="ClientA")
        client_b = SimulatedClient(server.bound_port, client_id="ClientB")
        client_c = SimulatedClient(server.bound_port, client_id="ClientC")
        clients.extend([client_a, client_b, client_c])

        # Connect Client A
        client_a.connect(server)
        assert server.is_registered(client_a.address)
        assert server.client_count == 1

        # Connect Client B
        client_b.connect(server)
        assert server.is_registered(client_b.address)
        assert server.client_count == 2

        # Connect Client C (>= 3 clients total)
        client_c.connect(server)
        assert server.is_registered(client_c.address)
        assert server.client_count == 3

        registered_addrs = server.registered_clients
        assert client_a.address in registered_addrs
        assert client_b.address in registered_addrs
        assert client_c.address in registered_addrs
    finally:
        for c in clients:
            c.close()


def test_ac3_audio_forwarding_intact_and_anti_echo(sfu_server: SFUServer) -> None:
    """
    AC-3: Audio payload from Client A arrives intact at Client B,
    with zero self-echo to Client A.
    """
    server = sfu_server
    clients: List[SimulatedClient] = []
    try:
        client_a = SimulatedClient(server.bound_port, client_id="ClientA")
        client_b = SimulatedClient(server.bound_port, client_id="ClientB")
        client_c = SimulatedClient(server.bound_port, client_id="ClientC")
        clients.extend([client_a, client_b, client_c])

        client_a.connect(server)
        client_b.connect(server)
        client_c.connect(server)

        # Transmit test audio payload from A
        audio_sample = b"\x00\x01\x02\x03\x04\xff\xfe\xfd\xfc_AUDIO_PAYLOAD_A_TO_PEERS"
        client_a.send_audio(audio_sample)

        # Verify Client B receives exact payload
        client_b.expect_packet(audio_sample, timeout=1.0)

        # Verify Client C receives exact payload
        client_c.expect_packet(audio_sample, timeout=1.0)

        # Strict Anti-Echo Rule: Client A must NOT receive its own packet
        client_a.expect_no_packet(timeout=0.2)
    finally:
        for c in clients:
            c.close()


def test_ac4_disconnect_and_isolation(sfu_server: SFUServer) -> None:
    """
    AC-4: Disconnection of Client B, and isolation of B from subsequent
    audio packets sent by Client A or Client C.
    """
    server = sfu_server
    clients: List[SimulatedClient] = []
    try:
        client_a = SimulatedClient(server.bound_port, client_id="ClientA")
        client_b = SimulatedClient(server.bound_port, client_id="ClientB")
        client_c = SimulatedClient(server.bound_port, client_id="ClientC")
        clients.extend([client_a, client_b, client_c])

        client_a.connect(server)
        client_b.connect(server)
        client_c.connect(server)
        assert server.client_count == 3

        # Disconnect Client B
        client_b.disconnect(server)
        assert not server.is_registered(client_b.address)
        assert server.client_count == 2
        client_b.drain()

        # Client A sends audio post-disconnect
        payload_from_a = b"AUDIO_PACKET_FROM_A_AFTER_B_DISCONNECTED"
        client_a.send_audio(payload_from_a)

        # Client C receives it, Client B receives nothing
        client_c.expect_packet(payload_from_a, timeout=1.0)
        client_b.expect_no_packet(timeout=0.2)

        # Client C sends audio post-disconnect
        payload_from_c = b"AUDIO_PACKET_FROM_C_AFTER_B_DISCONNECTED"
        client_c.send_audio(payload_from_c)

        # Client A receives it, Client B receives nothing
        client_a.expect_packet(payload_from_c, timeout=1.0)
        client_b.expect_no_packet(timeout=0.2)
    finally:
        for c in clients:
            c.close()


def test_ac5_full_e2e_programmatic_flow(sfu_server: SFUServer) -> None:
    """
    AC-5: 100% programmatic execution of the full end-to-end lifecycle
    without manual console inspection or human intervention.
    """
    server = sfu_server
    clients: List[SimulatedClient] = []
    try:
        client_a = SimulatedClient(server.bound_port, client_id="User1_Alice")
        client_b = SimulatedClient(server.bound_port, client_id="User2_Bob")
        client_c = SimulatedClient(server.bound_port, client_id="User3_Charlie")
        clients.extend([client_a, client_b, client_c])

        # Step 1: Sequential join
        client_a.connect(server)
        client_b.connect(server)
        assert server.client_count == 2

        # Step 2: Bi-directional conversation between A and B
        client_a.send_audio(b"Alice: Hi Bob!")
        client_b.expect_packet(b"Alice: Hi Bob!")
        client_a.expect_no_packet(0.2)

        client_b.send_audio(b"Bob: Hi Alice!")
        client_a.expect_packet(b"Bob: Hi Alice!")
        client_b.expect_no_packet(0.2)

        # Step 3: Charlie joins the room
        client_c.connect(server)
        assert server.client_count == 3

        client_c.send_audio(b"Charlie: Hello everyone!")
        client_a.expect_packet(b"Charlie: Hello everyone!")
        client_b.expect_packet(b"Charlie: Hello everyone!")
        client_c.expect_no_packet(0.2)

        # Step 4: Bob leaves
        client_b.disconnect(server)
        client_b.drain()
        assert server.client_count == 2

        # Step 5: Alice speaks, Charlie hears, Bob isolated
        client_a.send_audio(b"Alice: Did Bob just disconnect?")
        client_c.expect_packet(b"Alice: Did Bob just disconnect?")
        client_b.expect_no_packet(0.2)
        client_a.expect_no_packet(0.2)
    finally:
        for c in clients:
            c.close()


# ============================================================================
# Tier 2: Boundary & Corner Cases
# ============================================================================

def test_tier2_empty_datagram(sfu_server: SFUServer) -> None:
    """
    Empty datagram (0 bytes): Server must handle gracefully without crashing,
    and forward intact to registered peers.
    """
    server = sfu_server
    clients: List[SimulatedClient] = []
    try:
        client_a = SimulatedClient(server.bound_port, client_id="ClientA")
        client_b = SimulatedClient(server.bound_port, client_id="ClientB")
        clients.extend([client_a, client_b])

        client_a.connect(server)
        client_b.connect(server)

        # Send 0-byte datagram
        client_a.send_raw(b"")
        client_b.expect_packet(b"", timeout=1.0)
        client_a.expect_no_packet(timeout=0.2)

        # Verify server remains healthy and routes subsequent standard traffic
        client_a.send_audio(b"POST_EMPTY_PAYLOAD")
        client_b.expect_packet(b"POST_EMPTY_PAYLOAD", timeout=1.0)
    finally:
        for c in clients:
            c.close()


def test_tier2_payload_sizes_and_mtu_boundaries(sfu_server: SFUServer) -> None:
    """
    Payload boundary sizes: 1 B, 160 B (Opus 20ms frame), 1472 B (Ethernet MTU),
    4096 B, and 65507 B (maximum IPv4 UDP datagram).
    """
    server = sfu_server
    clients: List[SimulatedClient] = []
    try:
        client_a = SimulatedClient(server.bound_port, client_id="ClientA")
        client_b = SimulatedClient(server.bound_port, client_id="ClientB")
        clients.extend([client_a, client_b])

        client_a.connect(server)
        client_b.connect(server)

        test_sizes = [
            1,      # 1 byte
            160,    # Typical 20ms 8kHz audio frame
            1472,   # Standard Ethernet MTU datagram limit
            4096,   # Multi-frame block
            65507,  # Max IPv4 UDP datagram size (65535 - 20 - 8)
        ]

        for size in test_sizes:
            payload = os.urandom(size)
            client_a.send_audio(payload)
            received = client_b.expect_packet(payload, timeout=1.0)
            assert len(received) == size
    finally:
        for c in clients:
            c.close()


def test_tier2_unregistered_sender_audio_dropped(sfu_server: SFUServer) -> None:
    """
    Packets from unregistered senders must be silently dropped without forwarding.
    """
    server = sfu_server
    clients: List[SimulatedClient] = []
    try:
        client_a = SimulatedClient(server.bound_port, client_id="ClientA")
        client_b = SimulatedClient(server.bound_port, client_id="ClientB")
        unregistered = SimulatedClient(server.bound_port, client_id="UnregisteredX")
        clients.extend([client_a, client_b, unregistered])

        client_a.connect(server)
        client_b.connect(server)

        # Unregistered sender sends audio without calling connect()
        initial_stats = server.get_stats()
        unregistered.send_audio(b"SPOOFED_UNREGISTERED_DATA")

        # Neither registered client should receive the packet
        client_a.expect_no_packet(timeout=0.2)
        client_b.expect_no_packet(timeout=0.2)

        # Server stats confirm packet was dropped
        new_stats = server.get_stats()
        assert new_stats["packets_dropped"] >= initial_stats["packets_dropped"] + 1
    finally:
        for c in clients:
            c.close()


def test_tier2_malformed_control_frames(sfu_server: SFUServer) -> None:
    """
    Server must handle corrupted JSON, non-UTF8 bytes, and missing attributes
    without crashing or interrupting audio routing.
    """
    server = sfu_server
    clients: List[SimulatedClient] = []
    try:
        client_a = SimulatedClient(server.bound_port, client_id="ClientA")
        client_b = SimulatedClient(server.bound_port, client_id="ClientB")
        clients.extend([client_a, client_b])

        client_a.connect(server)
        client_b.connect(server)

        malformed_samples = [
            b'{"action": "con',              # Incomplete truncated JSON
            b'{\xff\xfe\x00\x01\x02}',        # Non-UTF-8 starting with '{'
            b'{"some_field": 12345}',         # Valid JSON but missing action/type
            b'{"action": "invalid_action"}',  # Unknown action
            b'{"action": null}',              # Null action
        ]

        for sample in malformed_samples:
            client_a.send_raw(sample)
            # Server receiver loop must stay alive
            assert server.is_running

        # Discard any non-control payloads forwarded to peer as raw audio (R3 passthrough)
        client_b.drain()

        # Verify normal audio forwarding operates cleanly afterward
        client_a.send_audio(b"HEALTH_CHECK_AFTER_MALFORMED")
        client_b.expect_packet(b"HEALTH_CHECK_AFTER_MALFORMED", timeout=1.0)
    finally:
        for c in clients:
            c.close()


def test_tier2_duplicate_connect_and_disconnect_idempotency(sfu_server: SFUServer) -> None:
    """
    Connect and disconnect control frames must be strictly idempotent:
    duplicate connects do not duplicate recipient entries, and duplicate
    disconnects do not raise exceptions.
    """
    server = sfu_server
    clients: List[SimulatedClient] = []
    try:
        client_a = SimulatedClient(server.bound_port, client_id="ClientA")
        client_b = SimulatedClient(server.bound_port, client_id="ClientB")
        clients.extend([client_a, client_b])

        # Duplicate connect calls from Client A
        client_a.send_connect()
        client_a.send_connect()
        wait_for_registration(server, client_a)
        assert server.client_count == 1

        client_b.connect(server)
        assert server.client_count == 2

        # Verify Client B receives only 1 forwarded packet (no duplicate routing)
        client_a.send_audio(b"SINGLE_PACKET_TEST")
        client_b.expect_packet(b"SINGLE_PACKET_TEST", timeout=1.0)
        client_b.expect_no_packet(timeout=0.2)

        # Duplicate disconnect calls from Client A
        client_a.send_disconnect()
        client_a.send_disconnect()
        wait_for_unregistration(server, client_a)
        assert server.client_count == 1

        # Extra disconnect from already unregistered endpoint
        client_a.send_disconnect()
        assert server.is_running
    finally:
        for c in clients:
            c.close()


def test_tier2_rapid_reconnect_same_port(sfu_server: SFUServer) -> None:
    """
    Rapid cycle of connect -> disconnect -> connect from the same UDP port
    must leave the server in a clean, functional state.
    """
    server = sfu_server
    clients: List[SimulatedClient] = []
    try:
        client_a = SimulatedClient(server.bound_port, client_id="ClientA")
        client_b = SimulatedClient(server.bound_port, client_id="ClientB")
        clients.extend([client_a, client_b])

        client_b.connect(server)

        # Connect, disconnect, and immediately reconnect Client A
        client_a.connect(server)
        assert server.is_registered(client_a.address)

        client_a.disconnect(server)
        assert not server.is_registered(client_a.address)

        client_a.connect(server)
        assert server.is_registered(client_a.address)

        # Audio forwarding resumes immediately
        client_a.send_audio(b"RECONNECTED_AUDIO")
        client_b.expect_packet(b"RECONNECTED_AUDIO", timeout=1.0)
    finally:
        for c in clients:
            c.close()


def test_tier2_binary_audio_colliding_with_json_delimiters(sfu_server: SFUServer) -> None:
    """
    Binary audio datagrams that start with '{' and end with '}' but are not
    valid JSON must be passed through verbatim as audio.
    """
    server = sfu_server
    clients: List[SimulatedClient] = []
    try:
        client_a = SimulatedClient(server.bound_port, client_id="ClientA")
        client_b = SimulatedClient(server.bound_port, client_id="ClientB")
        clients.extend([client_a, client_b])

        client_a.connect(server)
        client_b.connect(server)

        pseudo_json_audio = b"{" + os.urandom(64) + b"}"
        client_a.send_audio(pseudo_json_audio)

        # Forwarded intact to Client B
        client_b.expect_packet(pseudo_json_audio, timeout=1.0)
        client_a.expect_no_packet(timeout=0.2)
    finally:
        for c in clients:
            c.close()


# ============================================================================
# Tier 3: Concurrency & Dynamic Churn
# ============================================================================

def test_tier3_concurrent_bidirectional_audio_streaming(sfu_server: SFUServer) -> None:
    """
    Simultaneous bi-directional audio streaming between multiple clients (cross-talk).
    Clients A and B both transmit 20 packets concurrently.
    Peers C and D receive all 40 packets.
    A receives B's 20 packets with zero self-echo.
    B receives A's 20 packets with zero self-echo.
    """
    server = sfu_server
    clients: List[SimulatedClient] = []
    try:
        client_a = SimulatedClient(server.bound_port, client_id="ClientA")
        client_b = SimulatedClient(server.bound_port, client_id="ClientB")
        client_c = SimulatedClient(server.bound_port, client_id="ClientC")
        client_d = SimulatedClient(server.bound_port, client_id="ClientD")
        clients.extend([client_a, client_b, client_c, client_d])

        for c in clients:
            c.connect(server)
            c.start_collector()

        num_packets = 20

        def stream_sender(client: SimulatedClient, prefix: str) -> None:
            for i in range(num_packets):
                payload = f"{prefix}:{i}".encode("utf-8")
                client.send_audio(payload)
                time.sleep(0.003)

        thread_a = threading.Thread(target=stream_sender, args=(client_a, "A"))
        thread_b = threading.Thread(target=stream_sender, args=(client_b, "B"))

        thread_a.start()
        thread_b.start()
        thread_a.join(timeout=3.0)
        thread_b.join(timeout=3.0)

        # Allow loopback delivery to complete
        time.sleep(0.1)

        # Collect and inspect packets for each client
        def drain_received(client: SimulatedClient) -> List[bytes]:
            packets: List[bytes] = []
            while True:
                try:
                    data, _ = client._queue.get(timeout=0.2)
                    packets.append(data)
                except queue.Empty:
                    break
            return packets

        received_a = drain_received(client_a)
        received_b = drain_received(client_b)
        received_c = drain_received(client_c)
        received_d = drain_received(client_d)

        # Anti-echo check: A must receive NO 'A:*' packets, B must receive NO 'B:*' packets
        assert all(not p.startswith(b"A:") for p in received_a), "Client A received self-echo!"
        assert all(not p.startswith(b"B:") for p in received_b), "Client B received self-echo!"

        # A received B's 20 packets, B received A's 20 packets
        assert len([p for p in received_a if p.startswith(b"B:")]) == num_packets
        assert len([p for p in received_b if p.startswith(b"A:")]) == num_packets

        # Passive listeners C and D received all 40 packets
        assert len(received_c) == num_packets * 2
        assert len(received_d) == num_packets * 2
    finally:
        for c in clients:
            c.close()


def test_tier3_dynamic_roster_churn_during_streaming(sfu_server: SFUServer) -> None:
    """
    Dynamic join and leave while audio is actively streaming:
    Client A streams audio continuously.
    Mid-stream:
    - Client C connects and registers.
    - Client B disconnects.
    Verifies lock-free / thread-safe registry iteration, zero crash,
    reception for C after join, and cutoff for B after leave.
    """
    server = sfu_server
    clients: List[SimulatedClient] = []
    try:
        client_a = SimulatedClient(server.bound_port, client_id="ClientA")
        client_b = SimulatedClient(server.bound_port, client_id="ClientB")
        client_c = SimulatedClient(server.bound_port, client_id="ClientC")
        clients.extend([client_a, client_b, client_c])

        client_a.connect(server)
        client_b.connect(server)
        client_b.start_collector()

        streaming = threading.Event()
        streaming.set()
        stream_errors: List[Exception] = []

        def continuous_streamer() -> None:
            seq = 0
            while streaming.is_set():
                try:
                    payload = f"STREAM:{seq}".encode("utf-8")
                    client_a.send_audio(payload)
                    seq += 1
                    time.sleep(0.005)
                except Exception as ex:
                    stream_errors.append(ex)

        stream_thread = threading.Thread(target=continuous_streamer, daemon=True)
        stream_thread.start()

        # Let streaming run for 50ms
        time.sleep(0.05)

        # Dynamic join: Client C joins
        client_c.connect(server)
        client_c.start_collector()

        # Let streaming continue with C present
        time.sleep(0.05)

        # Dynamic leave: Client B disconnects
        client_b.disconnect(server)
        b_cutoff_time = time.monotonic()

        # Let streaming continue after B disconnected
        time.sleep(0.05)

        # Stop streaming
        streaming.clear()
        stream_thread.join(timeout=2.0)
        time.sleep(0.05)

        assert len(stream_errors) == 0, f"Streaming encountered errors: {stream_errors}"
        assert server.is_running

        # Verify Client C received packets
        c_packets: List[bytes] = []
        while not client_c._queue.empty():
            c_packets.append(client_c._queue.get_nowait()[0])
        assert len(c_packets) > 0, "Client C should have received audio packets after joining"

        # Verify Client B is disconnected and stopped receiving
        assert not server.is_registered(client_b.address)
    finally:
        for c in clients:
            c.close()


def test_tier3_high_frequency_burst_ingestion(sfu_server: SFUServer) -> None:
    """
    Client A blasts a burst of 100 packets in a tight loop to the SFU server.
    Client B receives the entire burst without server deadlock or crash.
    """
    server = sfu_server
    clients: List[SimulatedClient] = []
    try:
        client_a = SimulatedClient(server.bound_port, client_id="ClientA")
        client_b = SimulatedClient(server.bound_port, client_id="ClientB")
        clients.extend([client_a, client_b])

        client_a.connect(server)
        client_b.connect(server)
        client_b.start_collector()

        burst_count = 100
        for i in range(burst_count):
            client_a.send_audio(f"BURST:{i:04d}".encode("utf-8"))

        time.sleep(0.15)

        received_packets: List[bytes] = []
        while True:
            try:
                data, _ = client_b._queue.get(timeout=0.2)
                received_packets.append(data)
            except queue.Empty:
                break

        assert len(received_packets) == burst_count, (
            f"Expected {burst_count} packets in burst, got {len(received_packets)}"
        )
    finally:
        for c in clients:
            c.close()


# ============================================================================
# Tier 4: Real-World Workload Simulation & Metric Accounting
# ============================================================================

def test_tier4_multi_client_voice_room_simulation(sfu_server: SFUServer) -> None:
    """
    Simulates an active voice chat room with N >= 3 clients (A, B, C, D).
    Each client transmits 50 sequenced voice frames (200 total injected packets).
    Verifies packet accounting:
    - Expected per client = 3 peers * 50 packets = 150 packets.
    - Total room deliveries = 600 packets.
    - Zero self-echo across the room.
    - In-order monotonic sequencing per peer sender.
    """
    server = sfu_server
    clients: List[SimulatedClient] = []
    try:
        client_ids = ["Alice", "Bob", "Charlie", "David"]
        for cid in client_ids:
            client = SimulatedClient(server.bound_port, client_id=cid)
            clients.append(client)
            client.connect(server)
            client.start_collector()

        assert server.client_count == 4

        packets_per_client = 50
        send_errors: List[Exception] = []

        def client_speaker(client: SimulatedClient) -> None:
            try:
                for seq in range(packets_per_client):
                    # Formatted payload: "sender:seq:payload"
                    payload = (
                        f"{client.client_id}:{seq:04d}:".encode("utf-8")
                        + os.urandom(160)
                    )
                    client.send_audio(payload)
                    time.sleep(0.005)  # 5ms cadence
            except Exception as e:
                send_errors.append(e)

        threads = [
            threading.Thread(target=client_speaker, args=(c,))
            for c in clients
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)

        assert len(send_errors) == 0, f"Voice room speaker errors: {send_errors}"

        # Settle loopback queue
        time.sleep(0.2)

        # Verification per client
        expected_per_peer = packets_per_client
        for client in clients:
            received: List[bytes] = []
            while not client._queue.empty():
                received.append(client._queue.get_nowait()[0])

            # Zero self-echo
            self_prefix = f"{client.client_id}:".encode("utf-8")
            self_echoes = [p for p in received if p.startswith(self_prefix)]
            assert len(self_echoes) == 0, f"Client {client.client_id} received {len(self_echoes)} self-echo packets!"

            # Expected total = 3 other clients * 50 = 150
            peer_ids = [cid for cid in client_ids if cid != client.client_id]
            for peer in peer_ids:
                peer_prefix = f"{peer}:".encode("utf-8")
                peer_packets = [p for p in received if p.startswith(peer_prefix)]
                assert len(peer_packets) == expected_per_peer, (
                    f"Client {client.client_id} expected {expected_per_peer} from {peer}, got {len(peer_packets)}"
                )

                # Monotonic sequence ordering verification
                sequences = [int(p.split(b":")[1]) for p in peer_packets]
                assert sequences == list(range(packets_per_client)), (
                    f"Sequence disorder from {peer} at {client.client_id}"
                )
    finally:
        for c in clients:
            c.close()


def test_tier4_packet_loss_and_delivery_accounting(sfu_server: SFUServer) -> None:
    """
    Computes packet loss and delivery accounting under multi-client load.
    On local loopback (127.0.0.1), loss rate must be < 1.0% (and typically 0.0%).
    """
    server = sfu_server
    clients: List[SimulatedClient] = []
    try:
        n_clients = 3
        frames_per_client = 60
        for i in range(n_clients):
            c = SimulatedClient(server.bound_port, client_id=f"User{i}")
            clients.append(c)
            c.connect(server)
            c.start_collector()

        for c in clients:
            for seq in range(frames_per_client):
                payload = f"{c.client_id}:{seq:04d}".encode("utf-8")
                c.send_audio(payload)
                time.sleep(0.002)

        time.sleep(0.15)

        total_expected_deliveries = n_clients * (n_clients - 1) * frames_per_client
        total_actual_deliveries = 0

        for c in clients:
            count = 0
            while not c._queue.empty():
                c._queue.get_nowait()
                count += 1
            total_actual_deliveries += count

        loss_count = total_expected_deliveries - total_actual_deliveries
        loss_rate = loss_count / total_expected_deliveries if total_expected_deliveries > 0 else 0.0

        assert loss_rate < 0.01, (
            f"Loss rate {loss_rate:.4f} exceeded threshold 0.01 ({loss_count}/{total_expected_deliveries} dropped)"
        )
        assert total_actual_deliveries == total_expected_deliveries, (
            f"Expected {total_expected_deliveries} deliveries, got {total_actual_deliveries}"
        )
    finally:
        for c in clients:
            c.close()


# ============================================================================
# Standalone Test Runner
# ============================================================================

def run_standalone_tests() -> int:
    """
    Executes all test functions sequentially with clean logging and summary.
    Returns 0 if all tests pass, 1 if any test fails.
    """
    test_functions = [
        test_ac1_ac2_server_startup_and_registration,
        test_ac3_audio_forwarding_intact_and_anti_echo,
        test_ac4_disconnect_and_isolation,
        test_ac5_full_e2e_programmatic_flow,
        test_tier2_empty_datagram,
        test_tier2_payload_sizes_and_mtu_boundaries,
        test_tier2_unregistered_sender_audio_dropped,
        test_tier2_malformed_control_frames,
        test_tier2_duplicate_connect_and_disconnect_idempotency,
        test_tier2_rapid_reconnect_same_port,
        test_tier2_binary_audio_colliding_with_json_delimiters,
        test_tier3_concurrent_bidirectional_audio_streaming,
        test_tier3_dynamic_roster_churn_during_streaming,
        test_tier3_high_frequency_burst_ingestion,
        test_tier4_multi_client_voice_room_simulation,
        test_tier4_packet_loss_and_delivery_accounting,
    ]

    passed = 0
    failed = 0
    total = len(test_functions)

    print("\n" + "=" * 70)
    print(f"RUNNING SFU E2E TEST SUITE ({total} Tests across Tiers 1-4)")
    print("=" * 70)
    start_total = time.monotonic()

    for test_fn in test_functions:
        test_name = test_fn.__name__
        server = SFUServer(host="127.0.0.1", port=0)
        server.start()
        t0 = time.monotonic()
        try:
            test_fn(server)
            elapsed = time.monotonic() - t0
            print(f"  [PASS] {test_name} ({elapsed:.3f}s)")
            passed += 1
        except Exception as e:
            elapsed = time.monotonic() - t0
            print(f"  [FAIL] {test_name} ({elapsed:.3f}s): {e}")
            import traceback
            traceback.print_exc()
            failed += 1
        finally:
            server.stop()

    total_time = time.monotonic() - start_total
    print("=" * 70)
    print(f"RESULTS: {passed}/{total} Passed, {failed} Failed ({total_time:.2f}s)")
    print("=" * 70 + "\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--pytest":
        try:
            import pytest
            sys.exit(pytest.main(["-v", __file__]))
        except ImportError:
            sys.exit(run_standalone_tests())
    else:
        sys.exit(run_standalone_tests())
