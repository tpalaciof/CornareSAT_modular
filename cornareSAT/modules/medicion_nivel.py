from datetime import datetime
import logging
import math
import os
import re
import time
import sampling_time
from interpretarTramasXbee import contextoNodo, CODIGOS_LOG_XBEE
from configuracion import CONFIGURACION
LOG = logging.getLogger("PythonLogger")
import maxbotix
import adc
from moduls.registros import guardarRegistro

def abrir_puerto(ruta, baudios):
    import serial
    opciones = dict(port=ruta, baudrate=baudios, bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                    timeout=0.1, write_timeout=0.25)
    if os.name == "posix":
        opciones["exclusive"] = True
    return serial.Serial(**opciones)


def cerrar_puerto(puerto):
    if puerto is not None:
        try:
            puerto.close()
        except OSError:
            LOG.warning("No se pudo cerrar un puerto", exc_info=True)


def valores_distancia(distancia, estado):
    valores = {"estado": estado, "medicion_valida": estado == 0,
               "distancia_cruda_mm": distancia}
    if estado == 0:
        valores["distancia_mm"] = distancia
        valores["distancia_m"] = distancia / 1000.0
        valores["bajo_rango"] = distancia < 500
    valores["descripcion_estado"] = (
        "medicion recibida" if estado == 0 else
        "sin objetivo detectado" if estado == 1 else "sin trama valida reciente"
    )
    return valores


