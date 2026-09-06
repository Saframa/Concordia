@echo off
title Probar Stream GPU DirectX + MPV
echo ========================================================
echo Probando captura de pantalla por GPU (DirectX + NVENC)
echo ========================================================
echo.

:: 1. Verificar si MediaMTX esta corriendo
tasklist /fi "imagename eq mediamtx.exe" | find /i "mediamtx.exe" >nul
if errorlevel 1 (
    echo [!] MediaMTX no estaba corriendo. Iniciandolo...
    start /min "" "bin\mediamtx.exe" "mediamtx.yml"
    timeout /t 1 /nobreak >nul
)

echo [1/2] Iniciando captura de pantalla por GPU a 60 FPS...
start "FFmpeg - Transmitiendo Pantalla" cmd /k "bin\ffmpeg.exe -f lavfi -i ddagrab=framerate=60:draw_mouse=1 -c:v h264_nvenc -preset p1 -tune ull -zerolatency 1 -g 30 -keyint_min 30 -forced-idr 1 -b:v 3500k -maxrate 4000k -bufsize 2000k -f rtsp -rtsp_transport tcp rtsp://127.0.0.1:8554/live/test"

echo Esperando 2 segundos a que la transmision este lista...
timeout /t 2 /nobreak >nul

echo [2/2] Abriendo reproductor MPV...
"bin\mpv.exe" --force-window=yes --rtsp-transport=tcp rtsp://127.0.0.1:8554/live/test

echo.
echo Cerrando FFmpeg...
taskkill /f /im ffmpeg.exe >nul 2>&1
echo Prueba finalizada.
pause
