import logging
import sampling_time
import interpretarTramasXbee
from interpretarTramasXbee import contextoNodo, CODIGOS_LOG_XBEE
from configuracion import CONFIGURACION
LOG = logging.getLogger("PythonLogger")
from modules.medicion_nivel import agregarLecturaXBee, cerrarIntervaloXBee
from modules.medicion_lluvia import validarTramaLluvia

def distribuirLectura(acumulador, registro, colas):
    trama = registro['datos']['trama_json']
    if isinstance(trama, dict) and 'precipitacion' in trama:
        try:
            validarTramaLluvia(trama)
        except (ValueError, TypeError, OverflowError) as error:
            LOG.warning('Lluvia XBee descartada: %s', error, extra=contextoNodo(registro['origen']))
            return
        CODIGOS_LOG_XBEE[registro['origen']] = trama['codigo']
        colas['xbee'].put(registro)
    else:
        agregarLecturaXBee(acumulador, registro, colas)

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


