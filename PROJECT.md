# Project: Python UDP Selective Forwarding Unit (SFU) Server & Minimalist CustomTkinter Client

## Architecture
- **Networking Core**: Standard library `socket.AF_INET`, `socket.SOCK_DGRAM`, `SO_REUSEADDR`. Ephemeral port support (`port=0`).
- **Concurrency Model**: Single background receiver daemon thread with in-line direct forwarding to minimize jitter and packet reordering. Non-blocking shutdown via self-addressed loopback datagram and socket timeout.
- **Client Registry**: Thread-safe Copy-on-Write (`frozenset`) `ClientRegistry` protected by `threading.Lock` for mutations, enabling lock-free O(1) snapshots during high-frequency audio forwarding.
- **Packet Discrimination**: Fast prefix sniffing (`len >= 10 and data.startswith(b'{') and data.endswith(b'}')`) for JSON control frames (`{"action": "connect"}` and `{"action": "disconnect"}`). Raw binary payloads pass through untouched.
- **Selective Forwarding**: Sender exclusion (anti-self-echo rule). Payloads from unregistered senders are silently discarded. Zero audio decoding, transcoding, or mixing.
- **OS Fault Tolerance**: Trapping Windows `ConnectionResetError` (WinError 10054 / WSAECONNRESET) in receive and send loops.
- **Frontend Architecture (`discord_caserito.py`)**:
  - High-End Minimalist Monochrome UI built with `customtkinter`.
  - Double-Bezel (Doppelrand) concentric container architecture (`#111111` outer shell with $R_{outer}=16$, `#161616` inner core with $R_{inner}=12$).
  - Dynamic Zoom-style video grid with $O(N)$ aspect-ratio tiling optimizer, row centering, and debounced window `<Configure>` reflow.
  - Floating pill control island with high-contrast active states (`btn.configure()`).
  - Strict typography resolver prioritizing "Maven Pro" / "Maven" with deterministic fallback to "Segoe UI Variable Display" / "Segoe UI", banning low-grade fonts.