def tarea_sensor(detener, colas):
    if not CONFIGURACION['H_LEVEL']:
        return tarea_sensor_analogico(detener, colas)
    puerto = None
    bufferSensor = bytearray()
    huboBytesIntervalo = False
    ultima = None
    ultima_valida = None
    frecuencias = {}
    moda = None
    proximo_intento = 0.0
    proximo_envio = sampling_time.iniciar_intervalo(CONFIGURACION['intervalo'], 'seconds')
    try:
        while not detener.is_set():
            ahora = time.monotonic()
            if puerto is None and ahora >= proximo_intento:
                try:
                    puerto = abrir_puerto(CONFIGURACION['sensor'], CONFIGURACION['baudios_sensor'])
                    bufferSensor = bytearray()
                    LOG.info("MB7388 conectado: %s", CONFIGURACION['sensor'])
                except OSError as error:
                    LOG.warning("Sensor no disponible: %s. Se reintentará.", error)
                    proximo_intento = ahora + CONFIGURACION['reintento_puerto_s']
            datos = b''
            if puerto is not None:
                try:
                    datos = puerto.read(min(4096, puerto.in_waiting or 1))
                except OSError as error:
                    LOG.warning("Se perdió el sensor: %s", error)
                    cerrar_puerto(puerto)
                    puerto = None
                    ultima = None
                    proximo_intento = time.monotonic() + CONFIGURACION['reintento_puerto_s']
            else:
                detener.wait(0.05)

            ahora = time.monotonic()
            if ahora >= proximo_envio:
                # La moda representa todo el intervalo, no solo una lectura reciente.
                distancia = moda if moda is not None else -1
                estado = 0 if moda is not None else (1 if ultima is not None and ultima[0] == 9999 else 2)
                valores = valores_distancia(distancia, estado)
                valores['nivel'] = maxbotix.a_centimetros(distancia) if estado == 0 else CONFIGURACION['valor_error_nivel']
                valores["sensor_conectado"] = puerto is not None
                if ultima_valida is not None:
                    valores["lectura_sensor_ms"] = ultima_valida[2]
                    valores["edad_lectura_s"] = round(ahora - ultima_valida[1], 3)
                if moda is not None or huboBytesIntervalo:
                    guardarRegistro(colas, "local", "raspberry", valores)
                    if moda is None:
                        LOG.warning("Sensor local: llegaron datos, pero no hubo distancias válidas en el intervalo.")
                else:
                    LOG.warning("No se están recibiendo datos del sensor local durante el intervalo; no se publica una medición.")
                huboBytesIntervalo = False
                LOG.info("LOCAL moda del intervalo: estado=%d distancia=%s mm", estado, distancia)
                frecuencias.clear()
                moda = None
                ultima = None
                ultima_valida = None
                # Conserva el calendario sin inventar lecturas para intervalos
                # que pudieran haberse saltado por una pausa del sistema.
                proximo_envio = sampling_time.avanzar_intervalo(
                    proximo_envio, ahora, CONFIGURACION['intervalo'], 'seconds')

            huboBytesIntervalo = huboBytesIntervalo or bool(datos)
            # Las tramas recibidas al cerrar un intervalo pertenecen al siguiente.
            for distancia in maxbotix.decodificar_tramas(datos, bufferSensor):
                ultima = (distancia, time.monotonic(), time.time_ns() // 1_000_000)
                if 0 <= distancia <= CONFIGURACION['distancia_maxima_mm']:
                    ultima_valida = ultima
                    frecuencias[distancia] = frecuencias.get(distancia, 0) + 1
                    # En caso de empate se elige la más reciente de las empatadas.
                    if moda is None or frecuencias[distancia] >= frecuencias[moda]:
                        moda = distancia
    finally:
        cerrar_puerto(puerto)


def tarea_sensor_analogico(detener, colas):
    i2c = entrada = None
    frecuencias = {}
    moda = None
    proximo_intento = 0.0
    proximo_envio = sampling_time.iniciar_intervalo(CONFIGURACION['intervalo'], 'seconds')
    try:
        while not detener.is_set():
            ahora = time.monotonic()
            if ahora >= proximo_envio:
                valores = {'estado': 0 if moda is not None else 2,
                           'nivel': moda if moda is not None else CONFIGURACION['valor_error_nivel'],
                           'sensor_conectado': entrada is not None}
                if moda is not None:
                    guardarRegistro(colas, 'local', 'raspberry', valores)
                else:
                    LOG.warning("No se están recibiendo lecturas válidas del sensor analógico durante el intervalo; no se publica una medición.")
                LOG.info('LOCAL moda del intervalo analógico: nivel=%s', valores['nivel'])
                frecuencias.clear()
                moda = None
                proximo_envio = sampling_time.avanzar_intervalo(
                    proximo_envio, ahora, CONFIGURACION['intervalo'], 'seconds')
            if entrada is None and ahora >= proximo_intento:
                try:
                    # Definiciones de pines asociados al adc
                    # El parametro corresponde al canal del ADC
                    i2c, entrada = adc.abrir_canal(canal=0, ganancia=1)
                    LOG.info('Sensor analógico conectado: ADS1015, canal 0, ganancia 1')
                except (OSError, RuntimeError, ValueError, ImportError) as error:
                    LOG.warning('Sensor analógico no disponible: %s. Se reintentará.', error)
                    proximo_intento = ahora + CONFIGURACION['reintento_puerto_s']
            if entrada is not None:
                try:
                    nivel = adc.leer_nivel(entrada, CONFIGURACION['calibracion'])
                    frecuencias[nivel] = frecuencias.get(nivel, 0) + 1
                    if moda is None or frecuencias[nivel] >= frecuencias[moda]:
                        moda = nivel
                except (OSError, RuntimeError, ValueError) as error:
                    LOG.warning('Lectura analógica descartada: %s', error)
                    try:
                        i2c.deinit()
                    except OSError:
                        LOG.warning('No se pudo cerrar el bus I2C', exc_info=True)
                    i2c = entrada = None
                    proximo_intento = ahora + CONFIGURACION['reintento_puerto_s']
            detener.wait(min(CONFIGURACION['periodo_lectura_analogica_s'],
                             max(0.0, proximo_envio - time.monotonic())))
    finally:
        if i2c is not None:
            i2c.deinit()


# ********************* MEDICIONES DE LOS NODOS ******************* #


def validarTramaNivelNodo(trama):
    """El main de la ESP32 envía únicamente nivel y codigo."""
    if not isinstance(trama, dict) or set(trama) != {'nivel', 'codigo'}:
        raise ValueError('Se esperan únicamente nivel y codigo')
    nivel = trama['nivel']
    if (isinstance(nivel, bool) or not isinstance(nivel, (int, float))
            or not math.isfinite(nivel)):
        raise ValueError('nivel debe ser un número finito')
    codigo = trama['codigo']
    if not isinstance(codigo, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", codigo):
        raise ValueError('codigo debe ser una cadena válida')


def agregarLecturaXBee(acumulador_xbee, registro, colas):
    """Un acumulador por MAC/código; solo emite intervalos completos."""
    cerrarIntervaloXBee(acumulador_xbee, colas)
    datos = registro['datos']
    trama = datos['trama_json'] # {'nivel': 500, 'codigo': '667'}
    try:
        validarTramaNivelNodo(trama)    # comprueba que el diccionario tenga esas dos claves, que el nivel sea un número finito y que el código tenga el formato esperado.

    except (ValueError, TypeError, OverflowError) as error:
        LOG.warning('JSON del nodo descartado: %s', error, extra=contextoNodo(registro['origen']))
        return

    CODIGOS_LOG_XBEE[registro['origen']] = trama['codigo']   # registro['origen'] contiene la MAC, trama['codigo'] contiene el código de la estación que venía en el JSON. Por lo tanto, asocia la MAC al código de la estación:  CODIGOS_LOG_XBEE["0013A20012345678"] = "667"
    LOG.info('XBEE recibido: MAC=%s JSON=%s', registro['origen'], trama, extra=contextoNodo(registro['origen']))

    clave = (registro['origen'], trama['codigo'])  # ('0013A20012345678', '667')

    # Si la clave es nueva, setdefault() guarda el diccionario inicial en
    # acumulador_xbee['nodos'][clave]. Si ya existe, recupera el que estaba guardado.
    # En ambos casos, nodo apunta a ese mismo diccionario.
    nodo = acumulador_xbee['nodos'].setdefault(
        clave, {'frecuencias': {}, 'moda': None, 'registro': None}
    )

    # Ejemplo justo después de setdefault(), si esta es la primera entrada.
    #
    # nodo = {
    #     'frecuencias': {},
    #     'moda': None,
    #     'registro': None
    # }
    #
    # acumulador_xbee = {
    #     'proximo': 160.0,  # Plazo de cierre de ejemplo.
    #     'nodos': {
    #         ('0013A20012345678', '667'): {  # Este diccionario es nodo.
    #             'frecuencias': {},
    #             'moda': None,
    #             'registro': None
    #         }
    #     }
    # }

    # Guarda el registro completo de la medición en el diccionario del nodo.
    # Esta línea equivale a acumulador_xbee['nodos'][clave]['registro'] = registro.

    nodo['registro'] = registro

    # Ejemplo justo después de guardar el registro, antes de contar el nivel.
    #
    # nodo = {
    #     'frecuencias': {},
    #     'moda': None,
    #     'registro': {
    #         'tipo': 'xbee',
    #         'origen': '0013A20012345678',
    #         'ts': 1700000000123,
    #         'datos': {
    #             'trama_json': {'nivel': 500, 'codigo': '667'}
    #         }
    #     }
    # }
    #
    # acumulador_xbee = {
    #     'proximo': 160.0,  # Plazo de cierre de ejemplo.
    #     'nodos': {
    #         ('0013A20012345678', '667'): {  # El mismo diccionario actualizado.
    #             'frecuencias': {},
    #             'moda': None,
    #             'registro': {
    #                 'tipo': 'xbee',
    #                 'origen': '0013A20012345678',
    #                 'ts': 1700000000123,
    #                 'datos': {
    #                     'trama_json': {'nivel': 500, 'codigo': '667'}
    #                 }
    #             }
    #         }
    #     }
    # }

    nivel = trama['nivel']


    # Misma validez numérica que el sensor TTL: 0..9998; excluye -888.8 y 9999.
    # Si llega -888.8 o 9999, return termina esa llamada a agregarLecturaXBee(). 
    # El registro ya quedó guardado en nodo['registro'], pero ese nivel queda por fuera del conteo.
    if not 0 <= nivel <= CONFIGURACION['distancia_maxima_mm']:
        return


    frecuencias = nodo['frecuencias']
    frecuencias[nivel] = frecuencias.get(nivel, 0) + 1  # 'frecuencias': {500: 1}

    # Establece la moda según las frecuencias de llega del nivel
    if nodo['moda'] is None or frecuencias[nivel] >= frecuencias[nodo['moda']]:
        nodo['moda'] = nivel


def cerrarIntervaloXBee(acumulador_xbee, colas):
    ahora = time.monotonic()

    # Comprueba si ya llegó el momento de cerrar
    if ahora < acumulador_xbee['proximo']:
        return
    
    # Saca la MAC, el código y el diccionario del nodo
    for (mac, codigo), nodo in acumulador_xbee['nodos'].items():
        registro = nodo['registro']

        """
        mac = '0013A20012345678'
        codigo = '667'

        nodo = {
            'frecuencias': {500: 2, 502: 1},
            'moda': 500,
            'registro': {
                'tipo': 'xbee',
                'origen': '0013A20012345678',
                'ts': 1700000030123,
                'datos': {
                    'trama_json': {'nivel': 502, 'codigo': '667'}
                }
            }
        }
        """
        if registro is None:
            LOG.warning("No se recibieron mediciones del nodo XBee en el intervalo.", extra=contextoNodo(mac, codigo))
            continue

        nivel = nodo['moda'] if nodo['moda'] is not None else CONFIGURACION['valor_error_nivel']

        if nodo['moda'] is None:
            LOG.warning("Se recibieron mediciones del nodo XBee, pero ninguna válida en el intervalo.", extra=contextoNodo(mac, codigo))

        datos = {'trama_json': {'nivel': nivel, 'codigo': codigo}}

        # Fecha de cierre, igual que para la moda del sensor local.
        colas['xbee'].put(dict(registro, ts=time.time_ns() // 1_000_000, datos=datos))

        """
        Esto es lo que entra en colas['xbee']: 
        {
            'tipo': 'xbee',
            'origen': '0013A20012345678',
            'ts': 1700000060000,  # Marca de tiempo de cierre de ejemplo.
            'datos': {
                'trama_json': {'nivel': 500, 'codigo': '667'}
            }
        }
        """
        # Reinicia estas variables para cada (mac, codigo) que se encuentre en acumulador_xbee
        nodo.update(frecuencias={}, moda=None, registro=None)

    # Se calcula el próximo plazo
    acumulador_xbee['proximo'] = sampling_time.avanzar_intervalo(
        acumulador_xbee['proximo'], ahora, CONFIGURACION['intervalo'], 'seconds')


def formatearTramaNivel(registro):
    """Las mediciones conservan las tres claves que utiliza nivel.py."""
    datos = registro['datos']
    if registro['tipo'] == 'xbee':
        nivel = datos['trama_json']['nivel']
        codigo = datos['trama_json']['codigo']
    else:
        nivel = datos['nivel']
        codigo = CONFIGURACION['codigo']
    # Fecha de recepción: misma referencia horaria que el sensor local.
    # Los respaldos ya guardados se reenvían conservando su fecha registrada.
    fecha = datetime.fromtimestamp(registro['ts'] / 1000.0, CONFIGURACION['zona_horaria'])
    return {'nivel': nivel, 'fecha': fecha.strftime('%Y-%m-%d %H:%M'), 'codigo': codigo}


