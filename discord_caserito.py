"""
Discord Caserito — Minimalist Voice Chat Client (SFU Architecture)
Awwwards-Tier Minimalist Monochrome UI powered by CustomTkinter.
Decoupled AudioEngine backend with 100% preserved UDP SFU networking.
"""

import os
import sys
import time
import math
import json
import array
import queue
import socket
import threading
import subprocess
import shutil
import base64
import io
from tkinter import filedialog
try:
    from PIL import Image
except ImportError:
    Image = None
from typing import Optional, List, Tuple, Dict, Callable, Any

import tkinter as tk
from tkinter import messagebox
import tkinter.font as tkfont
import customtkinter as ctk

# Optional dependencies with safe fault tolerance
try:
    import pyaudio
except ImportError:
    pyaudio = None

try:
    import numpy as np
except ImportError:
    np = None

# Audio Protocol Constants (SFU Invariant)
CHUNK = 480
RATE = 48000
CHANNELS = 1
FORMAT = pyaudio.paInt16 if pyaudio is not None else 2  # 16-bit PCM

# Minimalist Monochrome Palette Tokens (Awwwards / Hardware Design)
BG_ROOT = "#080808"          # Obsidian Canvas
SHELL_BG = "#111111"         # Outer Double-Bezel Shell
SHELL_BORDER = "#1F1F1F"     # Hairline Outer Stroke (1px)
CORE_BG = "#161616"          # Inner Double-Bezel Core
CORE_BORDER = "#262626"      # Concentric Inner Stroke (1px)
TILE_BG_IDLE = "#181818"     # Participant Tile Surface
TILE_BG_HOVER = "#1E1E1E"    # Participant Tile Hover Surface
TILE_BORDER_IDLE = "#262626" # Tile Inactive Border
TILE_BORDER_SPEAK = "#FFFFFF"# Luminous Speaking Halo (2px)
AVATAR_BG = "#222224"        # Avatar Squircle Background
AVATAR_BORDER = "#333336"    # Avatar Hairline Border
TEXT_PRIMARY = "#FFFFFF"     # Pure White (100% luminance)
TEXT_SECONDARY = "#A3A3A3"   # Platinum Secondary Hierarchy
TEXT_MUTED = "#525252"       # Dark Gray Inactive Text

# Control Island Pill Button Tokens
PILL_IDLE_BG = "#1C1C1E"
PILL_IDLE_BORDER = "#2D2D30"
PILL_IDLE_TEXT = "#FFFFFF"
PILL_IDLE_HOVER = "#28282B"

PILL_MUTE_BG = "#2D1517"
PILL_MUTE_BORDER = "#4D2024"
PILL_MUTE_TEXT = "#F87171"
PILL_MUTE_HOVER = "#3D1B20"

PILL_DEAF_BG = "#2E1D10"
PILL_DEAF_BORDER = "#50321A"
PILL_DEAF_TEXT = "#FBBF24"
PILL_DEAF_HOVER = "#3E2716"

PILL_DANGER_BG = "#241416"
PILL_DANGER_BORDER = "#3D1D21"
PILL_DANGER_TEXT = "#F87171"
PILL_DANGER_HOVER = "#421B20"

# Mock Participants for Testing & Verification
GHOST_USERS = [
    "Satoshi Nakamoto",
    "Ada Lovelace",
    "Alan Turing",
    "Margaret Hamilton",
    "Linus Torvalds",
    "Grace Hopper"
]


class FontManager:
    """
    Font hierarchy resolver prioritizing Maven / Maven Pro with deterministic
    fallback to modern system fonts (Segoe UI Variable Display, Segoe UI),
    while strictly avoiding banned anti-patterns (Arial, Helvetica, Roboto, Inter).
    """
    _resolved_family = None
    _font_cache = {}

    @classmethod
    def get_family(cls) -> str:
        if cls._resolved_family is None:
            try:
                available = set(tkfont.families())
            except Exception:
                available = set()

            # Priority candidates
            candidates = [
                "Maven Pro",
                "Maven",
                "Segoe UI Variable Display",
                "Segoe UI Variable Text",
                "Bahnschrift",
                "Segoe UI",
                "SF Pro Display",
                "sans-serif"
            ]
            cls._resolved_family = next((c for c in candidates if c in available), "Segoe UI")
        return cls._resolved_family

    @classmethod
    def get(cls, size: int, weight: str = "normal") -> ctk.CTkFont:
        key = (size, weight)
        if key not in cls._font_cache:
            cls._font_cache[key] = ctk.CTkFont(
                family=cls.get_family(),
                size=size,
                weight=weight
            )
        return cls._font_cache[key]


class AudioDenoiser:
    """
    Resilient RNNoise AI suppression adapter.
    Interfaces with pyrnnoise via direct C ctypes bindings or high-level class,
    and falls back cleanly to raw PCM to ensure audio never crashes.
    """
    def __init__(self, rate: int = 48000):
        self.rate = rate
        self._ctypes_state = None
        self._process_mono_frame = None
        self._rnnoise_instance = None

        # 1. Attempt direct C ctypes binding from pyrnnoise.rnnoise (most reliable)
        try:
            from pyrnnoise.rnnoise import create, process_mono_frame
            self._ctypes_state = create()
            self._process_mono_frame = process_mono_frame
        except Exception:
            self._ctypes_state = None

        # 2. Attempt high-level pyrnnoise.RNNoise wrapper as secondary
        try:
            from pyrnnoise import RNNoise
            try:
                self._rnnoise_instance = RNNoise(rate)
            except Exception:
                self._rnnoise_instance = RNNoise()
        except Exception:
            self._rnnoise_instance = None

    def filter(self, data: bytes) -> bytes:
        """Denoise 10ms frame (480 samples @ 48kHz = 960 bytes)."""
        if not data or len(data) != 960:
            return data

        # Priority 1: Direct C ctypes mono frame processing
        if self._ctypes_state is not None and self._process_mono_frame is not None:
            try:
                import numpy as np
                pcm = np.frombuffer(data, dtype=np.int16)
                if len(pcm) == 480:
                    clean_pcm, _ = self._process_mono_frame(self._ctypes_state, pcm)
                    return clean_pcm.tobytes()
            except Exception:
                pass

        # Priority 2: High-level class methods
        if self._rnnoise_instance is not None:
            try:
                if hasattr(self._rnnoise_instance, "filter"):
                    return self._rnnoise_instance.filter(data)
                elif hasattr(self._rnnoise_instance, "denoise_frame"):
                    import numpy as np
                    pcm = np.frombuffer(data, dtype=np.int16)
                    _, clean = self._rnnoise_instance.denoise_frame(pcm)
                    return clean.tobytes()
            except Exception:
                pass

        # Fallback: Untouched raw PCM
        return data


