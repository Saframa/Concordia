"""
Visual Test Harness & Automated Verification for Discord Caserito UI Grid.

Tri-Mode Execution:
1. Visual Interactive Mode:
   python test_ui_grid.py
   (Launches the CustomTkinter GUI with 6 mock participants in the Zoom-style grid)

2. Automated Headless Check Mode:
   python test_ui_grid.py --check
   python test_ui_grid.py --headless
   (Runs programmatic assertions on tile count >= 5, photo placeholders, username
   labels, responsive reflow, and button state toggles; exits code 0 in <1.5s)

3. Pytest Mode:
   pytest test_ui_grid.py -v
   (Standard pytest discovery and test execution)
"""

import sys
import time
import pytest
import customtkinter as ctk
from discord_caserito import (
    VoiceClientGUI,
    VoiceClientApp,
    GridCalculator,
    FontManager,
    AudioDenoiser,
    GHOST_USERS,
    ParticipantTile
)


def run_headless_checks(app: ctk.CTk = None) -> int:
    """
    Executes full headless assertion suite against VoiceClientGUI without mainloop.
    Validates tile count >= 5, photo placeholders, name labels, responsive reflow,
    speaking indicator ring, and mutual mute/deafen button coupling.
    Exits with code 0 on success.
    """
    start_time = time.time()
    print("=== STARTING DISCORD CASERITO HEADLESS UI GRID CHECKS ===")

    owns_app = False
    if app is None:
        app = ctk.CTk()
        owns_app = True

    app.geometry("900x650")

    # 2. Instantiate VoiceClientGUI with mock parameters
    client = VoiceClientGUI(app)
    client.server_addr = ("127.0.0.1", 50000)
    client.username = "Satoshi Nakamoto"
    client.is_host = True

    # 3. Setup Room UI directly without starting audio client or UDP server
    client.setup_room_ui()

    # 4. Inject 6 mock participants
    client.update_user_list(GHOST_USERS)
    app.update_idletasks()
    app.update()

    # 5. Assertion: Participant tile count (>= 5 required by AC-2, 6 injected)
    tile_count = len(client.user_tiles)
    print(f"[*] Validating participant tile count: {tile_count} tiles found")
    assert tile_count >= 5, f"Expected >= 5 participant tiles, got {tile_count}"
    assert tile_count == len(GHOST_USERS), f"Expected {len(GHOST_USERS)} tiles, got {tile_count}"

    # 6. Assertion: Inspect photo placeholder & name label in each participant tile
    for user, tile in client.user_tiles.items():
        assert hasattr(tile, "placeholder_frame"), f"Tile for {user} missing 'placeholder_frame'"
        assert hasattr(tile, "name_label"), f"Tile for {user} missing 'name_label'"
        assert hasattr(tile, "lbl_initials"), f"Tile for {user} missing 'lbl_initials'"
        assert tile.placeholder_frame.winfo_exists(), f"Placeholder frame not mapped for {user}"
        assert tile.name_label.winfo_exists(), f"Name label not mapped for {user}"

        # First name verification
        first_name = user.split()[0]
        displayed_name = tile.name_label.cget("text")
        assert first_name in displayed_name, f"Displayed name '{displayed_name}' does not contain '{first_name}'"

        # Squircle monogram initials verification
        initials = tile.lbl_initials.cget("text")
        assert len(initials) in (1, 2), f"Expected 1-2 character monogram initials, got '{initials}'"

    print("[*] All participant tiles verified with photo placeholder and centered username")

    # 7. Assertion: Speaking Indicator Ring Toggle
    test_user = "Ada Lovelace"
    ada_tile = client.user_tiles[test_user]
    ada_tile.set_speaking(True)
    assert ada_tile.cget("border_color") == "#FFFFFF", "Active speaking border ring must be pure white (#FFFFFF)"
    assert ada_tile.cget("border_width") == 2, "Active speaking border ring must be 2px width"
    ada_tile.set_speaking(False)
    assert ada_tile.cget("border_color") == "#262626", "Inactive tile border must return to idle (#262626)"
    assert ada_tile.cget("border_width") == 1, "Inactive tile border must return to 1px width"
    print("[*] Speaking halo indicator toggle verified")

    # 7b. Assertion: Mute/Deafen Status Badge on ParticipantTile (Discord style)
    ada_tile.set_status(is_muted=True, is_deafened=False)
    assert "🎙" in ada_tile.lbl_status_icon.cget("text"), "Status badge must display microphone icon when muted"
    ada_tile.set_status(is_muted=True, is_deafened=True)
    assert "🎧" in ada_tile.lbl_status_icon.cget("text"), "Status badge must display headphone icon when deafened"
    ada_tile.set_status(is_muted=False, is_deafened=False)
    assert ada_tile.is_muted is False and ada_tile.is_deafened is False
    print("[*] Discord-style participant mute/deafen status badges verified")

    # 8. Assertion: Responsive Reflow on Window Resize
    # Wide Window: 960x650 -> Expected 3 columns (2 rows) for 6 participants
    app.geometry("960x650")
    app.update_idletasks()
    app.update()
    assert client.grid_cols == 3, f"Expected 3 columns on 960px width, got {client.grid_cols}"
    print(f"[*] Wide layout verified: {client.grid_cols} columns at 960px width")

    # Narrow Window: 540x700 -> Expected 2 columns (3 rows) for 6 participants
    app.geometry("540x700")
    app.update_idletasks()
    app.update()
    assert client.grid_cols == 2, f"Expected 2 columns on 540px width, got {client.grid_cols}"
    print(f"[*] Narrow layout verified: {client.grid_cols} columns at 540px width")

    # 9. Assertion: Mute / Deafen Button State Machine & Visual Toggles
    assert client.mic_muted is False, "Initial mic state must be unmuted"
    assert client.deafened is False, "Initial sound state must be undeafened"

    # Mute Toggle (Unmuted -> Muted)
    initial_mute_text = client.btn_mute.cget("text")
    client.toggle_mute()
    assert client.mic_muted is True, "Mic must be muted after toggle_mute()"
    assert client.btn_mute.cget("text") != initial_mute_text, "Mute button text must update"
    assert "Activar Mic" in client.btn_mute.cget("text"), "Mute button text must show un-mute prompt"
    assert client.btn_mute.cget("fg_color") == "#2D1517", "Mute button active color must be #2D1517"

    # Deafen Toggle (Undeafened -> Deafened)
    initial_deafen_text = client.btn_deafen.cget("text")
    client.toggle_deafen()
    assert client.deafened is True, "Sound must be deafened after toggle_deafen()"
    assert client.btn_deafen.cget("text") != initial_deafen_text, "Deafen button text must update"
    assert "Escuchar" in client.btn_deafen.cget("text"), "Deafen button text must show listen prompt"
    assert client.btn_deafen.cget("fg_color") == "#2E1D10", "Deafen button active color must be #2E1D10"
    assert client.mic_muted is True, "Mic must remain/become muted when deafened"

    # Unmute while Deafened -> Must automatically un-deafen
    client.toggle_mute()
    assert client.mic_muted is False, "Mic must be unmuted"
    assert client.deafened is False, "Deafened state must turn off when unmuting"
    assert "Silenciar" in client.btn_mute.cget("text"), "Mute button text must return to Silenciar"
    assert "Ensordecer" in client.btn_deafen.cget("text"), "Deafen button text must return to Ensordecer"

    # Deafening while unmuted -> Must automatically mute mic
    client.toggle_deafen()
    assert client.deafened is True, "Deafened state must be True"
    assert client.mic_muted is True, "Deafening must automatically mute mic"
    assert "Activar Mic" in client.btn_mute.cget("text"), "Mute button must show Activar Mic"

    # Undeafening while muted -> Mic must STAY muted
    client.toggle_deafen()
    assert client.deafened is False, "Deafened state must be False"
    assert client.mic_muted is True, "Mic must stay muted after undeafening"
    assert "Activar Mic" in client.btn_mute.cget("text"), "Mute button must still show Activar Mic"
    assert "Ensordecer" in client.btn_deafen.cget("text"), "Deafen button must show Ensordecer"

    print("[*] Mute/Deafen state machine and visual button toggles verified")

    # 10. Clean window destruction
    if owns_app:
        app.destroy()
    elapsed = time.time() - start_time
    print(f"[*] Headless verification completed in {elapsed:.3f}s (< 1.5s target)")
    print("ALL UI GRID CHECKS PASSED SUCCESSFULLY.")
    return 0


