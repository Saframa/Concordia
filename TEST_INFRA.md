# SFU Test Infrastructure & E2E Test Harness Specification

## 1. Executive Summary & Test Philosophy

The Selective Forwarding Unit (SFU) is a real-time, low-latency UDP server responsible for routing audio datagrams between active voice chat participants without decoding, transcoding, or mixing payloads. Testing an asynchronous, connectionless UDP server requires strict architectural discipline to prevent test flakiness, socket exhaustion, race conditions, or indefinite hangs.

### Core Testing Principles
1. **Opaque-Box & Requirement-Driven**: The test suite treats the SFU as an autonomous network appliance. Verification is conducted by transmitting and receiving standard UDP datagrams over the loopback network (`127.0.0.1`), verifying observable external behaviors against the explicit requirements in `ORIGINAL_REQUEST.md` (R1, R2, R3) and `PROJECT.md`.
2. **Zero-Hang Guarantee**: Every network operation, receive loop, lock acquisition, and thread join must have a bounded, explicit timeout (1.0s for positive assertions, 0.2s for negative assertions). Under no circumstances may any test hang or block indefinitely.
3. **Port & State Isolation via Ephemeral Ports (`port=0`)**: The SFU server and all simulated test clients bind exclusively to port `0`. The operating system dynamically allocates free ephemeral ports, preventing port collisions, port-exhaustion conflicts, and lingering socket states between test runs.
4. **Deterministic Synchronization**: Due to the connectionless nature of UDP, datagram arrival order and processing timing are asynchronous. Tests enforce determinism via registration polling barriers and buffer draining rather than arbitrary, fragile `time.sleep` calls.
5. **Dual Execution Interface**: The test suite is fully executable as both a standalone script (`python test_sfu_flow.py`) returning exit code 0 on success and 1 on failure, and via the standard `pytest` runner (`python -m pytest test_sfu_flow.py -v`). Zero external dependencies outside the Python standard library are required for standalone execution.

---

## 2. Feature Inventory Mapping

Every feature identified in `PROJECT.md` is mapped to its validating tier and specific test case:

| Feature # | Feature Name | Mapped Tier | Test ID | Description |
|-----------|--------------|-------------|---------|-------------|
| 1 | UDP Socket Creation & Binding | Tier 1 | TC-1.1 | IPv4 UDP socket creation, binding to 127.0.0.1 with ephemeral port 0 |
| 2 | Configurable Environment Defaults | Tier 1 | TC-1.1 | Binding resolution and server address reporting |
| 3 | Server Lifecycle Management | Tier 1 | TC-1.1, TC-1.5 | Threaded receiver startup, graceful loopback wakeup stop (<50ms) |
| 4 | Client Connection Registration | Tier 1 | TC-1.1 | Registration of (ip, port) upon `{"action": "connect"}` control frame |
| 5 | Client Disconnection Unregistration | Tier 1 | TC-1.4 | Unregistration of (ip, port) upon `{"action": "disconnect"}` control frame |
| 6 | Malformed Message Resilience | Tier 2 | TC-2.4 | Resilience against truncated JSON, non-UTF8 bytes, and invalid actions |
| 7 | Fast Packet Discrimination | Tier 2 | TC-2.7 | Clean separation of JSON control vs binary audio payloads |
| 8 | Selective Multi-Client Audio Forwarding | Tier 1 | TC-1.2 | Cloning of audio datagram to all other registered clients |
| 9 | Anti-Echo Suppression | Tier 1 | TC-1.3 | Strict exclusion of transmitting client from receiving its own audio |
| 10 | Unregistered Sender Dropping | Tier 2 | TC-2.3 | Silent drop of audio packets from unregistered (ip, port) endpoints |
| 11 | Zero-Processing Audio Passthrough | Tier 1 | TC-1.2 | Byte-for-byte exact forwarding without decoding, transcoding, or mixing |
| 12 | Windows WSAECONNRESET Handling | Tier 2, 3 | TC-2.5, TC-3.2 | Resilience against WinError 10054 when clients close sockets |
| 13 | Test Harness & Runner | Infra | TC-All | In-process `SimulatedClient`, dual standalone/pytest runner |
| 14 | Acceptance Criteria Flow Verification | Tier 1 | TC-1.1 - TC-1.5 | Programmatic verification of all user acceptance criteria (AC-1 to AC-5) |
| 15 | Concurrency & Dynamic Churn Testing | Tier 3 | TC-3.1 - TC-3.3 | Simultaneous bi-directional streams and dynamic roster join/leave |
| 16 | Real-World Workload Simulation | Tier 4 | TC-4.1, TC-4.2 | Multi-client room simulation (N>=3) with packet loss accounting (<1%) |
| 17 | Final E2E Suite Pass & Coverage | Tiers 1-4 | TC-All | 100% passing test suite ready for milestone verification |

