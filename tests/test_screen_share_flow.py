import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import json
import socket
import time
import pytest

from sfu.server import SFUServer
from discord_caserito import ScreenCaptureStreamer, ScreenShareViewer, AudioEngine

def test_screen_share_streamer_init():
    streamer = ScreenCaptureStreamer()
    assert not streamer.is_streaming
    assert streamer.process is None

def test_screen_share_signaling():
    # 1. Iniciar SFUServer en puerto dinámico
    server = SFUServer(host="127.0.0.1", port=0)
    server.start()
    bound_port = server.bound_port

    try:
        sock_sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock_viewer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock_sender.settimeout(2.0)
        sock_viewer.settimeout(2.0)

        # 2. Conectar dos clientes simulados
        sock_sender.sendto(json.dumps({"action": "connect", "username": "Alice"}).encode(), ("127.0.0.1", bound_port))
        sock_viewer.sendto(json.dumps({"action": "connect", "username": "Bob"}).encode(), ("127.0.0.1", bound_port))

        time.sleep(0.1)

        # 3. Alice inicia transmisión de pantalla
        stream_url = "rtsp://127.0.0.1:8554/live/Alice"
        sock_sender.sendto(json.dumps({
            "action": "screen_share_start",
            "username": "Alice",
            "stream_url": stream_url
        }).encode(), ("127.0.0.1", bound_port))

        # 4. Bob debe recibir el aviso de inicio
        data, _ = sock_viewer.recvfrom(4096)
        msg = json.loads(data.decode())
        # Descartar room_state si llega primero
        if msg.get("action") == "room_state":
            data, _ = sock_viewer.recvfrom(4096)
            msg = json.loads(data.decode())

        assert msg.get("action") == "screen_share_start"
        assert msg.get("username") == "Alice"
        assert msg.get("stream_url") == stream_url
        assert "Alice" in server.active_screen_shares

        # 5. Alice detiene transmisión de pantalla
        sock_sender.sendto(json.dumps({
            "action": "screen_share_stop",
            "username": "Alice"
        }).encode(), ("127.0.0.1", bound_port))

        # 6. Bob debe recibir el aviso de detención
        data, _ = sock_viewer.recvfrom(4096)
        msg = json.loads(data.decode())
        assert msg.get("action") == "screen_share_stop"
        assert msg.get("username") == "Alice"
        assert "Alice" not in server.active_screen_shares

    finally:
        sock_sender.close()
        sock_viewer.close()
        server.stop()

if __name__ == "__main__":
    test_screen_share_streamer_init()
    test_screen_share_signaling()
    print("ALL SCREEN SHARE TESTS PASSED SUCCESSFULLY.")