- **Audio & Networking Decoupling**: Clean layer separation between `AudioEngine` (backend) and `VoiceClientApp` (frontend) with 100% preservation of SFU UDP audio protocols (48kHz mono 16-bit PCM, 10ms chunks, 16-byte fixed username headers).
- **RNNoise AI Suppression**: Resilient `AudioDenoiser` adapter interfacing with `pyrnnoise` via direct C ctypes bindings or class methods, with safe fallback to raw PCM so audio never crashes.
- **Testing Architecture**:
  - SFU Test Suite (`test_sfu_flow.py`): Ephemeral port binding, `SimulatedClient` test harness, 4-tier systematic test suite + Tier 5 adversarial hardening.
  - UI Grid Visual Test Harness (`test_ui_grid.py`): Tri-mode execution (Interactive Visual, Automated Headless Check, and Pytest Suite).

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | UDP Socket Creation & Binding | IPv4 UDP socket creation, binding to host/port, SO_REUSEADDR, ephemeral port 0 support | M1 | R1 |
| 2 | Configurable Environment Defaults | Host/Port resolution from `SFU_HOST`, `SFU_PORT` or defaults (0.0.0.0, 50000) | M1 | R1 |
| 3 | Server Lifecycle Management | `start()`, `stop()`, background receiver daemon thread, loopback wake-up shutdown (<50ms) | M1 | R1 |
| 4 | Client Connection Registration | Idempotent registration of `(ip, port)` on JSON `{"action": "connect"}` | M1 | R2 |
| 5 | Client Disconnection Unregistration | Idempotent unregistration of `(ip, port)` on JSON `{"action": "disconnect"}` | M1 | R2 |
| 6 | Malformed Message Resilience | Safe handling of invalid JSON, non-UTF8 bytes, unhandled actions without crashing | M1 | R2 |
| 7 | Fast Packet Discrimination | High-performance separation of JSON control vs raw binary audio without payload mutation | M1 | R2, R3 |
| 8 | Selective Multi-Client Audio Forwarding | Verbatim cloning of audio datagram to all registered peers | M1 | R3 |
| 9 | Anti-Echo Suppression | Strict exclusion of sender `(ip, port)` from forwarding recipients | M1 | R3 |
| 10 | Unregistered Sender Dropping | Discarding audio packets originating from endpoints not in registered clients | M1 | R3 |
| 11 | Zero-Processing Audio Passthrough | Byte-for-byte exact forwarding without decoding, transcoding, or mixing | M1 | R3 |
| 12 | Windows WSAECONNRESET Handling | Trapping and absorbing WinError 10054 when clients disconnect or close ports | M1 | R1, OS |
| 13 | Test Harness & Runner | Standalone and pytest execution (`test_sfu_flow.py`), `SimulatedClient` fixture | E2E | AC-1, AC-5 |
| 14 | Acceptance Criteria Flow Verification | Full programmatic verification of AC-1 to AC-4 (Connect A/B, Forward A->B, Anti-echo A, Disconnect B, Isolation) | E2E | AC-1 - AC-4 |
| 15 | Concurrency & Dynamic Churn Testing | Stress tests for simultaneous talkers and clients joining/leaving mid-stream (Tier 3) | E2E | Spec |
| 16 | Real-World Workload Simulation | Multi-client room simulation (N>=3) with packet accounting and delivery metrics (Tier 4) | E2E | Spec |
| 17 | Final E2E Suite Pass & Coverage Hardening | 100% pass of E2E suite followed by Tier 5 white-box adversarial stress testing | M2 | Dual Track |
| 18 | CustomTkinter Monochrome Theme | Dark minimalist palette (#080808, #111111, #161616, #FFFFFF) | M3 | R1 |
| 19 | Font Fallback & Typography | "Maven Pro" / "Segoe UI Variable Display" font manager | M3 | R1 |
| 20 | Double-Bezel Card Container | Concentric Doppelrand architecture for login & room containers | M3 | R1, SKILL |
| 21 | Floating Pill Control Island | Floating bar with Mute, Deafen, Disconnect pill buttons & states | M3 | R1, R2 |
| 22 | Dynamic Zoom-Style User Grid | Aspect-ratio grid calculator adapting to window geometry | M3 | R2 |
| 23 | Participant Tile Component | Squircle monogram avatar + centered username + speaking ring | M3 | R2 |
| 24 | Debounced Window Resize Handler | Smooth reflow on window `<Configure>` without layout churn | M3 | R2 |
| 25 | SFU Audio & Network Engine Decoupling | Complete preservation of UDP socket, 3 daemon threads, PCM audio | M3 | R4 |
| 26 | RNNoise AI Suppression Adapter | Resilient wrapper over `pyrnnoise` supporting `denoise_frame` | M3 | R4 |
| 27 | Mute/Deafen State Machine Integrity | Bidirectional coupling preserving Discord-accurate behavior | M3 | R4, AC-3 |
| 28 | Visual Test Harness (`test_ui_grid.py`) | Tri-mode runner: interactive, automated headless check, pytest | M3 | R3, AC-2 |
| 29 | Mock Participant Injection API | `show_room_view` and `update_user_list` without audio dependencies | M3 | R3 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Track | Design test infra, `SimulatedClient` harness, 4 tiers of automated test cases, publish `TEST_READY.md` | none | DONE |
| M1 | Core SFU Server Implementation | Implement `sfu/` package (`config.py`, `protocol.py`, `registry.py`, `server.py`) and `sfu_server.py` CLI runner | none | DONE |
| M2 | Final Milestone: Integration & Hardening | Pass 100% of E2E test suite from `TEST_READY.md`, followed by Tier 5 adversarial coverage hardening | M1, E2E | DONE |
| M3 | UI Redesign & Visual Test Harness | Decouple `AudioEngine` & `VoiceClientApp`, build Zoom grid, implement `test_ui_grid.py` | M2 | DONE |
| M4 | Gate Verification & Audit | Multi-agent review (2 Reviewers, 2 Challengers, 1 Auditor) | M3 | PLANNED |

## Interface Contracts

### Control Message JSON Schema
- **Connect**:
  ```json
  {"action": "connect", "username": "Alice"}
  ```
- **Disconnect**:
  ```json
  {"action": "disconnect"}
  ```
- **Room State Broadcast**:
  ```json
  {"action": "room_state", "users": ["Alice", "Bob"]}
  ```

### Audio Datagram Protocol
- Frame size: 976 bytes total.
  - Bytes 0-15: 16-byte fixed UTF-8 username string padded with null bytes (`\x00`).
  - Bytes 16-975: 960 bytes raw 16-bit mono PCM audio (480 samples @ 48kHz, 10ms frame).

### `AudioEngine` Python API Contract
```python
class AudioEngine:
    def __init__(
        self,
        on_user_list: Optional[Callable[[List[str]], None]] = None,
        on_error: Optional[Callable[[str, str], None]] = None
    ) -> None: ...
    def start(self, server_ip: str, server_port: int, username: str, is_host: bool = False) -> bool: ...
    def stop(self) -> None: ...
    def toggle_mute(self) -> Tuple[bool, bool]: ...
    def toggle_deafen(self) -> Tuple[bool, bool]: ...
```

### `VoiceClientApp` Component & Injection Contract
```python
class VoiceClientApp:
    def __init__(self, root: Optional[ctk.CTk] = None) -> None: ...
    def show_room_view(self, username: str, server_info: str = "127.0.0.1:5000", is_host: bool = False) -> None: ...
    def update_user_list(self, users: List[str]) -> None: ...
    def toggle_mute(self) -> None: ...
    def toggle_deafen(self) -> None: ...
    @property
    def grid_cols(self) -> int: ...
    @property
    def user_tiles(self) -> Dict[str, ParticipantTile]: ...
```

### Visual Test Harness Contract (`test_ui_grid.py`)
```bash
# 1. Interactive visual inspection with 6 mock participants
python test_ui_grid.py

# 2. Automated headless assertion suite (exit code 0 in <1.5s)
python test_ui_grid.py --check
python test_ui_grid.py --headless

# 3. Pytest test discovery
python -m pytest test_ui_grid.py -v
```

### E2E Test Suite Contract
```bash
# Standalone execution
python test_sfu_flow.py
# Pytest execution
python -m pytest test_sfu_flow.py -v
```

## Code Layout
```
c:\Users\safra\OneDrive\Escritorio\Proyectos Personales\Discord caserito\
├── sfu/
│   ├── __init__.py
│   ├── config.py
│   ├── protocol.py
│   ├── registry.py
│   └── server.py
├── sfu_server.py
├── test_sfu_flow.py
├── discord_caserito.py
├── test_ui_grid.py
├── PROJECT.md
├── TEST_INFRA.md
├── TEST_READY.md
└── ORIGINAL_REQUEST.md
```
