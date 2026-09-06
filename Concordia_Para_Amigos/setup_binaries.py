import os
import sys
import urllib.request
import zipfile
import subprocess
import shutil

current_dir = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(current_dir).lower() == "scripts":
    BASE_DIR = os.path.dirname(current_dir)
else:
    BASE_DIR = current_dir
BIN_DIR = os.path.join(BASE_DIR, "bin")

BINARIES = {
    "mediamtx.exe": {
        "url": "https://github.com/bluenviron/mediamtx/releases/download/v1.21.0/mediamtx_v1.21.0_windows_amd64.zip",
        "archive_type": "zip",
        "internal_path": "mediamtx.exe"
    },
    "mpv.exe": {
        "url": "https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/20260903/mpv-x86_64-20260903-git-69e63f425a.7z",
        "archive_type": "7z",
        "internal_path": "mpv.exe"
    },
    "ffmpeg.exe": {
        "url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
        "archive_type": "zip",
        "internal_path": "bin/ffmpeg.exe"
    }
}

def download_with_progress(url, dest_path, desc):
    print(f"[*] Descargando {desc}...")
    def reporthook(count, block_size, total_size):
        if total_size > 0:
            percent = int(count * block_size * 100 / total_size)
            mb = (count * block_size) / (1024 * 1024)
            total_mb = total_size / (1024 * 1024)
            sys.stdout.write(f"\r    -> {percent}% ({mb:.1f}MB / {total_mb:.1f}MB)")
            sys.stdout.flush()
    
    headers = {'User-Agent': 'Mozilla/5.0'}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as response, open(dest_path, 'wb') as out_file:
        total_size = int(response.info().get('Content-Length', -1))
        count = 0
        block_size = 1024 * 64
        while True:
            chunk = response.read(block_size)
            if not chunk:
                break
            out_file.write(chunk)
            count += 1
            reporthook(count, block_size, total_size)
    print("\n[OK] Descarga completada.")

def setup_binaries():
    os.makedirs(BIN_DIR, exist_ok=True)
    all_ok = True
    
    for bin_name, info in BINARIES.items():
        target_exe = os.path.join(BIN_DIR, bin_name)
        if os.path.exists(target_exe):
            print(f"[OK] {bin_name} ya esta instalado en bin/")
            continue
            
        archive_name = f"temp_{bin_name}.{info['archive_type']}"
        archive_path = os.path.join(BIN_DIR, archive_name)
        
        try:
            download_with_progress(info["url"], archive_path, bin_name)
            print(f"[*] Extrayendo {bin_name}...")
            
            if info["archive_type"] == "zip":
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    matched = None
                    for member in zip_ref.namelist():
                        if member.replace("\\", "/").endswith(info["internal_path"]):
                            matched = member
                            break
                    if matched:
                        with zip_ref.open(matched) as source, open(target_exe, "wb") as target:
                            shutil.copyfileobj(source, target)
                        print(f"[OK] {bin_name} extraido correctamente.")
                    else:
                        raise RuntimeError(f"No se encontro {info['internal_path']} en el zip")
            elif info["archive_type"] == "7z":
                temp_extract = os.path.join(BIN_DIR, "temp_7z")
                os.makedirs(temp_extract, exist_ok=True)
                cmd = ["tar.exe", "-xf", archive_path, "-C", temp_extract]
                subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                
                found = False
                for root, dirs, files in os.walk(temp_extract):
                    if bin_name in files:
                        shutil.move(os.path.join(root, bin_name), target_exe)
                        found = True
                        break
                shutil.rmtree(temp_extract, ignore_errors=True)
                if not found:
                    raise RuntimeError(f"No se encontro {bin_name} en el 7z")
                print(f"[OK] {bin_name} extraido correctamente.")
                
        except Exception as e:
            print(f"[X] Error configurando {bin_name}: {e}")
            all_ok = False
        finally:
            if os.path.exists(archive_path):
                try:
                    os.remove(archive_path)
                except Exception:
                    pass

    # Asegurar la creacion de mediamtx.yml para permitir la publicacion de rutas dinamicas sin conflicto de puertos
    mediamtx_cfg = os.path.join(BIN_DIR, "mediamtx.yml")
    try:
        with open(mediamtx_cfg, "w", encoding="utf-8") as f:
            f.write(
                "api: no\n"
                "rtmp: no\n"
                "hls: no\n"
                "webrtc: no\n"
                "srt: no\n"
                "rtspTransports: [tcp]\n"
                "rtspAddress: :8554\n"
                "rtpAddress: :8002\n"
                "rtcpAddress: :8003\n"
                "paths:\n"
                "  all_others:\n"
            )
        print("[OK] mediamtx.yml configurado correctamente.")
    except Exception as e:
        print(f"[X] No se pudo crear mediamtx.yml: {e}")

    if not all_ok:
        sys.exit(1)

if __name__ == "__main__":
    setup_binaries()
