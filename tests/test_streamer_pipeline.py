import os
import subprocess
import time
import pytest

def test_mediamtx_config_exists():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mediamtx_cfg = os.path.join(base_dir, 'bin', 'mediamtx.yml')
    assert os.path.exists(mediamtx_cfg), 'bin/mediamtx.yml must exist'
    with open(mediamtx_cfg, 'r', encoding='utf-8') as f:
        content = f.read()
    assert 'all_others' in content or 'all' in content, 'mediamtx.yml must contain all_others path config'

def test_mediamtx_accepts_dynamic_stream():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    mediamtx_bin = os.path.join(base_dir, 'bin', 'mediamtx.exe')
    ffmpeg_bin = os.path.join(base_dir, 'bin', 'ffmpeg.exe')

    if not os.path.exists(mediamtx_bin) or not os.path.exists(ffmpeg_bin):
        pytest.skip('Binaries not found in bin/')

    creationflags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    mtx = subprocess.Popen(
        [mediamtx_bin],
        cwd=os.path.dirname(mediamtx_bin),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags
    )
    time.sleep(1.0)

    try:
        pub_cmd = [
            ffmpeg_bin,
            '-hide_banner',
            '-loglevel', 'error',
            '-re',
            '-f', 'lavfi',
            '-i', 'testsrc=size=320x240:rate=15',
            '-t', '2',
            '-pix_fmt', 'yuv420p',
            '-c:v', 'libx264',
            '-preset', 'ultrafast',
            '-tune', 'zerolatency',
            '-f', 'rtsp',
            '-rtsp_transport', 'tcp',
            'rtsp://127.0.0.1:8554/live/testuser'
        ]
        pub_proc = subprocess.run(pub_cmd, capture_output=True, text=True)
        assert pub_proc.returncode == 0, f'FFmpeg publish failed: {pub_proc.stderr}'
    finally:
        mtx.terminate()
        try:
            mtx.wait(timeout=2.0)
        except Exception:
            mtx.kill()
