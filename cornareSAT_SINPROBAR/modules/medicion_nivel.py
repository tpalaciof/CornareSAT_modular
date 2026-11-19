import logging
import time
import sampling_time
from configuracion import CONFIGURACION
LOG = logging.getLogger("PythonLogger")
import maxbotix
import adc
from modules.registros import guardarRegistro

def tarea_sensor(detener, colas):
    if not CONFIGURACION['H_LEVEL']:
        return tarea_sensor_analogico(detener, colas)
    puerto = None
    bufferSensor = bytearray()
    huboBytesIntervalo = False
    ultima_distancia = None
    frecuencias = {}
    moda = None
    proximo_intento = 0.0
    proximo_envio = sampling_time.iniciar_intervalo(CONFIGURACION['intervalo'], 'seconds')
    try:
        while not detener.is_set():
            ahora = time.monotonic()
            if puerto is None and ahora >= proximo_intento:
                try:
                    puerto = maxbotix.abrir_puerto(CONFIGURACION['sensor'], CONFIGURACION['baudios_sensor'])
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
                    maxbotix.cerrar_puerto(puerto)
                    puerto = None
                    ultima_distancia = None
                    proximo_intento = time.monotonic() + CONFIGURACION['reintento_puerto_s']
            else:
                detener.wait(0.05)

            ahora = time.monotonic()
            if ahora >= proximo_envio:
                # La moda representa todo el intervalo, no solo una lectura reciente.
                distancia = moda if moda is not None else -1
                estado = 0 if moda is not None else (1 if ultima_distancia == 9999 else 2)
                if moda is not None or huboBytesIntervalo:
                    nivel = (maxbotix.a_centimetros(distancia) if estado == 0
                             else CONFIGURACION['valor_error_nivel'])
                    guardarRegistro(colas, "local", "raspberry", {"nivel": nivel})
                    if moda is None:
                        LOG.warning("Sensor local: llegaron datos, pero no hubo distancias válidas en el intervalo.")
                else:
                    LOG.warning("No se están recibiendo datos del sensor local durante el intervalo; no se publica una medición.")
                huboBytesIntervalo = False
                LOG.info("LOCAL moda del intervalo: estado=%d distancia=%s mm", estado, distancia)
                frecuencias.clear()
                moda = None
                ultima_distancia = None
                # Conserva el calendario sin inventar lecturas para intervalos
                # que pudieran haberse saltado por una pausa del sistema.
                proximo_envio = sampling_time.avanzar_intervalo(
                    proximo_envio, ahora, CONFIGURACION['intervalo'], 'seconds')

            huboBytesIntervalo = huboBytesIntervalo or bool(datos)
            # Las tramas recibidas al cerrar un intervalo pertenecen al siguiente.
            for distancia in maxbotix.decodificar_tramas(datos, bufferSensor):
                ultima_distancia = distancia
                if 0 <= distancia <= CONFIGURACION['distancia_maxima_mm']:
                    frecuencias[distancia] = frecuencias.get(distancia, 0) + 1
                    # En caso de empate se elige la más reciente de las empatadas.
                    if moda is None or frecuencias[distancia] >= frecuencias[moda]:
                        moda = distancia
    finally:
        maxbotix.cerrar_puerto(puerto)


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