class AudioEngine:
    """
    Decoupled SFU Audio & Network Engine.
    Preserves UDP socket, 16-byte fixed username header, 960-byte PCM audio,
    3 daemon threads, per-user jitter buffers, and linear saturation mixing.
    """
    def __init__(
        self,
        on_user_list: Optional[Callable[[List[str]], None]] = None,
        on_error: Optional[Callable[[str, str], None]] = None,
        on_avatar_received: Optional[Callable[[str, bytes], None]] = None,
        on_screen_share_start: Optional[Callable[[str, str], None]] = None,
        on_screen_share_stop: Optional[Callable[[str], None]] = None,
        on_user_status_update: Optional[Callable[[str, bool, bool], None]] = None
    ):
        self.on_user_list = on_user_list
        self.on_error = on_error
        self.on_avatar_received = on_avatar_received
        self.on_screen_share_start = on_screen_share_start
        self.on_screen_share_stop = on_screen_share_stop
        self.on_user_status_update = on_user_status_update

        self.running = False
        self.connected = False
        self.sock: Optional[socket.socket] = None
        self.p: Optional[pyaudio.PyAudio] = None
        self.stream_in = None
        self.stream_out = None
        self.server_addr: Optional[Tuple[str, int]] = None
        self.username = ""
        self.is_host = False
        self.server_process: Optional[subprocess.Popen] = None

        self.mic_muted = False
        self.deafened = False

        self.user_buffers: Dict[str, queue.Queue] = {}
        self.user_volumes: Dict[str, float] = {}
        self.avatar_chunks_rx: Dict[str, Dict[int, str]] = {}
        self.avatar_expected_chunks: Dict[str, int] = {}
        self.denoiser = AudioDenoiser(RATE)

    def start(self, server_ip: str, server_port: int, username: str, is_host: bool = False) -> bool:
        self.username = username
        self.is_host = is_host
        self.server_addr = (server_ip, server_port)
        self.user_buffers.clear()

        # If hosting, launch background sfu_server.py
        if is_host:
            try:
                self.server_process = subprocess.Popen(
                    [sys.executable, "sfu_server.py", "--host", "0.0.0.0", "--port", str(server_port)],
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
                time.sleep(1.0)
            except Exception as e:
                if self.on_error:
                    self.on_error("Error de Host", f"No se pudo iniciar el servidor SFU: {e}")
                return False

        # Initialize UDP socket
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.settimeout(0.5)
        except Exception as e:
            if self.on_error:
                self.on_error("Error de Red", f"No se pudo inicializar socket UDP: {e}")
            return False

        # Initialize PyAudio
        if pyaudio is None:
            if self.on_error:
                self.on_error("Error de Audio", "PyAudio no está instalado.")
            return False

        try:
            self.p = pyaudio.PyAudio()
            self.stream_in = self.p.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                input=True,
                frames_per_buffer=CHUNK
            )
            self.stream_out = self.p.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=RATE,
                output=True,
                frames_per_buffer=CHUNK
            )
        except Exception as e:
            if self.on_error:
                self.on_error("Error de Audio", f"No se pudo acceder a micrófono/altavoces: {e}")
            self.stop()
            return False

        self.running = True
        self.connected = False
        self.mic_muted = False
        self.deafened = False

        # Spawn 3 worker daemon threads
        threading.Thread(target=self.receive_loop, daemon=True).start()
        threading.Thread(target=self.send_loop, daemon=True).start()
        threading.Thread(target=self.playback_loop, daemon=True).start()
        return True

    def send_avatar_image(self, filepath: str):
        if not self.sock or not self.server_addr or not Image:
            return
        
        # Iniciar hilo en segundo plano para no congelar la UI
        threading.Thread(target=self._process_and_send_avatar, args=(filepath,), daemon=True).start()

    def _process_and_send_avatar(self, filepath: str):
        try:
            # 1. Cargar y comprimir
            img = Image.open(filepath)
            img = img.convert("RGB")
            # Recortar a cuadrado
            width, height = img.size
            min_dim = min(width, height)
            left = (width - min_dim) / 2
            top = (height - min_dim) / 2
            img = img.crop((left, top, left + min_dim, top + min_dim))
            # Redimensionar a 64x64
            img = img.resize((64, 64), Image.Resampling.LANCZOS)
            
            # 2. Guardar a JPEG en memoria (alta compresión)
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=40)
            raw_bytes = buffer.getvalue()
            b64_data = base64.b64encode(raw_bytes).decode('utf-8')
            
            # Actualizar la interfaz local inmediatamente
            if self.on_avatar_received:
                self.on_avatar_received(self.username, raw_bytes)
            
            # 3. Fragmentar (500 bytes por chunk)
            chunk_size = 500
            chunks = [b64_data[i:i+chunk_size] for i in range(0, len(b64_data), chunk_size)]
            
            # 4. Enviar cíclicamente 3 veces (Redundancia)
            for _ in range(3):
                for idx, chunk in enumerate(chunks):
                    payload = {
                        "action": "avatar_chunk",
                        "username": self.username,
                        "chunk_id": idx,
                        "total_chunks": len(chunks),
                        "data": chunk
                    }
                    msg = json.dumps(payload).encode('utf-8')
                    self.sock.sendto(msg, self.server_addr)
                    time.sleep(0.02) # Pequeña pausa para no saturar UDP
        except Exception as e:
            print("Error enviando avatar:", e)

    def send_screen_share_start(self, stream_url: str):
        if self.sock and self.server_addr:
            msg = json.dumps({
                "action": "screen_share_start",
                "username": self.username,
                "stream_url": stream_url
            }).encode('utf-8')
            try:
                self.sock.sendto(msg, self.server_addr)
            except Exception:
                pass

    def send_screen_share_stop(self):
        if self.sock and self.server_addr:
            msg = json.dumps({
                "action": "screen_share_stop",
                "username": self.username
            }).encode('utf-8')
            try:
                self.sock.sendto(msg, self.server_addr)
            except Exception:
                pass

    def send_user_status(self, is_muted: bool, is_deafened: bool):
        if self.sock and self.server_addr:
            msg = json.dumps({
                "action": "user_status_update",
                "username": self.username,
                "is_muted": is_muted,
                "is_deafened": is_deafened
            }).encode('utf-8')
            try:
                self.sock.sendto(msg, self.server_addr)
            except Exception:
                pass

    def receive_loop(self):
        while self.running and self.sock:
            try:
                data, _ = self.sock.recvfrom(65535)

                # Control packet check: JSON (empieza con { y termina con })
                if len(data) >= 10 and data.startswith(b'{') and data.endswith(b'}'):
                    try:
                        text = data.decode('utf-8', errors='ignore').strip()
                        obj = json.loads(text)
                        if obj.get("action") == "room_state":
                            self.connected = True
                            users = obj.get("users", [])
                            if self.on_user_list:
                                self.on_user_list(users)
                            user_states = obj.get("user_states", {})
                            if self.on_user_status_update and isinstance(user_states, dict):
                                for u, st in user_states.items():
                                    if isinstance(st, dict):
                                        self.on_user_status_update(
                                            u,
                                            bool(st.get("is_muted", False)),
                                            bool(st.get("is_deafened", False))
                                        )
                            continue
                        elif obj.get("action") == "user_status_update":
                            sender = obj.get("username")
                            if sender and self.on_user_status_update:
                                is_muted = bool(obj.get("is_muted", False))
                                is_deafened = bool(obj.get("is_deafened", False))
                                self.on_user_status_update(sender, is_muted, is_deafened)
                            continue
                        elif obj.get("action") == "screen_share_start":
                            sender = obj.get("username")
                            stream_url = obj.get("stream_url")
                            if sender and stream_url and self.on_screen_share_start:
                                self.on_screen_share_start(sender, stream_url)
                            continue
                        elif obj.get("action") == "screen_share_stop":
                            sender = obj.get("username")
                            if sender and self.on_screen_share_stop:
                                self.on_screen_share_stop(sender)
                            continue
                        elif obj.get("action") == "avatar_chunk":
                            sender = obj.get("username")
                            chunk_id = obj.get("chunk_id")
                            total_chunks = obj.get("total_chunks")
                            data_chunk = obj.get("data")
                            
                            if sender and chunk_id is not None and data_chunk:
                                if sender not in self.avatar_chunks_rx:
                                    self.avatar_chunks_rx[sender] = {}
                                    self.avatar_expected_chunks[sender] = total_chunks
                                
                                if chunk_id not in self.avatar_chunks_rx[sender]:
                                    self.avatar_chunks_rx[sender][chunk_id] = data_chunk
                                    
                                    # Verificar si tenemos todos
                                    if len(self.avatar_chunks_rx[sender]) == self.avatar_expected_chunks[sender]:
                                        self._assemble_avatar(sender)
                            continue
                    except Exception:
                        pass

                # Audio packet check: length > 16 (16-byte username header + 960-byte PCM)
                if len(data) > 16:
                    if self.deafened:
                        continue  # Drop incoming packets when deafened

                    header = data[:16]
                    audio_payload = data[16:]
                    sender = header.decode('utf-8', errors='ignore').rstrip('\x00')

                    if sender not in self.user_buffers:
                        self.user_buffers[sender] = queue.Queue(maxsize=10)

                    try:
                        self.user_buffers[sender].put_nowait(audio_payload)
                    except queue.Full:
                        # Drop oldest frame to eliminate latency drift
                        try:
                            self.user_buffers[sender].get_nowait()
                        except Exception:
                            pass
                        try:
                            self.user_buffers[sender].put_nowait(audio_payload)
                        except Exception:
                            pass

            except socket.timeout:
                continue
            except ConnectionResetError:
                # Trapping WinError 10054 (WSAECONNRESET) on Windows
                continue
            except Exception as e:
                if self.running and self.on_error:
                    self.on_error("Error de Recepción", str(e))
                break

    def _assemble_avatar(self, sender: str):
        try:
            chunks_dict = self.avatar_chunks_rx[sender]
            expected = self.avatar_expected_chunks[sender]
            b64_data = "".join(chunks_dict[i] for i in range(expected))
            raw_bytes = base64.b64decode(b64_data)
            
            if self.on_avatar_received:
                self.on_avatar_received(sender, raw_bytes)
        except Exception as e:
            print(f"Error ensamblando avatar de {sender}:", e)

    def send_loop(self):
        last_connect = 0.0
        while self.running and self.sock and self.stream_in:
            try:
                # Periodic connect retry until room_state is received
                if not self.connected and time.time() - last_connect > 1.0:
                    msg = json.dumps({"action": "connect", "username": self.username}).encode('utf-8')
                    self.sock.sendto(msg, self.server_addr)
                    last_connect = time.time()

                # Always read hardware frame to prevent buffer overflow
                data = self.stream_in.read(CHUNK, exception_on_overflow=False)

                if not self.mic_muted:
                    clean_audio = self.denoiser.filter(data)
                    header = self.username.encode('utf-8').ljust(16, b'\x00')[:16]
                    self.sock.sendto(header + clean_audio, self.server_addr)

            except Exception as e:
                if self.running and self.on_error:
                    self.on_error("Error de Envío", str(e))
                break

    def playback_loop(self):
        target_size = CHUNK * 2  # 960 bytes

        while self.running and self.stream_out:
            mixed = None

            # Pull 1 packet from each active participant jitter buffer
            for user, q in list(self.user_buffers.items()):
                try:
                    packet = q.get_nowait()
                    if len(packet) == target_size:
                        vol = self.user_volumes.get(user, 1.0)
                        if mixed is None:
                            arr = array.array('h', packet)
                            if vol != 1.0:
                                for i in range(len(arr)): arr[i] = int(arr[i] * vol)
                            mixed = arr
                        else:
                            arr = array.array('h', packet)
                            for i in range(len(mixed)):
                                val = mixed[i] + int(arr[i] * vol)
                                if val > 32767:
                                    val = 32767
                                elif val < -32768:
                                    val = -32768
                                mixed[i] = val
                except Exception:
                    pass

            if mixed is not None:
                try:
                    self.stream_out.write(mixed.tobytes())
                except Exception:
                    pass
            else:
                time.sleep(0.01)

    def toggle_mute(self) -> Tuple[bool, bool]:
        """
        Toggles microphone mute state.
        Unmuting while deafened automatically un-deafens.
        Returns: (mic_muted, deafened)
        """
        self.mic_muted = not self.mic_muted
        if not self.mic_muted and self.deafened:
            self.deafened = False
        return self.mic_muted, self.deafened

    def toggle_deafen(self) -> Tuple[bool, bool]:
        """
        Toggles deafen state.
        Deafening automatically mutes microphone.
        Undeafening keeps microphone muted.
        Returns: (mic_muted, deafened)
        """
        self.deafened = not self.deafened
        if self.deafened and not self.mic_muted:
            self.mic_muted = True
        return self.mic_muted, self.deafened

    def stop(self):
        self.running = False
        if self.sock:
            try:
                msg = json.dumps({"action": "disconnect"}).encode('utf-8')
                self.sock.sendto(msg, self.server_addr)
                self.sock.close()
            except Exception:
                pass
            self.sock = None

        if self.stream_in:
            try:
                self.stream_in.stop_stream()
                self.stream_in.close()
            except Exception:
                pass
            self.stream_in = None

        if self.stream_out:
            try:
                self.stream_out.stop_stream()
                self.stream_out.close()
            except Exception:
                pass
            self.stream_out = None

        if self.p:
            try:
                self.p.terminate()
            except Exception:
                pass
            self.p = None

        if self.server_process:
            try:
                self.server_process.terminate()
            except Exception:
                pass
            self.server_process = None