# ==================== PYTEST TEST SUITE ====================

@pytest.fixture(scope="module")
def app_instance():
    app = ctk.CTk()
    app.geometry("900x650")
    yield app
    try:
        app.destroy()
    except Exception:
        pass


def test_ui_grid_participant_tiles(app_instance):
    """Verify participant tile creation, photo placeholder, monogram and username."""
    client = VoiceClientGUI(app_instance)
    client.show_room_view("Satoshi Nakamoto", "127.0.0.1:5000", is_host=True)
    client.update_user_list(GHOST_USERS)
    app_instance.update_idletasks()
    app_instance.update()

    assert len(client.user_tiles) == 6
    for u in GHOST_USERS:
        assert u in client.user_tiles
        tile = client.user_tiles[u]
        assert hasattr(tile, "placeholder_frame")
        assert hasattr(tile, "name_label")
        assert hasattr(tile, "lbl_initials")


def test_ui_grid_responsive_reflow(app_instance):
    """Verify dynamic reflow between 3 columns (wide) and 2 columns (narrow)."""
    client = VoiceClientGUI(app_instance)
    client.show_room_view("LocalTester", "127.0.0.1:5000", is_host=False)
    client.update_user_list(GHOST_USERS)

    # Wide geometry -> 3 columns
    app_instance.geometry("960x650")
    app_instance.update_idletasks()
    app_instance.update()
    assert client.grid_cols == 3

    # Narrow geometry -> 2 columns
    app_instance.geometry("540x700")
    app_instance.update_idletasks()
    app_instance.update()
    assert client.grid_cols == 2