---

## 3. Test Architecture & Harness Design

### 3.1 In-Process `SimulatedClient`
The `SimulatedClient` class encapsulates an isolated UDP endpoint simulating a voice chat client:
- **Private Socket**: Bound to `("127.0.0.1", 0)`. Ephemeral port is queried via `getsockname()`.
- **Address Identity**: Stores `(host, port)` matching what the SFU server sees as the sender.
- **Control Framing**:
  - `send_connect()`: Dispatches `{"action": "connect", "client_id": self.client_id}`.
  - `send_disconnect()`: Dispatches `{"action": "disconnect", "client_id": self.client_id}`.
  - `send_raw(data: bytes)`: Sends arbitrary byte sequences to the server.
- **Synchronous Receiving & Assertions**:
  - `receive_packet(timeout=1.0)`: Bounded blocking receive with timeout. Raises `TimeoutError` if no packet arrives.
  - `expect_packet(expected_payload, timeout=1.0)`: Asserts exact byte match of received datagram against expected payload.
  - `expect_no_packet(timeout=0.2)`: Asserts no datagram arrives within 200ms. Crucial for anti-echo and isolation verification.
  - `drain(timeout=0.05)`: Clears pending datagrams in OS buffers before test assertions.
- **Asynchronous Collector**:
  - `start_collector()` / `stop_collector()`: Spawns a background thread that empties the OS socket buffer into a thread-safe `queue.Queue`, preventing buffer overflow during high-throughput burst tests.
- **Context Manager**: Supports `with SimulatedClient(...) as client:` to guarantee socket cleanup.

### 3.2 Dual Execution Interface
`test_sfu_flow.py` supports two execution paradigms:
1. **Pytest Integration**: Each test is a standard `test_*` function compatible with `pytest`. Fixtures provide managed server lifecycle.
2. **Standalone Runner**: When invoked via `python test_sfu_flow.py`, `run_standalone_tests()` executes all test functions sequentially, formats a detailed console summary with elapsed times, and calls `sys.exit(0)` on success or `sys.exit(1)` on failure.

---

## 4. 4-Tier Test Matrix Specification

### Tier 1: Core Acceptance Criteria Verification
- **TC-1.1: Server Startup & Multi-Client Registration (AC-1, AC-2)**:
  Verifies that server binds cleanly on ephemeral port 0 and registers Client A, Client B, and Client C upon receiving `{"action": "connect"}`.
- **TC-1.2: Audio Forwarding Client A -> Client B (AC-3)**:
  Verifies that audio payload sent by Client A is received by Client B byte-for-byte identical (`assert received == sent`).
- **TC-1.3: Anti-Self-Echo Suppression (AC-3)**:
  Verifies that Client A does NOT receive an echo of its own transmitted audio packet (`expect_no_packet(0.2)`).
- **TC-1.4: Client Disconnection (AC-4)**:
  Verifies that sending `{"action": "disconnect"}` unregisters Client B from the server registry.
- **TC-1.5: Disconnected Client Isolation (AC-4)**:
  Verifies that disconnected Client B receives 0 packets from subsequent transmissions by Client A or Client C, while Client A and C continue communicating normally.

### Tier 2: Boundary & Corner Cases
- **TC-2.1: Empty Datagrams (`b""`)**:
  Sends a 0-byte datagram. Server must handle gracefully without crashing or dropping subsequent valid traffic.
- **TC-2.2: Payload Size Boundaries**:
  Tests payloads across key boundaries: 1 byte, 160 bytes (Opus frame), 1472 bytes (standard Ethernet MTU limit), 4096 bytes, and 65507 bytes (maximum IPv4 UDP payload). Verifies all payloads are forwarded without truncation.