class HardwareEncoderDetector:
    """
    Detector dinámico de aceleración por hardware de video (GPU).
    Detecta automáticamente si la máquina cuenta con NVIDIA NVENC para codificación
    por GPU a 0% de CPU, con fallback seguro a codificación universal por CPU (libx264).
    """
    _cached_encoder: Optional[Tuple[str, List[str]]] = None

    @classmethod
    def get_best_encoder(cls, ffmpeg_bin: str) -> Tuple[str, List[str]]:
        if cls._cached_encoder is not None:
            return cls._cached_encoder

        # 1. Probar NVIDIA NVENC (ultra baja latencia, 0% CPU, no afecta juegos)
        nvenc_flags = ["-preset", "p1", "-tune", "ull", "-zerolatency", "1"]
        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-loglevel", "error",
            "-f", "lavfi",
            "-i", "testsrc=size=320x240:rate=1",
            "-frames:v", "1",
            "-pix_fmt", "yuv420p",
            "-c:v", "h264_nvenc",
            *nvenc_flags,
            "-f", "null",
            "-"
        ]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags, timeout=1.5)
            if res.returncode == 0:
                cls._cached_encoder = ("h264_nvenc", nvenc_flags)
                return cls._cached_encoder
        except Exception:
            pass

        # 2. Fallback estándar garantizado: CPU libx264 ultrafast (compatible con 100% de PCs)
        cls._cached_encoder = (
            "libx264",
            ["-preset", "ultrafast", "-tune", "zerolatency", "-pix_fmt", "yuv420p", "-threads", "4"]
        )
        return cls._cached_encoder


class ScreenCaptureStreamer:
    """
    Subproceso FFmpeg para capturar y transmitir la pantalla en ultra baja latencia
    hacia el servidor MediaMTX vía RTSP sobre TCP.
    
    Arquitectura Robusta y Probada:
    - Nivel 1: GDI Grab (gdigrab) a 60 FPS en monitor primario.
      Usa NVIDIA NVENC por GPU si está disponible (0% CPU, 144Hz fluidos).
      Si la máquina no tiene NVIDIA o NVENC no inicializa, usa libx264 ultrafast.
    - Nivel 2: Tubería universal de fotogramas PIL inyectados por stdin a FFmpeg.
    - Watchdog: Supervisión activa del subproceso con auto-recuperación y reporte de error.
    """
    def __init__(self, on_stream_died: Optional[Callable[[str], None]] = None):
        self.process: Optional[subprocess.Popen] = None
        self.worker_thread: Optional[threading.Thread] = None
        self.watchdog_thread: Optional[threading.Thread] = None
        self.is_streaming = False
        self.last_error = ""
        self.on_stream_died = on_stream_died

    def start(self, host_ip: str, username: str) -> bool:
        if self.is_streaming:
            return True

        self.last_error = ""
        base_dir = os.path.dirname(os.path.abspath(__file__))
        ffmpeg_bin = os.path.join(base_dir, "bin", "ffmpeg.exe")
        if not os.path.exists(ffmpeg_bin):
            ffmpeg_bin = shutil.which("ffmpeg")

        if not ffmpeg_bin or not os.path.exists(ffmpeg_bin):
            self.last_error = (
                f"No se encontró 'ffmpeg.exe' en la carpeta:\n{os.path.join(base_dir, 'bin')}\n\n"
                "Por favor cierra la aplicación y ejecuta 'instalar_y_jugar.bat' "
                "para descargar las herramientas de video automáticamente."
            )
            return False

        rtsp_url = f"rtsp://{host_ip}:8554/live/{username}"

        # Obtener dimensiones nativas del monitor primario y virtual desktop
        screen_w = 1920
        screen_h = 1080
        virt_x = 0
        virt_y = 0
        try:
            import ctypes
            user32 = ctypes.windll.user32
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(2)
            except Exception:
                try:
                    user32.SetProcessDPIAware()
                except Exception:
                    pass

            screen_w = user32.GetSystemMetrics(0) # SM_CXSCREEN (ancho primario)
            screen_h = user32.GetSystemMetrics(1) # SM_CYSCREEN (alto primario)
            virt_x = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
            virt_y = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
        except Exception:
            pass

        codec, codec_flags = HardwareEncoderDetector.get_best_encoder(ffmpeg_bin)
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0

        # Lista de codificadores para probar (GPU primero, CPU después)
        encoder_combos = [(codec, codec_flags)]
        if codec != "libx264":
            encoder_combos.append((
                "libx264",
                ["-preset", "ultrafast", "-tune", "zerolatency", "-pix_fmt", "yuv420p", "-threads", "4"]
            ))

        # Construir lista de candidatos ordenada de mejor a fallback:
        # 1. Desktop Duplication API (ddagrab) en monitor principal (output 0)
        #    -> Captura por GPU Direct3D 11, 0% CPU, no afecta monitores 144Hz, captura juegos DirectX/Vulkan sin pantalla negra.
        # 2. Desktop Duplication API (ddagrab) en output_idx=1 por si el monitor principal está en índice 1.
        # 3. GDI Grab (gdigrab) con resolución nativa.
        # 4. GDI Grab universal.
        candidates = []
        gop_flags = ["-g", "30", "-keyint_min", "30", "-forced-idr", "1"]
        bitrate_flags = ["-b:v", "3500k", "-maxrate", "4000k", "-bufsize", "2000k"]

        # 1. ddagrab output 0
        for enc_name, enc_flags in encoder_combos:
            vf_args = ["-vf", "hwdownload,format=nv12"] if enc_name == "libx264" else []
            candidates.append((
                f"DirectX Desktop Duplication (ddagrab 0, {enc_name})",
                [
                    ffmpeg_bin,
                    "-hide_banner",
                    "-loglevel", "error",
                    "-f", "lavfi",
                    "-i", "ddagrab=framerate=60:draw_mouse=1",
                    *vf_args,
                    "-c:v", enc_name,
                    *enc_flags,
                    *gop_flags,
                    *bitrate_flags,
                    "-f", "rtsp",
                    "-rtsp_transport", "tcp",
                    rtsp_url
                ]
            ))

        # 2. ddagrab output 1
        for enc_name, enc_flags in encoder_combos:
            vf_args = ["-vf", "hwdownload,format=nv12"] if enc_name == "libx264" else []
            candidates.append((
                f"DirectX Desktop Duplication (ddagrab 1, {enc_name})",
                [
                    ffmpeg_bin,
                    "-hide_banner",
                    "-loglevel", "error",
                    "-f", "lavfi",
                    "-i", "ddagrab=output_idx=1:framerate=60:draw_mouse=1",
                    *vf_args,
                    "-c:v", enc_name,
                    *enc_flags,
                    *gop_flags,
                    *bitrate_flags,
                    "-f", "rtsp",
                    "-rtsp_transport", "tcp",
                    rtsp_url
                ]
            ))

        # 3. GDI Grab con dimensiones de monitor
        gdi_size_args = []
        if virt_x == 0 and virt_y == 0:
            gdi_size_args = ["-offset_x", "0", "-offset_y", "0", "-video_size", f"{screen_w}x{screen_h}"]

        for enc_name, enc_flags in encoder_combos:
            candidates.append((
                f"GDI Grab ({enc_name})",
                [
                    ffmpeg_bin,
                    "-hide_banner",
                    "-loglevel", "error",
                    "-f", "gdigrab",
                    "-framerate", "60",
                    *gdi_size_args,
                    "-i", "desktop",
                    "-vf", "scale=min(1920\\,iw):-2,format=yuv420p",
                    "-c:v", enc_name,
                    *enc_flags,
                    *gop_flags,
                    *bitrate_flags,
                    "-f", "rtsp",
                    "-rtsp_transport", "tcp",
                    rtsp_url
                ]
            ))

        # 4. GDI Grab universal sin parámetros de tamaño
        for enc_name, enc_flags in encoder_combos:
            candidates.append((
                f"GDI Grab Universal ({enc_name})",
                [
                    ffmpeg_bin,
                    "-hide_banner",
                    "-loglevel", "error",
                    "-f", "gdigrab",
                    "-framerate", "60",
                    "-i", "desktop",
                    "-vf", "scale=min(1920\\,iw):-2,format=yuv420p",
                    "-c:v", enc_name,
                    *enc_flags,
                    *gop_flags,
                    *bitrate_flags,
                    "-f", "rtsp",
                    "-rtsp_transport", "tcp",
                    rtsp_url
                ]
            ))

        # Probar candidatos en orden
        for desc, cmd in candidates:
            try:
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    creationflags=creationflags
                )

                time.sleep(0.7)
                if self.process.poll() is None:
                    self.is_streaming = True
                    self._start_watchdog()
                    print(f"[OK] Transmisión iniciada exitosamente con {desc}.")
                    return True
                else:
                    _, err = self.process.communicate(timeout=0.4)
                    err_text = err.decode('utf-8', errors='ignore') if err else ""
                    print(f"[x] {desc} no disponible ({err_text.strip()[:140]}).")
            except Exception as exc:
                print(f"Excepción probando {desc}:", exc)

        # Intento de último recurso: Fallback Universal por Tubería PIL -> stdin FFmpeg (protegido contra saturación de CPU)
        try:
            cap_w, cap_h = 1280, 720
            cmd_pipe = [
                ffmpeg_bin,
                "-hide_banner",
                "-loglevel", "error",
                "-f", "rawvideo",
                "-pix_fmt", "rgb24",
                "-s", f"{cap_w}x{cap_h}",
                "-r", "25",
                "-i", "-",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-tune", "zerolatency",
                "-pix_fmt", "yuv420p",
                "-threads", "4",
                "-b:v", "2000k",
                "-maxrate", "2500k",
                "-bufsize", "1000k",
                "-f", "rtsp",
                "-rtsp_transport", "tcp",
                rtsp_url
            ]
            self.process = subprocess.Popen(
                cmd_pipe,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=creationflags
            )
            time.sleep(0.5)
            if self.process.poll() is not None:
                _, err = self.process.communicate(timeout=0.5)
                err_str = err.decode('utf-8', errors='ignore') if err else "Error desconocido"
                self.last_error = f"Error al conectar con el servidor de video MediaMTX:\n{err_str}"
                return False

            self.is_streaming = True
            self.worker_thread = threading.Thread(
                target=self._pil_stream_loop,
                args=(cap_w, cap_h),
                daemon=True,
                name=f"PIL-Capture-{username}"
            )
            self.worker_thread.start()
            self._start_watchdog()
            print("[OK] Transmisión iniciada con fallback universal PIL.")
            return True
        except Exception as e:
            self.last_error = f"Error al ejecutar FFmpeg: {e}"
            print("Error en fallback universal de captura:", e)
            return False

    def _start_watchdog(self):
        self.watchdog_thread = threading.Thread(
            target=self._watchdog_loop,
            daemon=True,
            name="StreamWatchdog"
        )
        self.watchdog_thread.start()

    def _watchdog_loop(self):
        while self.is_streaming:
            if self.process and self.process.poll() is not None:
                self.is_streaming = False
                err = ""
                try:
                    if self.process.stderr:
                        err = self.process.stderr.read().decode('utf-8', errors='ignore')
                except Exception:
                    pass
                print(f"[!] Proceso FFmpeg de transmisión terminado. {err.strip()}")
                if self.on_stream_died:
                    try:
                        self.on_stream_died(err.strip())
                    except Exception:
                        pass
                break
            time.sleep(0.5)

    def _pil_stream_loop(self, w: int, h: int):
        try:
            from PIL import ImageGrab
            interval = 1.0 / 25.0
            error_count = 0
            while self.is_streaming and self.process and self.process.poll() is None:
                t0 = time.time()
                try:
                    frame = ImageGrab.grab(all_screens=True)
                    if frame.size != (w, h):
                        frame = frame.resize((w, h))
                    raw_bytes = frame.tobytes()
                    if self.process and self.process.stdin:
                        self.process.stdin.write(raw_bytes)
                        self.process.stdin.flush()
                    error_count = 0
                except Exception as ex:
                    error_count += 1
                    if error_count > 15:
                        print(f"[!] Falla continua en captura PIL: {ex}")
                        if self.on_stream_died:
                            self.on_stream_died("No se pudo capturar la pantalla (permisos de escritorio de Windows).")
                        break
                    time.sleep(0.04)

                to_sleep = interval - (time.time() - t0)
                if to_sleep > 0:
                    time.sleep(to_sleep)
                else:
                    time.sleep(0.003) # Prevenir bloqueo y saturación de CPU
        except Exception as exc:
            print("Excepción en loop PIL:", exc)

    def stop(self):
        self.is_streaming = False
        if self.worker_thread and self.worker_thread.is_alive():
            try:
                self.worker_thread.join(timeout=0.5)
            except Exception:
                pass
            self.worker_thread = None

        if self.process:
            try:
                if self.process.stdin:
                    try:
                        self.process.stdin.close()
                    except Exception:
                        pass
                self.process.terminate()
                self.process.wait(timeout=0.5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None


class ScreenShareViewer:
    """
    Subproceso MPV incrustado directamente en una ventana/frame de Tkinter
    usando el identificador nativo de ventana de Windows (--wid=<HWND>).
    """
    def __init__(self, target_frame: tk.Frame, stream_url: str):
        self.target_frame = target_frame
        self.stream_url = stream_url
        self.process: Optional[subprocess.Popen] = None

    def start(self):
        self.target_frame.update_idletasks()
        hwnd = self.target_frame.winfo_id()

        base_dir = os.path.dirname(os.path.abspath(__file__))
        mpv_bin = os.path.join(base_dir, "bin", "mpv.exe")
        if not os.path.exists(mpv_bin):
            mpv_bin = shutil.which("mpv") or "mpv"

        cmd = [
            mpv_bin,
            f"--wid={hwnd}",
            "--no-border",
            "--profile=low-latency",
            "--untimed",
            "--no-cache",
            "--hwdec=auto-safe",
            "--osc=no",
            "--osd-level=0",
            "--demuxer-lavf-o=rtsp_transport=tcp",
            "--rtsp-transport=tcp",
            self.stream_url
        ]

        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags
            )
        except Exception as e:
            print("Error iniciando visor MPV:", e)

    def stop(self):
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=0.5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            self.process = None


