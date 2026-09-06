import os
import sys
import time
import subprocess
import tkinter as tk
import customtkinter as ctk

def test_embed():
    app = ctk.CTk()
    app.geometry("800x600")
    app.title("Test MPV Embedding")

    top_label = ctk.CTkLabel(app, text="Prueba de incrustación de MPV en CustomTkinter", font=("Helvetica", 14, "bold"))
    top_label.pack(pady=10)

    video_frame = tk.Frame(app, bg="black", width=640, height=360)
    video_frame.pack(expand=True, fill="both", padx=20, pady=20)
    video_frame.pack_propagate(False)

    app.update_idletasks()
    hwnd = video_frame.winfo_id()
    print(f"[TEST] Window ID (HWND): {hwnd}")

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mpv_bin = os.path.join(base_dir, "bin", "mpv.exe")

    # Reproducir un testsrc generado internamente por MPV
    cmd = [
        mpv_bin,
        f"--wid={hwnd}",
        "--no-border",
        "--osc=no",
        "--osd-level=0",
        "av://lavfi:testsrc=size=640x360:rate=30"
    ]

    proc = subprocess.Popen(cmd)

    def on_close():
        proc.terminate()
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", on_close)
    if "--interactive" not in sys.argv:
        app.after(1000, on_close)

    app.mainloop()

if __name__ == "__main__":
    test_embed()
