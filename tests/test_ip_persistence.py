import os
import json
import tempfile
import pytest

from discord_caserito import VoiceClientApp

def test_last_ip_saved_and_loaded():
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_file = os.path.join(tmpdir, ".concordia_profile.json")
        # Save initial profile with last_ip
        with open(cfg_file, "w", encoding="utf-8") as f:
            json.dump({"username": "TestUser", "last_ip": "192.168.1.150"}, f)

        # Mock app without UI rendering
        class DummyRoot:
            def title(self, *a): pass
            def geometry(self, *a): pass
            def minsize(self, *a): pass
            def configure(self, *a): pass
            def protocol(self, *a): pass
            def bind(self, *a): pass
            def winfo_children(self): return []

        app = VoiceClientApp.__new__(VoiceClientApp)
        app.root = DummyRoot()
        app.config_path = cfg_file
        app.username = ""
        app.selected_avatar_path = None
        app.last_ip = ""
        app._load_config()

        assert app.username == "TestUser"
        assert app.last_ip == "192.168.1.150"

        # Update last_ip and save
        app.last_ip = "26.100.200.50"
        app._save_config()

        with open(cfg_file, "r", encoding="utf-8") as f:
            saved_data = json.load(f)

        assert saved_data["last_ip"] == "26.100.200.50"
