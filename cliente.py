import socket
import threading
import json
import sys
import argparse

try:
    import pyaudio
except ImportError:
    print("Error: PyAudio no está instalado.")
    print("Por favor instálalo ejecutando: pip install pyaudio")
    sys.exit(1)

# Configuraciones de Audio (Deben ser iguales para todos los que se conecten)
CHUNK = 1024
FORMAT = pyaudio.paInt16
CHANNELS = 1
RATE = 44100

class VoiceClient:
    def __init__(self, server_ip, server_port):
        self.server_ip = server_ip
        self.server_port = server_port
        self.server_addr = (server_ip, server_port)
        
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # Timeout para que los hilos no se queden bloqueados por siempre al salir
        self.sock.settimeout(1.0) 
        
        self.p = pyaudio.PyAudio()
        self.stream_in = self.p.open(format=FORMAT, channels=CHANNELS, rate=RATE, input=True, frames_per_buffer=CHUNK)
        self.stream_out = self.p.open(format=FORMAT, channels=CHANNELS, rate=RATE, output=True, frames_per_buffer=CHUNK)
        
        self.running = True

    def connect(self):
        """Envía el mensaje de control JSON para registrarse en el servidor."""
        msg = json.dumps({"action": "connect"}).encode('utf-8')
        self.sock.sendto(msg, self.server_addr)
        print(f"Conectado al servidor en {self.server_ip}:{self.server_port}")

    def disconnect(self):
        """Envía el mensaje de control JSON para desregistrarse del servidor."""
        msg = json.dumps({"action": "disconnect"}).encode('utf-8')
        try:
            self.sock.sendto(msg, self.server_addr)
        except:
            pass
        print("\nDesconectado del servidor.")

    def receive_audio(self):
        """Escucha paquetes UDP del servidor y los reproduce."""
        while self.running:
            try:
                data, _ = self.sock.recvfrom(65535)
                # Si llega un paquete JSON (mensajes de control), lo ignoramos
                if len(data) >= 10 and data.startswith(b'{') and data.endswith(b'}'):
                    continue
                # Escribimos el audio directo a los altavoces/auriculares
                self.stream_out.write(data)
            except socket.timeout:
                continue
            except ConnectionResetError:
                continue
            except Exception as e:
                if self.running:
                    print(f"Error recibiendo audio: {e}")
                break

    def send_audio(self):
        """Captura audio del micrófono y lo envía al servidor UDP."""
        while self.running:
            try:
                # Leemos del micrófono
                data = self.stream_in.read(CHUNK, exception_on_overflow=False)
                # Lo enviamos tal cual (raw) al servidor
                self.sock.sendto(data, self.server_addr)
            except Exception as e:
                if self.running:
                    print(f"Error enviando audio: {e}")
                break

    def start(self):
        self.connect()
        
        # Iniciamos hilos para enviar y recibir audio al mismo tiempo
        t_recv = threading.Thread(target=self.receive_audio, daemon=True)
        t_send = threading.Thread(target=self.send_audio, daemon=True)
        
        t_recv.start()
        t_send.start()
        
        try:
            print("Micrófono abierto y escuchando... Presiona Ctrl+C para salir.")
            while True:
                # Bucle principal esperando la interrupción
                import time
                time.sleep(0.5)
        except KeyboardInterrupt:
            self.running = False
            self.disconnect()
            
            # Limpieza limpia de PyAudio
            self.stream_in.stop_stream()
            self.stream_in.close()
            self.stream_out.stop_stream()
            self.stream_out.close()
            self.p.terminate()
            self.sock.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cliente de Voz UDP - Discord Caserito")
    parser.add_argument("ip", help="IP del Servidor (Tu IP Pública para amigos, o 127.0.0.1 para probar local)")
    parser.add_argument("--port", type=int, default=5000, help="Puerto del Servidor (por defecto 5000)")
    
    args = parser.parse_args()
    
    client = VoiceClient(args.ip, args.port)
    client.start()