class GridCalculator:
    """
    Pure mathematical aspect-ratio layout optimizer for Zoom-style video grid.
    Computes optimal columns/rows, centers uneven trailing rows, and centers the grid vertically.
    Complexity: O(N) where N is participant count.
    """
    @staticmethod
    def compute_layout(
        n: int,
        container_w: int,
        container_h: int,
        target_aspect: float = 1.35,
        gap: int = 12,
        pad: int = 16,
        min_w: int = 140,
        min_h: int = 105,
        max_w: int = 480,
        max_h: int = 360
    ) -> Tuple[int, int, int, int, List[Tuple[int, int, int, int]]]:
        if n <= 0:
            return 0, 0, 0, 0, []

        avail_w = max(min_w, container_w - 2 * pad)
        avail_h = max(min_h, container_h - 2 * pad)
        best = None

        for c in range(1, n + 1):
            r = math.ceil(n / c)
            w_space = avail_w - (c - 1) * gap
            h_space = avail_h - (r - 1) * gap
            if w_space <= 0 or h_space <= 0:
                continue

            max_tw = w_space / c
            max_th = h_space / r

            tw = min(max_tw, max_th * target_aspect)
            tw = min(tw, max_w)
            th = tw / target_aspect
            if th > max_h:
                th = max_h
                tw = th * target_aspect

            tw = max(tw, min_w)
            th = max(th, min_h)

            area = tw * th
            score = area - abs(c - r) * 0.1
            if best is None or score > best[0]:
                best = (score, c, r, int(tw), int(th))

        if best is None:
            cols, rows, tw, th = 1, n, min_w, min_h
        else:
            _, cols, rows, tw, th = best

        total_grid_h = rows * th + (rows - 1) * gap
        y_start = pad + max(0, (avail_h - total_grid_h) // 2)

        positions = []
        for idx in range(n):
            row_idx = idx // cols
            col_idx = idx % cols

            if row_idx == rows - 1:
                items_in_row = n - (rows - 1) * cols
            else:
                items_in_row = cols

            row_w = items_in_row * tw + (items_in_row - 1) * gap
            x_start = pad + max(0, (avail_w - row_w) // 2)

            x = int(x_start + col_idx * (tw + gap))
            y = int(y_start + row_idx * (th + gap))
            positions.append((x, y, tw, th))

        return cols, rows, tw, th, positions


class DoubleBezelContainer(ctk.CTkFrame):
    """
    Awwwards-tier Double-Bezel (Doppelrand) card container.
    Outer shell (#111111, 1px #1F1F1F, R_outer=16) enclosing
    Inner core (#161616, 1px #262626, R_inner=12) with concentric geometry.
    """
    def __init__(self, master, outer_radius: int = 16, padding: int = 4, **kwargs):
        super().__init__(
            master,
            corner_radius=outer_radius,
            fg_color=SHELL_BG,
            border_color=SHELL_BORDER,
            border_width=1,
            **kwargs
        )
        self.inner_radius = max(0, outer_radius - padding)
        self.core = ctk.CTkFrame(
            self,
            corner_radius=self.inner_radius,
            fg_color=CORE_BG,
            border_color=CORE_BORDER,
            border_width=1
        )
        self.core.pack(padx=padding, pady=padding, fill="both", expand=True)


class ParticipantTile(ctk.CTkFrame):
    """
    Individual participant tile featuring:
    - Squircle outer card with idle / speaking border
    - Squircle / circular photo monogram placeholder showing user initials
    - Centered username label with (Tú) local indicator
    - Dynamic proportional scaling on window reflow
    """
    def __init__(self, master, username: str, is_local: bool = False, **kwargs):
        super().__init__(
            master,
            corner_radius=14,
            fg_color=TILE_BG_IDLE,
            border_color=TILE_BORDER_IDLE,
            border_width=1,
            **kwargs
        )
        self.pack_propagate(False)
        self.username = username
        self.is_local = is_local
        self.is_speaking = False

        # Photo placeholder (monogram squircle)
        self.avatar_size = 64
        self.placeholder_frame = ctk.CTkFrame(
            self,
            width=self.avatar_size,
            height=self.avatar_size,
            corner_radius=self.avatar_size // 2,
            fg_color=AVATAR_BG,
            border_color=AVATAR_BORDER,
            border_width=1
        )
        self.placeholder_frame.pack_propagate(False)
        self.placeholder_frame.pack(expand=True, pady=(12, 4))

        # Avatar initials label
        initials = self._extract_initials(username)
        self.lbl_initials = ctk.CTkLabel(
            self.placeholder_frame,
            text=initials,
            font=FontManager.get(18, "bold"),
            text_color=TEXT_PRIMARY
        )
        self.lbl_initials.pack(expand=True)

        # Centered username label
        display_name = f"{username} (Tú)" if is_local else username
        if len(display_name) > 22:
            display_name = display_name[:19] + "..."

        self.name_label = ctk.CTkLabel(
            self,
            text=display_name,
            font=FontManager.get(13, "bold"),
            text_color=TEXT_PRIMARY
        )
        self.name_label.pack(side="bottom", pady=(0, 12))
        
        self.avatar_image_ref = None
        self.lbl_image = None

        # Estado de audio (silenciado / ensordecido)
        self.is_muted = False
        self.is_deafened = False

        # Insignia de estado en la esquina inferior derecha (estilo Discord)
        self.status_badge_frame = ctk.CTkFrame(
            self,
            fg_color="#DA373C",
            corner_radius=6,
            border_width=0
        )
        self.lbl_status_icon = ctk.CTkLabel(
            self.status_badge_frame,
            text="",
            font=FontManager.get(10, "bold"),
            text_color="#FFFFFF"
        )
        self.lbl_status_icon.pack(padx=5, pady=2)
        
        # Vincular clic derecho para volumen
        self.bind("<Button-3>", self._on_right_click)
        self.placeholder_frame.bind("<Button-3>", self._on_right_click)
        self.lbl_initials.bind("<Button-3>", self._on_right_click)
        self.name_label.bind("<Button-3>", self._on_right_click)

    def set_status(self, is_muted: bool, is_deafened: bool):
        self.is_muted = is_muted
        self.is_deafened = is_deafened
        self._update_status_badge()

    def _update_status_badge(self):
        if self.is_deafened:
            self.lbl_status_icon.configure(text="🎧 ✕")
            self.status_badge_frame.configure(fg_color="#DA373C")
            self.status_badge_frame.place(relx=1.0, rely=1.0, x=-8, y=-8, anchor="se")
        elif self.is_muted:
            self.lbl_status_icon.configure(text="🎙 ✕")
            self.status_badge_frame.configure(fg_color="#DA373C")
            self.status_badge_frame.place(relx=1.0, rely=1.0, x=-8, y=-8, anchor="se")
        else:
            self.status_badge_frame.place_forget()

    def _on_right_click(self, event):
        if self.is_local: return # No cambiar volumen propio
        app = self.winfo_toplevel()
        if hasattr(app, "app_instance"):
            app.app_instance.on_tile_right_click(self.username, event.x_root, event.y_root)

    def set_avatar_image(self, raw_bytes: bytes):
        if not Image: return
        try:
            img = Image.open(io.BytesIO(raw_bytes))
            self.avatar_image_ref = ctk.CTkImage(light_image=img, dark_image=img, size=(self.avatar_size, self.avatar_size))
            
            if self.lbl_image is None:
                self.lbl_initials.pack_forget()
                self.lbl_image = ctk.CTkLabel(self.placeholder_frame, text="", image=self.avatar_image_ref)
                self.lbl_image.pack(expand=True, fill="both")
                self.lbl_image.bind("<Button-3>", self._on_right_click)
            else:
                self.lbl_image.configure(image=self.avatar_image_ref)
        except Exception as e:
            print("Error cargando avatar en UI:", e)

    @staticmethod
    def _extract_initials(name: str) -> str:
        clean = name.replace("(Tú)", "").strip()
        parts = clean.split()
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[0][0] + parts[1][0]).upper()

    def set_speaking(self, speaking: bool):
        if self.is_speaking == speaking:
            return
        self.is_speaking = speaking
        if speaking:
            self.configure(border_color=TILE_BORDER_SPEAK, border_width=2)
            self.placeholder_frame.configure(border_color=TILE_BORDER_SPEAK, border_width=2)
        else:
            self.configure(border_color=TILE_BORDER_IDLE, border_width=1)
            self.placeholder_frame.configure(border_color=AVATAR_BORDER, border_width=1)

    def update_geometry_scale(self, tile_w: int, tile_h: int):
        new_avatar_size = max(40, min(80, int(tile_h * 0.38)))
        if abs(new_avatar_size - self.avatar_size) >= 4:
            self.avatar_size = new_avatar_size
            self.placeholder_frame.configure(
                width=new_avatar_size,
                height=new_avatar_size,
                corner_radius=new_avatar_size // 2
            )
            font_size = max(11, int(new_avatar_size * 0.38))
            self.lbl_initials.configure(font=FontManager.get(font_size, "bold"))
            
            if self.avatar_image_ref and self.lbl_image:
                self.avatar_image_ref.configure(size=(new_avatar_size, new_avatar_size))


class ZoomUserGrid(ctk.CTkFrame):
    """
    Dynamic Zoom-style user grid container.
    Employs GridCalculator for aspect-ratio placement and debounced reflow on window resize.
    """
    def __init__(self, master, **kwargs):
        super().__init__(
            master,
            corner_radius=12,
            fg_color=CORE_BG,
            border_color=CORE_BORDER,
            border_width=1,
            **kwargs
        )
        self.user_tiles: Dict[str, ParticipantTile] = {}
        self.user_states: Dict[str, Tuple[bool, bool]] = {}
        self.users: List[str] = []
        self.local_username = ""
        self.grid_cols = 1
        self.grid_rows = 1

        self._debounce_timer = None
        self._last_dims = (0, 0)

        # Empty state label
        self.lbl_empty = ctk.CTkLabel(
            self,
            text="Esperando a otros participantes...",
            font=FontManager.get(14, "normal"),
            text_color=TEXT_SECONDARY
        )

        self.bind("<Configure>", self._on_configure)

    def set_user_status(self, username: str, is_muted: bool, is_deafened: bool):
        self.user_states[username] = (is_muted, is_deafened)
        if username in self.user_tiles:
            self.user_tiles[username].set_status(is_muted, is_deafened)

    def set_users(self, users: List[str], local_username: str = ""):
        self.users = list(users)
        self.local_username = local_username

        # Remove departed tiles
        current_set = set(self.users)
        for u in list(self.user_tiles.keys()):
            if u not in current_set:
                self.user_tiles[u].destroy()
                del self.user_tiles[u]

        # Add new participant tiles
        for u in self.users:
            if u not in self.user_tiles:
                is_local = (u == self.local_username)
                tile = ParticipantTile(self, username=u, is_local=is_local)
                if u in self.user_states:
                    m, d = self.user_states[u]
                    tile.set_status(m, d)
                self.user_tiles[u] = tile

        if not self.users:
            self.lbl_empty.place(relx=0.5, rely=0.5, anchor="center")
        else:
            self.lbl_empty.place_forget()

        self.reflow_now()

    def _on_configure(self, event):
        if event.widget not in (self, getattr(self, "_canvas", None)):
            return
        if (event.width, event.height) == self._last_dims:
            return
        self._last_dims = (event.width, event.height)

        # Immediate reflow on geometry change
        self.reflow_now(event.width, event.height)

        if self._debounce_timer is not None:
            self.after_cancel(self._debounce_timer)
        self._debounce_timer = self.after(50, self._on_debounce_fired)

    def _on_debounce_fired(self):
        self._debounce_timer = None
        self.reflow_now()

    def reflow_now(self, w: Optional[int] = None, h: Optional[int] = None):
        if w is None or h is None:
            w = self.winfo_width()
            h = self.winfo_height()

        if w <= 50 or h <= 50:
            try:
                self.update_idletasks()
                w = self.winfo_width()
                h = self.winfo_height()
            except Exception:
                pass

        if w <= 50 or h <= 50:
            try:
                # Estimate available space from parent widget / master
                pw = self.master.winfo_width()
                ph = self.master.winfo_height()
                w = max(300, pw - 8) if pw > 50 else 860
                h = max(300, ph - 8) if ph > 50 else 480
            except Exception:
                w = 860
                h = 480

        n = len(self.users)
        if n == 0:
            return

        cols, rows, tw, th, positions = GridCalculator.compute_layout(n, w, h)
        self.grid_cols = cols
        self.grid_rows = rows

        for idx, u in enumerate(self.users):
            if u in self.user_tiles and idx < len(positions):
                x, y, pw, ph = positions[idx]
                tile = self.user_tiles[u]
                tile.configure(width=pw, height=ph)
                tile.update_geometry_scale(pw, ph)
                tile.place(x=x, y=y)


class VoiceClientApp:
    """
    Main CustomTkinter Voice Client Application.
    Implements High-End Minimalist Monochrome UI (Doppelrand, Maven typography,
    floating pill control island, dynamic Zoom-style grid).
    """
    def __init__(self, root: Optional[ctk.CTk] = None):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("dark-blue")

        if root is None:
            self.root = ctk.CTk()
            self._owns_root = True
        else:
            self.root = root
            self._owns_root = False

        self.root.title("Concordia")
        self.root.geometry("900x650")
        self.root.minsize(480, 400)
        self.root.configure(fg_color=BG_ROOT)
        self.root.app_instance = self

        # Audio Engine backend
        self.engine = AudioEngine(
            on_user_list=self._on_user_list_threadsafe,
            on_error=self._on_engine_error_threadsafe,
            on_avatar_received=self._on_avatar_received_threadsafe,
            on_screen_share_start=self._on_screen_share_start_threadsafe,
            on_screen_share_stop=self._on_screen_share_stop_threadsafe,
            on_user_status_update=self._on_user_status_update_threadsafe
        )

        # UI state variables
        self.username = ""
        self.is_host = False
        self.server_addr = ("127.0.0.1", 5000)
        self.mic_muted = False
        self.deafened = False
        self.selected_avatar_path = None
        self.volume_popup = None
        
        # Screen sharing state
        self.streamer = ScreenCaptureStreamer(on_stream_died=self._on_stream_died_threadsafe)
        self.is_sharing_screen = False
        self.active_screen_sharer: Optional[str] = None
        self.screen_viewer: Optional[ScreenShareViewer] = None

        # Stage view widgets
        self.main_content_shell: Optional[ctk.CTkFrame] = None
        self.stage_shell: Optional[ctk.CTkFrame] = None
        self.video_viewport: Optional[tk.Frame] = None
        self.lbl_stage_title: Optional[ctk.CTkLabel] = None
        self.btn_screen_share: Optional[ctk.CTkButton] = None
        
        # Caché local para evitar perder fotos si llegan antes que se cree la tarjeta
        self.avatar_bytes_cache: Dict[str, bytes] = {}

        # Autologin loading
        self.config_path = os.path.join(os.path.dirname(__file__), ".concordia_profile.json")
        self.last_ip = ""
        self._load_config()

        # Widgets and Grid
        self.grid_container: Optional[ZoomUserGrid] = None
        self._user_tiles: Dict[str, ParticipantTile] = {}
        self._grid_cols = 1

        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.bind("<Configure>", self._on_root_configure)
        self.setup_login_ui()

    def _on_root_configure(self, event):
        if event.widget == self.root and self.grid_container is not None:
            self.grid_container.reflow_now()

    @property
    def grid_cols(self) -> int:
        if self.grid_container is not None:
            return self.grid_container.grid_cols
        return self._grid_cols

    @grid_cols.setter
    def grid_cols(self, val: int):
        self._grid_cols = val
        if self.grid_container is not None:
            self.grid_container.grid_cols = val

    @property
    def user_tiles(self) -> Dict[str, ParticipantTile]:
        if self.grid_container is not None:
            return self.grid_container.user_tiles
        return self._user_tiles

    @user_tiles.setter
    def user_tiles(self, val: Dict[str, ParticipantTile]):
        self._user_tiles = val
        if self.grid_container is not None:
            self.grid_container.user_tiles = val

    def _load_config(self):
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.username = data.get("username", "")
                    self.selected_avatar_path = data.get("avatar_path", None)
                    self.last_ip = data.get("last_ip", "")
            except Exception:
                pass

    def _save_config(self):
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump({
                    "username": self.username,
                    "avatar_path": self.selected_avatar_path,
                    "last_ip": self.last_ip
                }, f)
        except Exception:
            pass

    def clear_window(self):
        if self.screen_viewer:
            self.screen_viewer.stop()
            self.screen_viewer = None
        if self.is_sharing_screen:
            self.streamer.stop()
            self.is_sharing_screen = False

        self.active_screen_sharer = None
        self.stage_shell = None
        self.video_viewport = None
        self.lbl_stage_title = None
        self.btn_screen_share = None

        for widget in self.root.winfo_children():
            widget.destroy()
        self.grid_container = None
        self._user_tiles.clear()

    def _on_stream_died_threadsafe(self, err_msg: str):
        try:
            self.root.after(0, lambda: self._handle_stream_died(err_msg))
        except Exception:
            pass

    def _handle_stream_died(self, err_msg: str):
        if self.is_sharing_screen:
            self.is_sharing_screen = False
            self.engine.send_screen_share_stop()
            self._update_controls_visual_state()
            if self.active_screen_sharer == self.username:
                self._hide_stage_view()
            if err_msg:
                messagebox.showwarning("Transmisión Detenida", f"La captura de pantalla se detuvo:\n{err_msg}")

    # ==================== LOGIN VIEW ====================
    def _select_avatar(self):
        filepath = filedialog.askopenfilename(
            title="Seleccionar foto de perfil",
            filetypes=(("Archivos de imagen", "*.jpg *.jpeg *.png"), ("Todos", "*.*"))
        )
        if filepath:
            self.selected_avatar_path = filepath
            self.btn_avatar.configure(text="✅ Foto Cargada", fg_color="#22C55E")

    def setup_login_ui(self):
        self.clear_window()

        outer_wrapper = ctk.CTkFrame(self.root, fg_color=BG_ROOT)
        outer_wrapper.pack(expand=True, fill="both")

        # Double-Bezel Container
        card = DoubleBezelContainer(outer_wrapper, outer_radius=18, padding=4, width=460, height=480)
        card.place(relx=0.5, rely=0.5, anchor="center")

        content = card.core

        # Header Typography & Subtitle
        eyebrow = ctk.CTkLabel(
            content,
            text="CONCORDIA • SFU AUDIO",
            font=FontManager.get(10, "bold"),
            text_color=TEXT_SECONDARY
        )
        eyebrow.pack(anchor="w", padx=32, pady=(32, 4))

        title = ctk.CTkLabel(
            content,
            text="Sala de Voz Minimalista",
            font=FontManager.get(22, "bold"),
            text_color=TEXT_PRIMARY
        )
        title.pack(anchor="w", padx=32, pady=(0, 20))

        # Avatar Selector Button
        self.btn_avatar = ctk.CTkButton(
            content,
            text="📷 Seleccionar Foto de Perfil",
            font=FontManager.get(11, "bold"),
            height=32,
            fg_color="#1F1F22",
            hover_color="#2A2A2E",
            command=self._select_avatar
        )
        self.btn_avatar.pack(anchor="w", padx=32, pady=(0, 16))
        if self.selected_avatar_path:
            self.btn_avatar.configure(text="✅ Foto Cargada", fg_color="#22C55E")

        # Form: Username
        lbl_user = ctk.CTkLabel(content, text="NOMBRE DE USUARIO", font=FontManager.get(10, "bold"), text_color=TEXT_SECONDARY)
        lbl_user.pack(anchor="w", padx=32, pady=(0, 4))
        self.entry_username = ctk.CTkEntry(
            content,
            height=40,
            corner_radius=10,
            fg_color="#121212",
            border_color=CORE_BORDER,
            text_color=TEXT_PRIMARY,
            placeholder_text="Tu alias o nombre..."
        )
        if self.username:
            self.entry_username.insert(0, self.username)
        self.entry_username.pack(fill="x", padx=32, pady=(0, 14))

        # Form: IP
        lbl_ip = ctk.CTkLabel(content, text="IP DEL SERVIDOR (VACÍO SI ERES HOST)", font=FontManager.get(10, "bold"), text_color=TEXT_SECONDARY)
        lbl_ip.pack(anchor="w", padx=32, pady=(0, 4))
        self.entry_ip = ctk.CTkEntry(
            content,
            height=40,
            corner_radius=10,
            fg_color="#121212",
            border_color=CORE_BORDER,
            text_color=TEXT_PRIMARY,
            placeholder_text="127.0.0.1"
        )
        if self.last_ip:
            self.entry_ip.insert(0, self.last_ip)
        self.entry_ip.pack(fill="x", padx=32, pady=(0, 14))

        # Form: Port
        lbl_port = ctk.CTkLabel(content, text="PUERTO UDP", font=FontManager.get(10, "bold"), text_color=TEXT_SECONDARY)
        lbl_port.pack(anchor="w", padx=32, pady=(0, 4))
        self.entry_port = ctk.CTkEntry(
            content,
            height=40,
            corner_radius=10,
            fg_color="#121212",
            border_color=CORE_BORDER,
            text_color=TEXT_PRIMARY
        )
        self.entry_port.insert(0, "5000")
        self.entry_port.pack(fill="x", padx=32, pady=(0, 24))

        # Action Buttons (Host vs Conectar)
        btn_box = ctk.CTkFrame(content, fg_color="transparent")
        btn_box.pack(fill="x", padx=32, pady=(0, 32))

        self.btn_host = ctk.CTkButton(
            btn_box,
            text="Crear Sala (Host)",
            font=FontManager.get(12, "bold"),
            height=42,
            corner_radius=21,
            fg_color="#1F1F22",
            hover_color="#2A2A2E",
            border_color="#333338",
            border_width=1,
            text_color=TEXT_PRIMARY,
            command=self.start_host
        )
        self.btn_host.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.btn_connect = ctk.CTkButton(
            btn_box,
            text="Conectar",
            font=FontManager.get(12, "bold"),
            height=42,
            corner_radius=21,
            fg_color="#FFFFFF",
            hover_color="#E5E5E5",
            text_color="#080808",
            command=self.start_client
        )
        self.btn_connect.pack(side="right", expand=True, fill="x", padx=(6, 0))

    # ==================== ROOM VIEW ====================
    def setup_room_ui(self):
        self.clear_window()

        # Top Header Bar (Double-Bezel)
        header_shell = ctk.CTkFrame(
            self.root,
            corner_radius=14,
            fg_color=SHELL_BG,
            border_color=SHELL_BORDER,
            border_width=1,
            height=54
        )
        header_shell.pack(fill="x", padx=16, pady=(14, 8))
        header_shell.pack_propagate(False)

        role = "HOST" if self.is_host else "CLIENTE"
        addr_text = f"{self.server_addr[0]}:{self.server_addr[1]}" if self.server_addr else "127.0.0.1:5000"

        # Room Eyebrow / Role Tag
        self.lbl_title = ctk.CTkLabel(
            header_shell,
            text=f"SALA DE VOZ • {role}",
            font=FontManager.get(12, "bold"),
            text_color=TEXT_PRIMARY
        )
        self.lbl_title.pack(side="left", padx=(18, 8))

        # Status & Server Info
        self.lbl_status = ctk.CTkLabel(
            header_shell,
            text=f"Servidor: {addr_text}  |  Usuario: {self.username}",
            font=FontManager.get(11, "normal"),
            text_color=TEXT_SECONDARY
        )
        self.lbl_status.pack(side="left", padx=8)

        # Online Status Pill Badge
        online_badge = ctk.CTkLabel(
            header_shell,
            text="● EN LÍNEA",
            font=FontManager.get(10, "bold"),
            text_color="#22C55E"
        )
        online_badge.pack(side="right", padx=(8, 18))

        # Center: Main Content Area (Holds Screen Share Stage and Zoom Grid)
        self.main_content_shell = ctk.CTkFrame(self.root, fg_color="transparent")
        self.main_content_shell.pack(fill="both", expand=True, padx=16, pady=6)

        # Stage Shell (Hidden initially, shown when someone shares screen)
        self.stage_shell = ctk.CTkFrame(
            self.main_content_shell,
            corner_radius=16,
            fg_color=SHELL_BG,
            border_color=SHELL_BORDER,
            border_width=1
        )

        stage_top_bar = ctk.CTkFrame(self.stage_shell, height=36, fg_color="transparent")
        stage_top_bar.pack(fill="x", padx=12, pady=(8, 4))
        stage_top_bar.pack_propagate(False)

        self.lbl_stage_title = ctk.CTkLabel(
            stage_top_bar,
            text="🖥  TRANSMISIÓN EN VIVO",
            font=FontManager.get(11, "bold"),
            text_color=TEXT_PRIMARY
        )
        self.lbl_stage_title.pack(side="left", padx=4)

        btn_hide_stage = ctk.CTkButton(
            stage_top_bar,
            text="✕ Ocultar",
            font=FontManager.get(11, "bold"),
            width=70,
            height=24,
            corner_radius=12,
            fg_color="#1F1F22",
            hover_color="#2A2A2E",
            command=self._hide_stage_view
        )
        btn_hide_stage.pack(side="right", padx=4)

        # Native Frame container to receive MPV --wid
        self.video_viewport = tk.Frame(self.stage_shell, bg="#080808")
        self.video_viewport.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Dynamic Zoom Grid Container
        self.grid_shell = ctk.CTkFrame(
            self.main_content_shell,
            corner_radius=16,
            fg_color=SHELL_BG,
            border_color=SHELL_BORDER,
            border_width=1
        )
        self.grid_shell.pack(fill="both", expand=True)

        self.grid_container = ZoomUserGrid(self.grid_shell)
        self.grid_container.pack(padx=4, pady=4, fill="both", expand=True)
        self.user_tiles = self.grid_container.user_tiles

        # Bottom: Floating Pill Control Island (Detached)
        island = ctk.CTkFrame(
            self.root,
            height=54,
            corner_radius=27,
            fg_color=SHELL_BG,
            border_color=SHELL_BORDER,
            border_width=1
        )
        island.pack(fill="none", pady=(8, 16))

        # Floating Pill Buttons
        self.btn_mute = ctk.CTkButton(
            island,
            text="🎙  Silenciar",
            font=FontManager.get(12, "bold"),
            width=136,
            height=36,
            corner_radius=18,
            fg_color=PILL_IDLE_BG,
            border_color=PILL_IDLE_BORDER,
            border_width=1,
            text_color=PILL_IDLE_TEXT,
            hover_color=PILL_IDLE_HOVER,
            command=self.toggle_mute
        )
        self.btn_mute.pack(side="left", padx=(10, 5), pady=8)

        self.btn_deafen = ctk.CTkButton(
            island,
            text="🎧  Ensordecer",
            font=FontManager.get(12, "bold"),
            width=140,
            height=36,
            corner_radius=18,
            fg_color=PILL_IDLE_BG,
            border_color=PILL_IDLE_BORDER,
            border_width=1,
            text_color=PILL_IDLE_TEXT,
            hover_color=PILL_IDLE_HOVER,
            command=self.toggle_deafen
        )
        self.btn_deafen.pack(side="left", padx=5, pady=8)

        self.btn_screen_share = ctk.CTkButton(
            island,
            text="🖥  Compartir",
            font=FontManager.get(12, "bold"),
            width=140,
            height=36,
            corner_radius=18,
            fg_color=PILL_IDLE_BG,
            border_color=PILL_IDLE_BORDER,
            border_width=1,
            text_color=PILL_IDLE_TEXT,
            hover_color=PILL_IDLE_HOVER,
            command=self.toggle_screen_share
        )
        self.btn_screen_share.pack(side="left", padx=5, pady=8)

        self.btn_disconnect = ctk.CTkButton(
            island,
            text="✕  Desconectar",
            font=FontManager.get(12, "bold"),
            width=136,
            height=36,
            corner_radius=18,
            fg_color=PILL_DANGER_BG,
            border_color=PILL_DANGER_BORDER,
            border_width=1,
            text_color=PILL_DANGER_TEXT,
            hover_color=PILL_DANGER_HOVER,
            command=self.disconnect_and_return
        )
        self.btn_disconnect.pack(side="left", padx=(5, 10), pady=8)

        # Synchronize visual state of controls
        self._update_controls_visual_state()

    # ==================== PUBLIC API & INJECTION ====================
    def show_room_view(self, username: str, server_info: str = "127.0.0.1:5000", is_host: bool = False):
        """
        Public injection hook for visual testing without starting audio hardware.
        """
        self.username = username
        self.is_host = is_host
        if isinstance(server_info, str) and ":" in server_info:
            parts = server_info.split(":")
            self.server_addr = (parts[0], int(parts[1]))
        elif isinstance(server_info, tuple):
            self.server_addr = server_info
        else:
            self.server_addr = ("127.0.0.1", 5000)

        self.setup_room_ui()

    def update_user_list(self, users: List[str]):
        """
        Dynamically redraws participant tiles in Zoom-style grid.
        """
        if self.grid_container is not None:
            self.grid_container.set_users(users, local_username=self.username)
            self.user_tiles = self.grid_container.user_tiles
            self.grid_cols = self.grid_container.grid_cols
            
            # Aplicar avatares cacheados a las tarjetas recién creadas
            for u in users:
                if u in self.avatar_bytes_cache and u in self.user_tiles:
                    self.user_tiles[u].set_avatar_image(self.avatar_bytes_cache[u])

    def _on_user_list_threadsafe(self, users: List[str]):
        try:
            self.root.after(0, self.update_user_list, users)
        except Exception:
            pass

    def _on_user_status_update_threadsafe(self, username: str, is_muted: bool, is_deafened: bool):
        try:
            def apply_status():
                if self.grid_container:
                    self.grid_container.set_user_status(username, is_muted, is_deafened)
            self.root.after(0, apply_status)
        except Exception:
            pass

    def _on_engine_error_threadsafe(self, title: str, message: str):
        try:
            self.root.after(0, lambda: messagebox.showerror(title, message))
        except Exception:
            pass

    def _on_avatar_received_threadsafe(self, username: str, raw_bytes: bytes):
        try:
            self.avatar_bytes_cache[username] = raw_bytes
            def update_avatar():
                if username in self.user_tiles:
                    self.user_tiles[username].set_avatar_image(raw_bytes)
            self.root.after(0, update_avatar)
        except Exception:
            pass

    def on_tile_right_click(self, target_username: str, x: int, y: int):
        if self.volume_popup is not None:
            self.volume_popup.destroy()
            
        self.volume_popup = tk.Toplevel(self.root)
        self.volume_popup.wm_overrideredirect(True)
        self.volume_popup.geometry(f"200x80+{x}+{y}")
        self.volume_popup.configure(bg=SHELL_BG)
        self.volume_popup.attributes("-topmost", True)
        
        # Borde
        frame = ctk.CTkFrame(self.volume_popup, fg_color=CORE_BG, border_color=CORE_BORDER, border_width=1, corner_radius=8)
        frame.pack(fill="both", expand=True, padx=2, pady=2)
        
        lbl = ctk.CTkLabel(frame, text=f"Volumen de {target_username}", font=FontManager.get(11, "bold"), text_color=TEXT_PRIMARY)
        lbl.pack(pady=(8, 2))
        
        current_vol = self.engine.user_volumes.get(target_username, 1.0)
        
        slider = ctk.CTkSlider(frame, from_=0.0, to=2.0, number_of_steps=20, width=160)
        slider.set(current_vol)
        slider.pack(pady=(2, 8))
        
        def on_change(value):
            self.engine.user_volumes[target_username] = float(value)
            
        slider.configure(command=on_change)
        
        # Cerrar si pierde el foco
        def on_focus_out(event):
            if self.volume_popup:
                self.volume_popup.destroy()
                self.volume_popup = None
                
        self.volume_popup.bind("<FocusOut>", on_focus_out)
        self.volume_popup.focus_set()

    # ==================== CONTROLS & STATE ====================
    def toggle_mute(self):
        self.mic_muted, self.deafened = self.engine.toggle_mute()
        self._update_controls_visual_state()
        self.engine.send_user_status(self.mic_muted, self.deafened)
        if self.grid_container and self.username:
            self.grid_container.set_user_status(self.username, self.mic_muted, self.deafened)

    def toggle_deafen(self):
        self.mic_muted, self.deafened = self.engine.toggle_deafen()
        self._update_controls_visual_state()
        self.engine.send_user_status(self.mic_muted, self.deafened)
        if self.grid_container and self.username:
            self.grid_container.set_user_status(self.username, self.mic_muted, self.deafened)

    def _update_controls_visual_state(self):
        """
        Reflects mute/deafen states using configure() (never .config()).
        """
        if not hasattr(self, 'btn_mute') or not hasattr(self, 'btn_deafen'):
            return

        if self.mic_muted:
            self.btn_mute.configure(
                text="🔇  Activar Mic",
                fg_color=PILL_MUTE_BG,
                border_color=PILL_MUTE_BORDER,
                text_color=PILL_MUTE_TEXT,
                hover_color=PILL_MUTE_HOVER
            )
        else:
            self.btn_mute.configure(
                text="🎙  Silenciar",
                fg_color=PILL_IDLE_BG,
                border_color=PILL_IDLE_BORDER,
                text_color=PILL_IDLE_TEXT,
                hover_color=PILL_IDLE_HOVER
            )

        if self.deafened:
            self.btn_deafen.configure(
                text="🔊  Escuchar",
                fg_color=PILL_DEAF_BG,
                border_color=PILL_DEAF_BORDER,
                text_color=PILL_DEAF_TEXT,
                hover_color=PILL_DEAF_HOVER
            )
        else:
            self.btn_deafen.configure(
                text="🎧  Ensordecer",
                fg_color=PILL_IDLE_BG,
                border_color=PILL_IDLE_BORDER,
                text_color=PILL_IDLE_TEXT,
                hover_color=PILL_IDLE_HOVER
            )

        if hasattr(self, 'btn_screen_share') and self.btn_screen_share is not None:
            if self.is_sharing_screen:
                self.btn_screen_share.configure(
                    text="⏹  Dejar de compartir",
                    fg_color=PILL_DANGER_BG,
                    border_color=PILL_DANGER_BORDER,
                    text_color=PILL_DANGER_TEXT,
                    hover_color=PILL_DANGER_HOVER
                )
            else:
                self.btn_screen_share.configure(
                    text="🖥  Compartir",
                    fg_color=PILL_IDLE_BG,
                    border_color=PILL_IDLE_BORDER,
                    text_color=PILL_IDLE_TEXT,
                    hover_color=PILL_IDLE_HOVER
                )

    def toggle_screen_share(self):
        if self.is_sharing_screen:
            self.is_sharing_screen = False
            self.streamer.stop()
            self.engine.send_screen_share_stop()
            self._update_controls_visual_state()
            if self.active_screen_sharer == self.username:
                self._hide_stage_view()
        else:
            host_ip = "127.0.0.1" if self.is_host else (self.server_addr[0] if self.server_addr else "127.0.0.1")
            if self.streamer.start(host_ip, self.username):
                self.is_sharing_screen = True
                stream_url = f"rtsp://{host_ip}:8554/live/{self.username}"
                self.engine.send_screen_share_start(stream_url)
                self._update_controls_visual_state()
                self._show_stage_view(self.username, is_local=True, stream_url=stream_url)
            else:
                err = self.streamer.last_error or "No se pudo iniciar la captura de pantalla con FFmpeg.\nAsegúrate de tener un monitor activo."
                messagebox.showerror("Error de Transmisión", err)

    def _show_stage_view(self, username: str, is_local: bool = False, stream_url: Optional[str] = None):
        if not self.stage_shell or not self.main_content_shell:
            return

        self.active_screen_sharer = username

        # Actualizar título del escenario
        if self.lbl_stage_title:
            if is_local:
                self.lbl_stage_title.configure(text=f"🖥  Estás compartiendo tu pantalla ({self.username})")
            else:
                self.lbl_stage_title.configure(text=f"🖥  Transmisión de {username}")

        # Limpiar visor anterior si lo había
        if self.screen_viewer:
            self.screen_viewer.stop()
            self.screen_viewer = None

        # Limpiar cualquier widget previo dentro del video_viewport
        if self.video_viewport:
            for child in self.video_viewport.winfo_children():
                child.destroy()

        # Re-organizar layout: Stage a la izquierda (expand), Grid a la derecha (compacto)
        self.grid_shell.pack_forget()
        self.stage_shell.pack(side="left", fill="both", expand=True, padx=(0, 6))
        self.grid_shell.pack(side="right", fill="y", padx=(6, 0))
        if self.grid_container:
            self.grid_container.reflow_now()

        if is_local and self.video_viewport:
            # Mostrar tarjeta de estado estilizada para el emisor local (evita pantalla negra y efecto espejo)
            card = ctk.CTkFrame(self.video_viewport, fg_color="#141414", corner_radius=12)
            card.place(relx=0.5, rely=0.5, anchor="center")

            lbl_icon = ctk.CTkLabel(card, text="🖥", font=("Segoe UI Emoji", 48), text_color="#FFFFFF")
            lbl_icon.pack(padx=32, pady=(24, 8))

            lbl_info = ctk.CTkLabel(
                card,
                text="Estás transmitiendo tu pantalla en vivo",
                font=("Maven Pro", 16, "bold"),
                text_color="#FFFFFF"
            )
            lbl_info.pack(padx=32, pady=(0, 4))

            lbl_sub = ctk.CTkLabel(
                card,
                text="Los demás miembros de la sala están viendo tu pantalla en tiempo real.\n(La vista previa local se oculta para evitar el efecto espejo).",
                font=("Maven Pro", 12),
                text_color="#888888",
                justify="center"
            )
            lbl_sub.pack(padx=32, pady=(0, 16))

            btn_stop = ctk.CTkButton(
                card,
                text="⏹  Dejar de compartir",
                font=("Maven Pro", 13, "bold"),
                fg_color="#E05252",
                hover_color="#C0392B",
                text_color="#FFFFFF",
                corner_radius=8,
                height=34,
                command=self.toggle_screen_share
            )
            btn_stop.pack(padx=32, pady=(0, 24))

        elif not is_local and stream_url and self.video_viewport:
            def launch_viewer():
                if self.active_screen_sharer == username and self.video_viewport:
                    self.screen_viewer = ScreenShareViewer(self.video_viewport, stream_url)
                    self.screen_viewer.start()
            self.root.after(400, launch_viewer)

    def _hide_stage_view(self):
        if self.screen_viewer:
            self.screen_viewer.stop()
            self.screen_viewer = None

        if self.video_viewport:
            for child in self.video_viewport.winfo_children():
                child.destroy()

        self.active_screen_sharer = None

        if self.stage_shell and self.grid_shell:
            self.stage_shell.pack_forget()
            self.grid_shell.pack_forget()
            self.grid_shell.pack(fill="both", expand=True)
            if self.grid_container:
                self.grid_container.reflow_now()

    def _on_screen_share_start_threadsafe(self, username: str, stream_url: str):
        try:
            self.root.after(0, lambda: self._handle_remote_screen_share_start(username, stream_url))
        except Exception:
            pass

    def _handle_remote_screen_share_start(self, username: str, stream_url: str):
        if username == self.username:
            return

        # Resolver IP real del servidor MediaMTX:
        # Si este cliente es el host, MediaMTX corre localmente (127.0.0.1).
        # Esto evita el fallo de NAT loopback de routers que bloquean conexiones a la IP pública desde la LAN.
        if self.is_host:
            resolved_url = f"rtsp://127.0.0.1:8554/live/{username}"
        else:
            server_ip = self.server_addr[0] if self.server_addr else "127.0.0.1"
            resolved_url = f"rtsp://{server_ip}:8554/live/{username}"

        self._show_stage_view(username, is_local=False, stream_url=resolved_url)

    def _on_screen_share_stop_threadsafe(self, username: str):
        try:
            self.root.after(0, lambda: self._handle_remote_screen_share_stop(username))
        except Exception:
            pass

    def _handle_remote_screen_share_stop(self, username: str):
        if self.active_screen_sharer == username:
            self._hide_stage_view()

    def start_host(self):
        username = self.entry_username.get().strip()
        port_str = self.entry_port.get().strip()

        if not username:
            messagebox.showwarning("Falta dato", "Por favor ingresa un nombre de usuario.")
            return

        try:
            port = int(port_str)
        except ValueError:
            messagebox.showwarning("Error", "El puerto debe ser un número entero.")
            return

        self.username = username
        self.is_host = True
        self.server_addr = ("127.0.0.1", port)
        self._save_config()

        if not self.engine.start("127.0.0.1", port, username, is_host=True):
            return

        if self.selected_avatar_path:
            self.engine.send_avatar_image(self.selected_avatar_path)

        self.setup_room_ui()

    def start_client(self):
        username = self.entry_username.get().strip()
        ip = self.entry_ip.get().strip()
        port_str = self.entry_port.get().strip()

        if not username or not ip:
            messagebox.showwarning("Faltan datos", "Por favor ingresa un nombre y la IP del Host.")
            return

        try:
            port = int(port_str)
        except ValueError:
            messagebox.showwarning("Error", "El puerto debe ser un número entero.")
            return

        self.username = username
        self.is_host = False
        self.server_addr = (ip, port)
        self.last_ip = ip
        self._save_config()

        if not self.engine.start(ip, port, username, is_host=False):
            return

        if self.selected_avatar_path:
            self.engine.send_avatar_image(self.selected_avatar_path)

        self.setup_room_ui()

    def start_audio_client(self):
        """Backward-compatible helper."""
        if self.server_addr and self.username:
            self.engine.start(self.server_addr[0], self.server_addr[1], self.username, is_host=self.is_host)

    def disconnect_and_return(self):
        if self.is_sharing_screen:
            self.streamer.stop()
            self.is_sharing_screen = False
        if self.screen_viewer:
            self.screen_viewer.stop()
            self.screen_viewer = None
        self.engine.stop()
        self.setup_login_ui()

    def cleanup_audio(self):
        if self.is_sharing_screen:
            self.streamer.stop()
        if self.screen_viewer:
            self.screen_viewer.stop()
        self.engine.stop()

    def on_closing(self):
        if hasattr(self, 'discovery_listener') and self.discovery_listener:
            self.discovery_listener.stop()
            self.discovery_listener = None
        if self.is_sharing_screen:
            self.streamer.stop()
        if self.screen_viewer:
            self.screen_viewer.stop()
        self.engine.stop()
        self.root.destroy()


# Backward-compatible alias
VoiceClientGUI = VoiceClientApp


if __name__ == "__main__":
    app = VoiceClientApp()
    app.root.mainloop()
