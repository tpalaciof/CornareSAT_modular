import logging
import math
import re
import time
import sampling_time
import interpretarTramasXbee
from interpretarTramasXbee import contextoNodo, CODIGOS_LOG_XBEE
from configuracion import CONFIGURACION
LOG = logging.getLogger("PythonLogger")

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


def agregarLecturaNivelXBee(acumulador_xbee, registro, colas):
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


def validarTramaLluvia(trama):
    if not isinstance(trama, dict) or set(trama) != {'precipitacion', 'codigo'}:
        raise ValueError('Se esperan únicamente precipitacion y codigo')
    valor = trama['precipitacion']
    if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
        raise ValueError('precipitacion debe ser un número finito')
    if not isinstance(trama['codigo'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', trama['codigo']):
        raise ValueError('codigo debe ser una cadena válida')
    # Se conservan los indicadores de error -999 y -999.9 del original.

def agregarLecturaLluviaXbee(registro, colas):
    trama = registro['datos']['trama_json']
    try:
        validarTramaLluvia(trama)
    except (ValueError, TypeError, OverflowError) as error:
        LOG.warning('Lluvia XBee descartada: %s', error, extra=contextoNodo(registro['origen']))
        return
    CODIGOS_LOG_XBEE[registro['origen']] = trama['codigo']
    colas['xbee'].put(registro)

def distribuirLectura(acumulador, registro, colas):
    trama = registro['datos']['trama_json']
    if isinstance(trama, dict) and 'precipitacion' in trama:
        agregarLecturaLluviaXbee(registro, colas)
    else:
        agregarLecturaNivelXBee(acumulador, registro, colas)

def tarea_xbee(detener, colas):
    # 'proximo': El plazo en el reloj monotónico para cerrar el intervalo. 
    # 'nodos': Los acumuladores de las mediciones de cada nodo.
    acumulador_xbee = {
        'proximo': sampling_time.iniciar_intervalo(CONFIGURACION['intervalo'], 'seconds'),
        'nodos': {}
    }
    estado = {'puerto': None, 'proximo_intento': 0.0}
    try:
        while not detener.is_set(): # Mientras no se solicite detener la tarea
            registros = interpretarTramasXbee.recibir(CONFIGURACION, estado)

            """
            registros = [
                {
                    'tipo': 'xbee',
                    'origen': '0013A200422AB555',
                    'ts': 1700000000123,
                    'datos': {
                        'trama_json': {'nivel': 500, 'codigo': '667'}
                    }
                },
                {
                    'tipo': 'identificacion',
                    'origen': '0013A200422AB555',
                    'datos': {
                        'mac': '0013A200422AB555',
                        'ni': 'Nodo_667'
                    }
                }
            ]
            """

            cerrarIntervaloXBee(acumulador_xbee, colas)

            """
            Envía a colas['xbee'] y reinicia las variables frecuencia, moda y resitro para cada dupla (mac, codigo) : 
            {
                'tipo': 'xbee',
                'origen': '0013A20012345678',
                'ts': 1700000060000,  # Marca de tiempo de cierre de ejemplo.
                'datos': {
                    'trama_json': {'nivel': 500, 'codigo': '667'}
                }
            }
            """
            for registro in registros:

                # la cola de identificación recibe el diccionario completo con la MAC y el NI. 
                # Si el NI es Nodo_667, ese dato queda disponible para la tarea de salida desde ese momento.
                if registro['tipo'] == 'identificacion':  # es decir, si recibió una respuesta 0x97 conteniendo el NI
                    colas['identificacion'].put(registro)
                
                    """
                    Envia a las colas['identificacion']: 

                    {
                        'tipo': 'identificacion',
                        'origen': '0013A200422AB555',
                        'datos': {
                            'mac': '0013A200422AB555',
                            'ni': 'Nodo_667'
                        }
                    }
                    """
                # Si el registro trae una medición, se ejecuta:
                else:
                    distribuirLectura(acumulador_xbee, registro, colas)

                    # Ejemplo del estado al terminar agregarLecturaXBee().
                    # acumulador_xbee = {
                    #     'proximo': 160.0,  # Plazo de cierre de ejemplo.
                    #     'nodos': {
                    #         ('0013A20012345678', '667'): {
                    #             'frecuencias': {500: 1},
                    #             'moda': 500,
                    #             'registro': {
                    #                 'tipo': 'xbee',
                    #                 'origen': '0013A20012345678',
                    #                 'ts': 1700000000123,
                    #                 'datos': {
                    #                     'trama_json': {
                    #                         'nivel': 500,
                    #                         'codigo': '667'
                    #                     }
                    #                 }
                    #             }
                    #         }
                    #     }
                    # }

            if estado['puerto'] is None:
                detener.wait(0.05)
    finally:
        interpretarTramasXbee.cerrarPuerto(estado)


