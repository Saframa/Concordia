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

def drain_messages(sock, expected_action, timeout=2.0):
    start = time.time()
    while time.time() - start < timeout:
        sock.settimeout(max(0.1, timeout - (time.time() - start)))
        try:
            data, _ = sock.recvfrom(4096)
            msg = json.loads(data.decode())
            if msg.get("action") == expected_action:
                return msg
        except socket.timeout:
            break
    return None

def test_user_status_signaling_and_sync():
    server = SFUServer(host="127.0.0.1", port=0)
    server.start()
    bound_port = server.bound_port

    try:
        sock_alice = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock_bob = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        # 1. Conectar Alice y Bob
        sock_alice.sendto(json.dumps({"action": "connect", "username": "Alice"}).encode(), ("127.0.0.1", bound_port))
        sock_bob.sendto(json.dumps({"action": "connect", "username": "Bob"}).encode(), ("127.0.0.1", bound_port))

        time.sleep(0.1)

        # 2. Alice se mutea
        sock_alice.sendto(json.dumps({
            "action": "user_status_update",
            "username": "Alice",
            "is_muted": True,
            "is_deafened": False
        }).encode(), ("127.0.0.1", bound_port))

        # 3. Bob debe recibir la actualización de Alice
        msg = drain_messages(sock_bob, "user_status_update")
        assert msg is not None, "Bob did not receive user_status_update"
        assert msg.get("username") == "Alice"
        assert msg.get("is_muted") is True
        assert msg.get("is_deafened") is False
        assert server.user_states.get("Alice") == {"is_muted": True, "is_deafened": False}

        # 4. Alice se ensordece
        sock_alice.sendto(json.dumps({
            "action": "user_status_update",
            "username": "Alice",
            "is_muted": True,
            "is_deafened": True
        }).encode(), ("127.0.0.1", bound_port))

        msg = drain_messages(sock_bob, "user_status_update")
        assert msg is not None
        assert msg.get("is_deafened") is True
        assert server.user_states.get("Alice") == {"is_muted": True, "is_deafened": True}

        # 5. Charlie se conecta después y debe recibir el estado en room_state
        sock_charlie = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock_charlie.sendto(json.dumps({"action": "connect", "username": "Charlie"}).encode(), ("127.0.0.1", bound_port))

        room_state_msg = drain_messages(sock_charlie, "room_state")
        assert room_state_msg is not None
        states = room_state_msg.get("user_states", {})
        assert states.get("Alice") == {"is_muted": True, "is_deafened": True}

        # 6. Alice se desconecta, su estado debe removerse del servidor
        sock_alice.sendto(json.dumps({"action": "disconnect", "username": "Alice"}).encode(), ("127.0.0.1", bound_port))
        time.sleep(0.1)
        assert "Alice" not in server.user_states

        sock_alice.close()
        sock_bob.close()
        sock_charlie.close()
    finally:
        server.stop()
