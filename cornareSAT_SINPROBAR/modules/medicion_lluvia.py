from datetime import datetime
import logging
import math
from configuracion import CONFIGURACION
LOG = logging.getLogger("PythonLogger")
from modules.registros import guardarRegistro

def leerLluvia():
    from rain_rg15v2 import RG15Sensor
    sensor = RG15Sensor(port=CONFIGURACION['sensor_lluvia'], enable_xtb=False)
    try:
        if sensor.connect():
            datos = sensor.read_sensor()
            valor = datos['acc'] if datos and 'acc' in datos else -999
            if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
                raise ValueError('precipitacion debe ser un número finito')
            return valor
        return -999
    except (OSError, ValueError, TypeError) as error:
        LOG.warning('No se pudo leer el RG15: %s', error)
        return -999
    finally:
        sensor.disconnect()

def tarea_lluvia(detener, colas):
    # Conserva la espera inicial y la consulta por intervalo del rain.py original.
    while not detener.is_set():
        # Mismo alineamiento al reloj que sampling_time.delay(..., 'minutes').
        ahora = datetime.now()
        minutos = CONFIGURACION['intervalo_lluvia'] / 60
        total = ahora.hour * 60 + ahora.minute
        siguiente = ((total // minutos) + 1) * minutos
        espera = max(0, (siguiente - total) * 60 - ahora.second)
        if detener.wait(espera):
            break
        guardarRegistro(colas, 'local', CONFIGURACION['codigo'], {'precipitacion': leerLluvia()})