- **TC-2.3: Unregistered Sender Traffic**:
  An unregistered client sends audio payloads. Server must silently drop the audio without forwarding it to registered clients.
- **TC-2.4: Malformed Control Frames**:
  Dispatches corrupted control payloads: incomplete JSON (`b'{"action": "con'`), non-UTF8 bytes starting with `{` (`b'{\xff\xfe\x00'`), JSON missing `"action"` key (`b'{"user": "alice"}'`), and unknown actions. Server must not crash and must continue routing.
- **TC-2.5: Duplicate Connects and Disconnects (Idempotency)**:
  Client sends duplicate `connect` frames (must not register duplicate endpoints or cause duplicate packet delivery) and duplicate `disconnect` frames (must not raise KeyError).
- **TC-2.6: Rapid Reconnect from Same Port**:
  Client connects, immediately disconnects, and reconnects from the same socket within < 10ms. Verifies registry consistency and immediate resumption of audio forwarding.
- **TC-2.7: Audio Payload Collision with JSON Delimiters**:
  Audio datagram starting with `{` and ending with `}` that is not valid control JSON. Verifies server treats it as raw audio passthrough without throwing exceptions.

### Tier 3: Concurrency & Dynamic Churn
- **TC-3.1: Concurrent Bi-Directional Audio Streaming**:
  4 clients registered. Clients A and B transmit 20 packets each simultaneously. Verifies C and D receive all 40 packets, A receives B's 20 packets with 0 self-echo, and B receives A's 20 packets with 0 self-echo.
- **TC-3.2: Dynamic Join and Leave During Active Streaming**:
  Client A streams audio continuously. Client B connects mid-stream, and Client C disconnects mid-stream. Verifies thread-safe registry iteration (no `RuntimeError: Set changed size during iteration`), prompt packet reception for B, and immediate cutoff for C.
- **TC-3.3: High-Frequency Burst Ingestion**:
  Client A sends a burst of 100 packets in a tight loop. Verifies server stability, zero deadlock, and consistent delivery to Client B.

### Tier 4: Real-World Workload Simulation
- **TC-4.1: Simulated Multi-Client Voice Room (N >= 3)**:
  4 simulated clients in a shared room. All 4 clients simultaneously transmit 50 sequenced voice frames (200 total injected packets) with background collectors active.
- **TC-4.2: Packet Loss Accounting & Delivery Metrics**:
  Evaluates TC-4.1 packet accounting: Each client receives exactly 150 packets (3 peers * 50 frames). Total room deliveries = 600 packets. Calculates loss rate on local loopback, asserting `loss_rate < 0.01` (1.0% threshold, typically 0.0% on loopback) and verifying strictly monotonic sequence ordering.

---

## 5. UDP Determinism & Flake Prevention Blueprint

1. **Registration Synchronization Barrier**:
   Because UDP is connectionless, sending a connect message is asynchronous. Tests poll `server.is_registered(client.address)` with a fast retry loop (up to 1.0s timeout, 5ms interval) to ensure the server registry has processed the connection before sending audio.
2. **Bounded Assertions**:
   - `expect_packet` timeout: 1.0s (sufficient for high system load while failing fast on real drops).
   - `expect_no_packet` timeout: 0.2s (fast negative verification).
3. **Buffer Draining**:
   `client.drain()` flushes stale datagrams from socket and queue buffers prior to isolation assertions.
4. **Queue-Based Collector Threads**:
   For burst and multi-client streaming tests, `SimulatedClient.start_collector()` drains OS socket buffers into thread-safe Python queues continuously.
5. **Clean Server Teardown**:
   Server `stop()` signals a stop event and sends a wake-up loopback datagram to unblock `socket.recvfrom()`, ensuring server threads terminate cleanly in < 50ms without leaking background daemon threads.

---

## 6. Coverage & Quality Thresholds

- **Acceptance Criteria**: 100% pass rate for AC-1 through AC-5.
- **Test Matrix Execution**: All 16 test cases across Tiers 1-4 must execute and pass cleanly.
- **Process Exit Code**: Standalone execution must exit with code 0 on all passes and code 1 on any failure.
- **Zero Resource Leaks**: All sockets closed and all threads joined at test completion.
