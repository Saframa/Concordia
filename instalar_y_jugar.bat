@echo off
cd /d "%~dp0"
title Iniciando Concordia...
echo ==============================================
echo    Instalador y Lanzador - Concordia
echo ==============================================
echo.

:: 1. Comprobar si Python esta instalado
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Python no esta instalado o hay un conflicto con Windows.
    echo [*] Intentando instalar Python 3.11 automaticamente desde la tienda de Windows...
    
    :: Intentar instalar usando winget (incluido en Windows 10/11)
    winget install --id 9NRWM7N2SVN0 --accept-package-agreements --accept-source-agreements >nul 2>&1
    
    if %errorlevel% equ 0 (
        echo.
        echo [OK] PYTHON SE HA INSTALADO CORRECTAMENTE DESDE LA TIENDA.
        echo [!] IMPORTANTE: Cierra esta ventana y vuelve a darle doble clic al archivo.
        pause
        exit /b
    )
    
    :: Fallback: Abrir la tienda de Windows para que el usuario le de a "Obtener"
    echo.
    echo [X] La instalacion silenciosa fallo. 
    echo Se abrira la Tienda de Microsoft Store en la pagina oficial de Python.
    echo Por favor, dale al boton "Obtener" o "Instalar" y espera a que termine.
    echo Una vez instalado, vuelve a abrir este archivo.
    pause
    start ms-windows-store://pdp/?productid=9NRWM7N2SVN0
    exit /b
)

echo [OK] Python detectado correctamente.
echo Comprobando librerias de audio...

:: 2. Comprobar e instalar dependencias (PyAudio, pyrnnoise, customtkinter, pillow)
python -c "import pyaudio; import pyrnnoise; import customtkinter; import PIL" >nul 2>&1
if %errorlevel% neq 0 (
    echo [*] Faltan librerias requeridas. Procediendo a instalarlas automaticamente...
    python -m pip install --upgrade pip >nul 2>&1
    python -m pip install pyaudio pyrnnoise customtkinter pillow
    
    :: Fallback por si falla por falta de C++
    if %errorlevel% neq 0 (
        echo [!] Hubo un error instalando PyAudio normalmente. Usando metodo alternativo Pipwin...
        python -m pip install pipwin
        python -m pipwin install pyaudio
        python -m pip install pyrnnoise customtkinter pillow
    )
    echo [OK] Librerias instaladas.
) else (
    echo [OK] Todas las librerias ya estaban instaladas.
)

:: 3. Comprobar componentes multimedia (FFmpeg, MediaMTX, MPV)
if not exist "bin\ffmpeg.exe" goto :download_binaries
if not exist "bin\mediamtx.exe" goto :download_binaries
if not exist "bin\mpv.exe" goto :download_binaries
goto :start_app

:download_binaries
echo.
echo ==============================================================
echo [*] Configurando herramientas de pantalla compartida...
echo [*] Esto se realiza una unica vez. Por favor espera...
echo ==============================================================
echo.
if exist "scripts\setup_binaries.py" (
    python scripts\setup_binaries.py
) else if exist "setup_binaries.py" (
    python setup_binaries.py
) else (
    echo [!] No se encontro el archivo 'setup_binaries.py' ni la carpeta 'scripts'.
    echo Asegurate de copiar la carpeta completa del proyecto y no solo el archivo .bat.
    pause
    exit /b
)
if not exist "bin\ffmpeg.exe" (
    echo.
    echo [!] ERROR: No se pudo completar la descarga de los componentes multimedia.
    echo Revisa tu conexion a internet y vuelve a abrir este instalador.
    pause
    exit /b
)
echo.
echo [OK] Componentes multimedia configurados correctamente.

:start_app
echo.
echo ==============================================
echo        Iniciando Concordia...
echo ==============================================
start pythonw discord_caserito.py
exit
