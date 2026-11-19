import serial
import time
from typing import Tuple, Optional, Dict
import logging
import re

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class RG15Sensor:
    def __init__(
        self,
        port: str = '/dev/rain',
        baud_rate: int = 9600,
        timeout: float = 1.0,
        max_retries: int = 3,
        retry_delay: float = 0.5,
        enable_xtb: bool = False,
    ):
        """
        Inicializa el sensor RG-15 con configuraciones extendidas.
        
        Args:
            port: Puerto serial del dispositivo
            baud_rate: Velocidad de comunicación
            timeout: Tiempo de espera para lectura
            max_retries: Número máximo de intentos de lectura
            retry_delay: Tiempo entre reintentos
            enable_xtb: Habilita la lectura de External Tipping Bucket
        """
        self.port = port
        self.baud_rate = baud_rate
        self.timeout = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.enable_xtb = enable_xtb
        self.ser = None

    def connect(self) -> bool:
        """Establece la conexión con el sensor y configura el modo de operación."""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baud_rate,
                timeout=self.timeout,
                write_timeout=self.timeout
            )
            
            # Espera a que el dispositivo se inicialice
            time.sleep(2)
            
            # Configuración inicial
            self.flush_buffer()
            
            # Habilitar/deshabilitar XTB
            if self.enable_xtb:
                self._send_command('X')
                logging.info("XTB habilitado")
            else:
                self._send_command('Y')
                logging.info("XTB deshabilitado")
            
            self._send_command('P')
            logging.info("Modo polling activado")
            
            logging.info(f"Conexión establecida en {self.port}")
            return True
            
        except serial.SerialException as e:
            logging.error(f"Error al conectar: {e}")
            return False


    def _send_command(self, cmd: str) -> None:
        """Envía un comando al sensor."""
        if self.ser and self.ser.is_open:
            self.ser.write(f"{cmd}\n".encode())
            time.sleep(0.5)  # Pequeña pausa para procesamiento

    def _read_line(self) -> str:
        """Lee una línea completa del puerto serial."""
        buffer = ""
        limite = time.monotonic() + self.timeout
        while time.monotonic() < limite:
            if self.ser.in_waiting:
                char = self.ser.read().decode()
                if char == '\n':
                    return buffer
                buffer += char
            elif not buffer:
                time.sleep(0.2)  # Espera si no hay datos
            else:
                return buffer  # Retorna buffer si hay timeout

        return buffer

    def parse_response(self, response: str) -> Dict:
        data = {}
        try:
            # Eliminar 'iph' del final y dividir por líneas
            lines = response.rstrip().strip("mmph,").split('\n')
            cleaned_line = re.sub(r"(mmph|mm)", "", lines[0])
            #print(cleaned_line)
            # Verificar que haya al menos una línea
            if not lines:
                logging.warning("Respuesta vacía o malformada")
                return {}

            # Procesar la primera línea (datos principales)
            main_data = cleaned_line.split(",")
            if len(main_data) >= 4:
                data['acc'] = self._convert_to_float(main_data[0].replace("Acc ", ""))
                data['event'] = self._convert_to_float(main_data[1].replace(" EventAcc ", ""))
                data['total'] = self._convert_to_float(main_data[2].replace(" TotalAcc ", ""))
                #print(main_data[3].replace(" RInt ", ""))
                data['rint'] = self._convert_to_float(main_data[3].replace(" RInt ", ""))
            else:
                logging.warning(f"Datos principales incompletos: {lines[0]}")

            # Procesar la segunda línea si existe (datos XTB)
            if len(lines) > 1 and self.enable_xtb:
                
                #print(xtb_data)
                if len(main_data) > 4:
                    
                    data['xtb_tips'] = self._convert_to_int(main_data[4].replace(" XTBTips: ", ""))
                    data['xtb_event'] = self._convert_to_float(main_data[5].replace(" XTBEventAcc:  ", "").replace(" mm", ""))
                    data['xtb_total'] = self._convert_to_float(main_data[6].replace(" XTBTotalAcc:  ", "").replace(" mm", ""))
                    data['xtb_int'] = self._convert_to_float(main_data[7].replace(" XTBInt:  ", "").replace(" mmph", ""))
                else:
                    logging.warning(f"Datos XTB incompletos: {main_data[:4]}")
                
            return data
        except (ValueError, IndexError) as e:
            logging.error(f"Error al parsear respuesta: {e}")
            return {}

    def _convert_to_float(self, value: str) -> float:
        """Convierte una cadena a flotante, manejando casos con caracteres no numéricos."""
        try:
            # Limpiar la cadena eliminando espacios y caracteres no numéricos
            cleaned_value = value.strip().replace(',', '')  # Elimina comas, si es necesario
            if cleaned_value == '':
                return -999.9  # Si la cadena está vacía, retornar 0.0
            return float(cleaned_value)
        except ValueError:
            logging.warning(f"No se pudo convertir el valor a flotante: {value}")
            return -999.9  # O devolver un valor predeterminado como 0.0

    def _convert_to_int(self, value: str) -> int:
        """Convierte una cadena a entero."""
        try:
            return int(value.strip().replace(',', ''))
        except ValueError:
            logging.warning(f"No se pudo convertir el valor a entero: {value}")
            return 0

    def read_sensor(self) -> Optional[Dict]:
        """
        Lee los datos del sensor con reintentos y manejo de errores.
        
        Returns:
            Dictionary con todos los valores o None si hay error
        """
        if not self.ser or not self.ser.is_open:
            if not self.connect():
                return None

        for attempt in range(self.max_retries):
            try:
                self.flush_buffer()
                self._send_command('R')
                
                # Espera a que haya datos disponibles
                start_time = time.time()
                while self.ser.in_waiting == 0:
                    if time.time() - start_time > self.timeout:
                        raise TimeoutError("No se recibieron datos")
                    time.sleep(0.01)

                # Lee la respuesta usando el nuevo método
                response = self._read_line()
                #print(response)
                
                if not response:
                    raise ValueError("Respuesta vacía del sensor")

                data = self.parse_response(response)
                if data:
                    logging.info(f"Lectura exitosa: {data}")
                    return data

            except (serial.SerialException, ValueError, TimeoutError) as e:
                logging.warning(f"Intento {attempt + 1}/{self.max_retries} fallido: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay)
                    self.flush_buffer()
                else:
                    logging.error("Se agotaron los reintentos de lectura")
                    return None

    def flush_buffer(self):
        """Limpia los buffers de entrada y salida."""
        if self.ser:
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()

    def disconnect(self):
        """Cierra la conexión con el sensor."""
        if self.ser and self.ser.is_open:
            self.ser.close()
            logging.info("Conexión cerrada")

    def __enter__(self):
        """Soporte para uso con 'with'."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Cierra la conexión al salir del contexto."""
        self.disconnect()

# Ejemplo de uso

if __name__ == "__main__":

    # Inicialización del sensor sin modo continuo
    sensor = RG15Sensor(enable_xtb=False)

    # Conectar el sensor manualmente
    if sensor.connect():
        try:
            # Leer datos del sensor en un bucle (por ejemplo, cada 10 segundos)
            for _ in range(5):  # Realiza 5 lecturas
                data = sensor.read_sensor()
                if data:
                    print(f"Datos recibidos: {data}")
                else:
                    print("Error al leer datos del sensor o datos incompletos")
                
                time.sleep(10)  # Espera de 10 segundos entre lecturas

        finally:
            # Asegurarse de desconectar el sensor al terminar
            sensor.disconnect()
    else:
        print("No se pudo conectar al sensor.")
       
