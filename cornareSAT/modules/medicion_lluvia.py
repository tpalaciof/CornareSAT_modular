from datetime import datetime
import logging
import math
import re
from configuracion import CONFIGURACION
LOG = logging.getLogger("PythonLogger")
from modules.registros import guardarRegistro

def validarTramaLluvia(trama):
    if not isinstance(trama, dict) or set(trama) != {'precipitacion', 'codigo'}:
        raise ValueError('Se esperan únicamente precipitacion y codigo')
    valor = trama['precipitacion']
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise ValueError('precipitacion debe ser un número finito')
    if not isinstance(trama['codigo'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', trama['codigo']):
        raise ValueError('codigo debe ser una cadena válida')
    # Se conservan los indicadores de error -999 y -999.9 del original.

def leerLluvia():
    from rain_rg15v2 import RG15Sensor
    sensor = RG15Sensor(port=CONFIGURACION['sensor_lluvia'], continuous_mode=False,
                        enable_xtb=False, auto_reset_hours=24)
    try:
        if sensor.connect():
            datos = sensor.read_sensor()
            valor = datos['acc'] if datos and 'acc' in datos else -999
            validarTramaLluvia({'precipitacion': valor, 'codigo': CONFIGURACION['codigo']})
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
