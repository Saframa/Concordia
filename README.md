# 🎙️ Concordia — Minimalist SFU Voice & Screen Share

**Concordia** es una aplicación de chat de voz y pantalla compartida ligera, minimalista y de ultra-baja latencia construida en Python con **CustomTkinter**, arquitectura de servidor **SFU (Selective Forwarding Unit) UDP**, supresión de ruido por IA (**RNNoise**) y streaming de pantalla a **60 FPS** con aceleración por hardware (**NVIDIA NVENC**).

---

## ✨ Características Principales

- **Arquitectura SFU UDP**: Servidor de reenvío selectivo con prevención estricta de eco (*anti-self-echo*), soporte para IPs efímeras y manejo resiliente de desconexiones en Windows (WSAECONNRESET).
- **Supresión de Ruido por IA (RNNoise)**: Filtro inteligente en tiempo real que elimina ruidos de fondo (teclado, ventiladores, ambiente) sin degradar la voz.
- **Pantalla Compartida a 60 FPS**:
  - Captura ultra fluida vía GDI.
  - Aceleración por GPU **NVIDIA NVENC** (`h264_nvenc`) con 0% de uso de CPU y sin caídas de FPS en juegos.
  - Fallback universal automático a **CPU (`libx264 ultrafast`)** para equipos AMD, Intel o laptops.
  - Supervisor watchdog en segundo plano para tolerancia a fallos.
- **Interfaz Moderna y Monocromática**:
  - Cuadrícula dinámica estilo Zoom con optimizador de aspecto y reflow automático.
  - Contenedores concéntricos *Double-Bezel* (`#080808`, `#111111`, `#161616`).
  - Indicadores de estado de micrófono y auriculares en vivo estilo Discord (`🎙 ✕` y `🎧 ✕`).
  - Isla flotante de controles (Silenciar, Ensordecer, Compartir Pantalla, Desconectar).
  - Soporte de avatares personalizados.
- **Instalación en 1 Clic**: Script `instalar_y_jugar.bat` que detecta Python, instala librerías y descarga automáticamente los binarios necesarios (FFmpeg, MediaMTX, mpv).

---

## 🚀 Inicio Rápido

### Opción 1: Lanzador Automático (Recomendado en Windows)
Haz doble clic en:
```bat
instalar_y_jugar.bat
```
El script verificará el entorno, instalará las dependencias necesarias y abrirá la aplicación.

### Opción 2: Manual por Consola

1. **Instalar dependencias:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Descargar binarios de streaming (FFmpeg, MediaMTX, mpv):**
   ```bash
   python setup_binaries.py
   ```

3. **Ejecutar la aplicación:**
   ```bash
   python discord_caserito.py
   ```

---

## 🖥️ Servidor Dedicado (Opcional)

Si deseas alojar un servidor SFU independiente en un VPS o en una máquina separada:

```bash
python sfu_server.py --host 0.0.0.0 --port 5000
```

---

## 🧪 Pruebas Automatizadas

El proyecto cuenta con una suite completa de pruebas unitarias, de integración de red y de UI:

```bash
# Pruebas de integración de red SFU (16 pruebas)
python test_sfu_flow.py

# Verificación de interfaz gráfica headless
python test_ui_grid.py --check

# Suite Pytest completa
python -m pytest tests/
```

---

## 📁 Estructura del Proyecto

```
├── discord_caserito.py       # Aplicación cliente GUI (CustomTkinter + AudioEngine)
├── sfu/
│   ├── __init__.py
│   └── server.py             # Servidor SFU UDP de reenvío selectivo
├── sfu_server.py             # Entrypoint CLI para servidor dedicado
├── setup_binaries.py         # Descargador automático de FFmpeg, MediaMTX y mpv
├── instalar_y_jugar.bat      # Instalador y ejecutor de 1 clic para Windows
├── test_sfu_flow.py          # Suite de pruebas de protocolo SFU
├── test_ui_grid.py           # Pruebas visuales y headless de la UI
├── tests/                    # Pruebas unitarias de streaming y estado
├── Concordia_Para_Amigos/    # Paquete portátil listo para distribuir
└── requirements.txt          # Dependencias de Python
```

---

## 📄 Licencia

Desarrollado para uso personal y comunitario. Código abierto bajo licencia MIT.