def test_ui_grid_mute_deafen_toggles(app_instance):
    """Verify bidirectional mute/deafen coupling and visual configure() updates."""
    client = VoiceClientGUI(app_instance)
    client.show_room_view("LocalTester", "127.0.0.1:5000", is_host=False)

    # Initially unmuted, undeafened
    assert client.mic_muted is False
    assert client.deafened is False

    # Mute toggle
    client.toggle_mute()
    assert client.mic_muted is True
    assert "Activar Mic" in client.btn_mute.cget("text")

    # Deafen toggle
    client.toggle_deafen()
    assert client.deafened is True
    assert client.mic_muted is True
    assert "Escuchar" in client.btn_deafen.cget("text")

    # Unmute while deafened -> undeafens
    client.toggle_mute()
    assert client.mic_muted is False
    assert client.deafened is False
    assert "Silenciar" in client.btn_mute.cget("text")
    assert "Ensordecer" in client.btn_deafen.cget("text")


def test_grid_calculator_math():
    """Verify pure math GridCalculator aspect-ratio optimization."""
    # 1 user -> 1x1
    cols, rows, tw, th, pos = GridCalculator.compute_layout(1, 800, 600)
    assert cols == 1 and rows == 1 and len(pos) == 1

    # 2 users -> 2x1 on wide
    cols, rows, tw, th, pos = GridCalculator.compute_layout(2, 800, 600)
    assert cols == 2 and rows == 1 and len(pos) == 2

    # 6 users wide -> 3x2
    cols, rows, tw, th, pos = GridCalculator.compute_layout(6, 920, 500)
    assert cols == 3 and rows == 2 and len(pos) == 6

    # 6 users narrow -> 2x3
    cols, rows, tw, th, pos = GridCalculator.compute_layout(6, 500, 550)
    assert cols == 2 and rows == 3 and len(pos) == 6


def test_font_manager_no_banned_fonts(app_instance):
    """Verify FontManager never resolves to banned fonts (Arial, Roboto, Inter, Helvetica)."""
    resolved = FontManager.get_family()
    banned = ["Arial", "Roboto", "Helvetica", "Inter", "Open Sans"]
    assert resolved not in banned, f"FontManager resolved banned font: {resolved}"
    assert isinstance(FontManager.get(14, "bold"), ctk.CTkFont)


def test_audio_denoiser_resilience():
    """Verify AudioDenoiser processes 960 bytes without exceptions."""
    denoiser = AudioDenoiser(48000)
    raw_pcm = b"\x00\x00" * 480
    filtered = denoiser.filter(raw_pcm)
    assert isinstance(filtered, bytes)
    assert len(filtered) == 960


def test_headless_checks_suite(app_instance):
    """Verify the full headless assertion flow passes with code 0."""
    result = run_headless_checks(app=app_instance)
    assert result == 0


# ==================== MAIN EXECUTION ROUTING ====================

if __name__ == "__main__":
    # Check for automated headless flags
    if "--check" in sys.argv or "--headless" in sys.argv:
        sys.exit(run_headless_checks())

    # Default: Visual Interactive Mode
    print("Launching Discord Caserito UI Grid Visual Interactive Test...")
    print(f"Injecting {len(GHOST_USERS)} mock participants: {', '.join(GHOST_USERS)}")
    app = ctk.CTk()
    client = VoiceClientGUI(app)
    client.show_room_view("Satoshi Nakamoto (Tú)", "127.0.0.1:5000", is_host=True)
    client.update_user_list(GHOST_USERS)

    # Pulse speaking state and simulate mute/deafen badges for visual verification
    def simulate_speaking():
        if "Ada Lovelace" in client.user_tiles:
            client.user_tiles["Ada Lovelace"].set_speaking(True)
        if "Alan Turing" in client.user_tiles:
            client.user_tiles["Alan Turing"].set_status(is_muted=True, is_deafened=False)
        if "Linus Torvalds" in client.user_tiles:
            client.user_tiles["Linus Torvalds"].set_status(is_muted=True, is_deafened=True)
        app.after(1500, lambda: client.user_tiles["Ada Lovelace"].set_speaking(False) if "Ada Lovelace" in client.user_tiles else None)

    app.after(1000, simulate_speaking)
    app.mainloop()
