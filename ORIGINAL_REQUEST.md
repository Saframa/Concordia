# Original User Request

## Initial Request — 2026-09-03T01:43:30Z

# Teamwork Project Prompt — Draft

> Status: Launched
> Goal: Craft prompt → get user approval → delegate to teamwork_preview
> Requested team: Full team

Develop a Python UDP server that acts as a Selective Forwarding Unit (SFU) for a real-time voice chat application. The server receives audio packets from clients and forwards them to all other connected clients, managing connections via explict connect/disconnect messages.

Working directory: c:/Users/safra/OneDrive/Escritorio/Proyectos Personales/Discord caserito
Integrity mode: demo

## Requirements

### R1. Servidor UDP
El servidor debe implementarse en Python usando las bibliotecas estándar `socket` y `threading`. Debe escuchar en un puerto UDP específico configurado a través de variables de entorno o constantes claras.

### R2. Protocolo de Conexión (Control)
Dado que UDP no orienta a conexión, el servidor debe procesar mensajes de control específicos (ej. tramas JSON o bytes predefinidos) para registrar explícitamente a un nuevo cliente cuando este se "conecta" y desregistrarlo cuando se "desconecta". Un cliente permanece activo hasta que envía explícitamente la desconexión.

### R3. Reenvío SFU (Audio)
Cuando el servidor recibe un paquete que no es de control (carga útil de audio) de un cliente registrado, debe reenviar (clonar) ese paquete de forma eficiente a las direcciones IP/puertos de todos los demás clientes registrados en ese momento. El servidor NO debe intentar decodificar, transcodificar ni mezclar el audio.

## Verification Resources
El usuario no cuenta con scripts de prueba actualmente; el equipo deberá construir el mecanismo de verificación desde cero.

## Acceptance Criteria

### Verificación Programática (Script de Pruebas)
- [ ] Existe un script de prueba automatizado (ej. `test_sfu_flow.py`) que levanta el servidor y simula al menos 3 clientes locales.
- [ ] La prueba verifica que al conectar al Cliente A y Cliente B, el servidor los registra correctamente.
- [ ] La prueba verifica que cuando el Cliente A envía un paquete de datos simulado, el Cliente B lo recibe intacto, pero el Cliente A no recibe un "eco" de su propio paquete.
- [ ] La prueba verifica que tras enviar un mensaje de "desconexión", el Cliente B ya no recibe los paquetes que envía el Cliente A o el Cliente C.
- [ ] Todas las pruebas programáticas pasan exitosamente sin necesidad de intervención manual o de inspeccionar visualmente la consola.

## Follow-up — 2026-09-03T17:17:00Z

# Teamwork Project Prompt — Draft

> Status: Launched
> Goal: Craft prompt → get user approval → delegate to teamwork_preview
> Requested team: [none — teamwork routes from the description]

Rediseñar la interfaz gráfica de `discord_caserito.py` para adoptar un estilo minimalista monocromático (blanco, negro, gris) usando la tipografía "Maven". La vista principal debe cambiar de una lista simple a una cuadrícula (grid) estilo Zoom, mostrando el nombre del usuario y un espacio/placeholder para su foto.

Working directory: c:/Users/safra/OneDrive/Escritorio/Proyectos Personales/Discord caserito
Integrity mode: development

## Requirements

### R1. Diseño Minimalista Monocromático con CustomTkinter
Migrar la interfaz gráfica actual (`discord_caserito.py`) para utilizar la librería `customtkinter`. El diseño debe aplicar colores blanco, negro y grises. Usar la tipografía "Maven" (o una fuente similar si no está instalada, asegurando que se vea moderna y elegante). Utilizar los lineamientos de diseño de la skill "high-end-visual-design".

### R2. Cuadrícula de Usuarios (Zoom-style)
Reemplazar la lista actual de usuarios por una cuadrícula dinámica (grid). Cada celda de la cuadrícula debe representar a un participante y contener un recuadro (placeholder) para su foto, junto a su nombre centrado abajo. La cuadrícula debe acomodarse al redimensionar la ventana.

### R3. Script de Prueba Visual de Interfaz
Crear un pequeño script temporal (ej. `test_ui_grid.py`) que inicie la ventana e inyecte 5 o 6 "usuarios fantasma" directamente en el array de la interfaz, para que el equipo pueda probar y refinar cómo se ve la cuadrícula llena, sin necesidad de conectarse al servidor UDP real.

### R4. Preservar la Lógica de Audio (SFU)
El rediseño debe ser puramente de Interfaz de Usuario (UI). No se debe alterar la arquitectura de red (UDP), los hilos de envío/recepción, ni la supresión de ruido por IA (RNNoise).

## Acceptance Criteria

### Verificación Programática y Visual
- [ ] `discord_caserito.py` se ejecuta sin errores y la ventana utiliza `customtkinter` con paleta monocromática.
- [ ] El script `test_ui_grid.py` levanta exitosamente la ventana mostrando una cuadrícula (grid) de al menos 5 usuarios falsos con placeholders.
- [ ] Los botones de "Ensordecer" y "Silenciar" mantienen su lógica funcional previa y cambian de estado visualmente.

