import smbus2
import time

# Dirección I2C del sensor (por defecto 0x70 en modo 7-bit)
I2C_ADDRESS = 0x70

# Comandos del sensor según el datasheet
CMD_TAKE_READING = 0x51  # Comando para iniciar una medición
CMD_REPORT_READING = 0xE1  # Dirección de lectura para obtener el rango medido

# Rango válido del sensor (según datasheet)
MIN_DISTANCE = 20  # cm
MAX_DISTANCE = 765  # cm
MAX_RETRIES = 3  # Número máximo de intentos para obtener una lectura válida

def take_range_reading(bus, address):
    """
    Envía el comando para que el sensor realice una medición.
    :param bus: Instancia del bus I2C.
    :param address: Dirección I2C del sensor.
    """
    try:
        bus.write_byte(address, CMD_TAKE_READING)
    except Exception as e:
        print(f"Error al iniciar la medición: {e}")

def get_range_reading(bus, address):
    """
    Intenta leer los dos bytes que representan la distancia medida por el sensor con reintentos.
    :param bus: Instancia del bus I2C.
    :param address: Dirección I2C del sensor.
    :return: Distancia medida en centímetros o None si no se logra obtener una lectura válida.
    """
    for attempt in range(MAX_RETRIES):
        try:
            # Iniciar una medición
            take_range_reading(bus, address)
            time.sleep(0.15)  # Esperar para completar la medición

            # Leer dos bytes de datos del sensor
            data = bus.read_i2c_block_data(address, CMD_REPORT_READING, 2)
            # Combinar los bytes en un entero
            distance = (data[0] << 8) | data[1]

            # Validar que la distancia está dentro del rango especificado
            if MIN_DISTANCE <= distance <= MAX_DISTANCE:
                return distance
                continue
        except Exception as e:
            print(f"Error al leer la distancia (Intento {attempt + 1}/{MAX_RETRIES}): {e}")
            time.sleep(0.2)

    print("No se logró obtener una lectura válida tras múltiples intentos.")
    return None

def main():
    # Inicializar el bus I2C
    bus = smbus2.SMBus(1)  # En Raspberry Pi, I2C1 está en /dev/i2c-1

    print("Iniciando lecturas del sensor MaxBotix MB7040...")

    try:
        
        # Obtener la distancia medida
        distance = get_range_reading(bus, I2C_ADDRESS)
        if distance is not None:
            print(f"Distancia medida: {distance} cm")
            return distance
        else:
            print("Lectura descartada por ser inválida.")
            distance = 888.8
            return distance
        # Pausar antes de la próxima medición
        time.sleep(1)  # Tiempo total entre lecturas
    except Exception as e:
        print("\nDeteniendo la lectura del sensor.")
    finally:
        # Cerrar el bus I2C
        bus.close()

#distancia = main()
#print(distancia)
