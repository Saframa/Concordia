# Concordia - Hoja de Ruta (To-Do List)

## 1. Imágenes de Perfil sobre UDP con Compresión y Redundancia
**Objetivo:** Permitir que los usuarios suban una foto de perfil y que esta viaje por el mismo canal rápido de UDP, pero mitigando la corrupción por pérdida de paquetes.
**Investigación y Solución:**
- **Compresión Automática:** El usuario podrá elegir cualquier foto de su PC sin importar el tamaño. El propio cliente de Python (usando la librería `Pillow`) se encargará de achicar la imagen (ej. 64x64 píxeles), recortarla en forma de cuadrado y bajarle la calidad para que el peso total sea de apenas unos pocos kilobytes.
- **Transmisión UDP con Redundancia:** Para evitar enviar la foto por TCP, el cliente dividirá la imagen comprimida en pequeños "trozos" (chunks) numerados y los enviará repetidas veces por UDP (redundancia cíclica o Forward Error Correction). El cliente receptor irá juntando los pedacitos; si se pierde alguno, simplemente lo completará en la siguiente vuelta. Una vez armados todos los pedazos, mostrará la foto.

## 2. Caché de Imágenes en el Servidor (Optimización de Red)
**Objetivo:** Evitar que un usuario tenga que re-enviar su foto de perfil constantemente, ahorrando ancho de banda.
**Investigación y Solución:**
- **Memoria del Servidor:** El servidor (`sfu_server.py`) mantendrá un diccionario en memoria RAM donde guardará la imagen comprimida de cada participante, asociada a su IP y Nombre de Usuario.
- **Lógica Inteligente:** 
  1. Cuando un usuario entra, manda su foto en pedacitos una sola vez. El servidor la guarda en su Caché.
  2. El servidor retransmite esta foto a los demás.
  3. Si el usuario se desconecta un rato y vuelve a entrar, el servidor detecta su IP/Nombre, recupera la foto de la memoria y la retransmite al resto de la sala de inmediato, sin pedirle a la aplicación del usuario que la vuelva a subir.
  4. Si entra alguien nuevo a la sala, el servidor le envía la Caché de todas las fotos actuales para que las cargue al instante.

## 3. Guardado Local de Datos de Usuario (Autologin)
**Objetivo:** Al abrir el programa, que el nombre de usuario y la foto de perfil ya estén cargados.
**Investigación y Solución:**
- Crear un pequeño archivo de configuración oculto en formato JSON (ej. `config.json` o `.perfil_concordia.json`) que se guarde en la misma carpeta del programa.
- Al abrir `VoiceClientApp`, el software leerá este archivo y rellenará automáticamente el campo "Nombre de usuario" en el Login, e inyectará la ruta de la foto guardada, logrando una experiencia de entrada mucho más fluida.

## 4. Control de Volumen Individual (Estilo Discord)
**Objetivo:** Poder nivelar el volumen si alguien se escucha muy fuerte o muy bajo.
**Investigación y Solución:**
- **Frontend (UI):** Añadiremos un evento de clic derecho (`<Button-3>`) sobre las tarjetas `ParticipantTile`. Al hacerlo, flotará un pequeño menú con un `CTkSlider` (Barra de deslizamiento).
- **Escala de Volumen:** El centro de la barra representará el 100% (factor `1.0`), hacia la izquierda bajará hasta el 0% (`0.0`), y hacia la derecha subirá al 200% (`2.0`).
- **Backend (AudioEngine):** Dentro de la función `playback_loop`, mantendremos un diccionario `self.user_volumes = {"Juan": 1.5, "Maria": 0.8}`. Antes de sumar la forma de onda de un usuario a la mezcla general, se la multiplicará por su volumen: `arr[i] = arr[i] * volume`. Esto regulará perfectamente el audio individual de cada persona.
