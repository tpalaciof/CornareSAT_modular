from datetime import datetime
import json
import logging
import os
import threading
import time
import loggingTelegraf as lt
from interpretarTramasXbee import contextoNodo
from configuracion import CONFIGURACION
LOG = logging.getLogger("PythonLogger")
import csvwritingv2 as csvwriting
from moduls.registros import obtenerPendiente
from moduls.medicion_nivel import formatearTramaNivel

def formatearMedicion(registro):
    datos = registro['datos']['trama_json'] if registro['tipo'] == 'xbee' else registro['datos']
    if 'precipitacion' not in datos:
        return formatearTramaNivel(registro)
    fecha = datetime.fromtimestamp(registro['ts'] / 1000, CONFIGURACION['zona_horaria'])
    return {'precipitacion': datos['precipitacion'], 'fecha': fecha.strftime('%Y-%m-%d %H:%M'),
            'codigo': datos['codigo'] if registro['tipo'] == 'xbee' else CONFIGURACION['codigo']}

def contextoMedicion(trama):
    codigo = trama.get('codigo') if isinstance(trama, dict) else None
    if codigo == lt.codigo:
        return {}  # Medición local: conserva metadatos de settings.json.
    return contextoNodo(codigo=codigo)


# *************************** MQTT Y RESPALDO ********************* #

def on_connect(client, userdata, flags, rc, properties):
    if rc == 0:
        client.subscribe("sensor/" + CONFIGURACION['codigo'])
        LOG.info("client is connected")
    else:
        LOG.warning('Falla de conexión por código %s', rc)


def on_message(client, userdata, message):
    try:
        payload = message.payload.decode()
        data = json.loads(payload)
        if isinstance(data, dict) and "type" in data:
            if data["type"] == "saved":
                LOG.info("data saved %s", data)
            else:
                LOG.warning('broker falló en responder: %s', message.topic)
    except (UnicodeDecodeError, ValueError):
        LOG.warning("Respuesta no válida del broker en %s", message.topic)


def tarea_salida(finalizar, colas):
    import paho.mqtt.client as mqtt
    from dotenv import load_dotenv

    logger = LOG

    '''
    Load credentials to connect to broker MQTT
    '''
    load_dotenv(CONFIGURACION['credenciales'])
    user = os.getenv('USERNAME')
    password = os.getenv('PASSWORD')
    host = os.getenv('HOST')
    port = int(os.getenv('PORT') or 1883)

    turno = 0
    salidaDisponible = True
    timeout = CONFIGURACION['timeout_mqtt']
    reintento = CONFIGURACION['reintento_mqtt']
    porConfirmar = []
    proximoReenvio = 0.0
    client = None
    loopIniciado = False

    try:
        csvwriting.migrarRespaldosAnteriores(CONFIGURACION['carpeta_csv'])
    except OSError as error:
        logger.warning('No se completó la reubicación de archivos anteriores: %s', error)

    '''
    Connect to database
    '''
    try:
        if not host:
            raise ConnectionError("Falta HOST en el archivo .env")
        client = mqtt.Client(client_id=CONFIGURACION['codigo'], callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = on_connect
        client.on_message = on_message
        client.connect_timeout = timeout
        client.reconnect_delay_set(min_delay=1, max_delay=30)
        client.max_inflight_messages_set(16)
        client.max_queued_messages_set(32)
        if os.getenv('MQTT_TLS', '1').lower() not in ('0', 'false', 'no'):
            client.tls_set(cert_reqs=mqtt.ssl.CERT_NONE)
            client.tls_insecure_set(True)
        client.username_pw_set(username=user, password=password)
        # DNS, TCP y TLS se resuelven en el hilo de Paho, fuera de este bucle.
        client.connect_async(host, port, 60)
        if client.loop_start() != mqtt.MQTT_ERR_SUCCESS:
            raise OSError("No se pudo iniciar el hilo MQTT")
        loopIniciado = True
    except (OSError, ValueError, RuntimeError) as error:
        logger.warning("MQTT no disponible; se conservan los datos localmente: %s", error)

    def enviar(trama, registro=None, respaldo=None):
        '''
        Conform the frame to write on database and file
        '''
        #print(data)
        informacion = client.publish("estacion", json.dumps(
            trama, separators=(',', ':'), allow_nan=False
        ), qos=1)
        if informacion.rc != mqtt.MQTT_ERR_SUCCESS:
            raise ConnectionError("El cliente MQTT no aceptó la publicación")
        porConfirmar.append({
            'informacion': informacion,
            'limite': time.monotonic() + timeout,
            'registro': registro,
            'trama': trama,
            'respaldo': respaldo,
        })

    '''
    Main loop
    '''
    try:
        while (not finalizar.is_set() or porConfirmar
               or any(not colas[tipo].empty() for tipo in ('local', 'xbee', 'identificacion'))):
            ahora = time.monotonic()

            # Revisa las confirmaciones de las publicaciones anteriores.
            for envio in porConfirmar[:]:
                registro = envio['registro']
                trama = envio['trama']
                respaldo = envio['respaldo']
                try:
                    confirmado = envio['informacion'].is_published()
                except (ValueError, RuntimeError):
                    confirmado = False
                if confirmado:
                    if respaldo is not None:
                        try:
                            csvwriting.confirmarRespaldo(*respaldo)
                        except (OSError, ValueError) as error:
                            logger.warning("No se pudo actualizar el respaldo; se conserva: %s", error, extra=contextoMedicion(trama))
                            proximoReenvio = ahora + reintento
                    porConfirmar.remove(envio)
                elif ahora >= envio['limite'] or client is None or not client.is_connected():
                    if respaldo is None:
                        csvwriting.guardarRespaldoNivel(CONFIGURACION, registro, trama)
                    proximoReenvio = ahora + reintento
                    porConfirmar.remove(envio)
                    logger.warning("Envío MQTT sin confirmar; el dato queda respaldado.", extra=contextoMedicion(trama))

            reenvioEnCurso = any(envio['respaldo'] is not None for envio in porConfirmar)

            # Procesa una medición nueva.
            registro = obtenerPendiente(colas, dar_turno_remoto=(turno % 4 == 3))
            if registro is not None:
                turno += 1
                if registro['tipo'] == 'identificacion':
                    mac = registro['origen']
                    logger.info('Nodo XBee %s identificado como %s', mac, registro['datos']['ni'],
                                extra=contextoNodo(mac))
                    continue
                trama = formatearMedicion(registro)
                csvwriting.guardarHistorico(CONFIGURACION, registro, trama)
                # La terminal muestra la recepción sin esperar a DNS ni al PUBACK.
                if salidaDisponible:
                    try:
                        print(json.dumps(trama, separators=(',', ':'), allow_nan=False), flush=True)
                    except OSError:
                        logger.warning("Terminal no disponible; el envío y el respaldo continúan.")
                        salidaDisponible = False
                if client is not None and client.is_connected() and len(porConfirmar) < 16:
                    try:
                        enviar(trama, registro=registro)
                    except (OSError, ValueError, RuntimeError) as error:
                        logger.warning("No se pudo iniciar el envío MQTT: %s", error, extra=contextoMedicion(trama))
                        csvwriting.guardarRespaldoNivel(CONFIGURACION, registro, trama)
                else:
                    csvwriting.guardarRespaldoNivel(CONFIGURACION, registro, trama)

            # Solo un respaldo en vuelo; los datos nuevos conservan su prioridad.
            if (not finalizar.is_set() and client is not None and client.is_connected()
                    and not reenvioEnCurso and len(porConfirmar) < 16
                    and time.monotonic() >= proximoReenvio
                    and colas['local'].empty() and colas['xbee'].empty()):
                try:
                    respaldo = None
                    pendiente = csvwriting.leerPendienteRespaldo(CONFIGURACION['carpeta_csv'])
                    if pendiente is not None:
                        trama, respaldo = pendiente
                    else:
                        proximoReenvio = time.monotonic() + 0.25
                    if respaldo is not None:
                        enviar(trama, respaldo=respaldo)
                except (OSError, ValueError, RuntimeError) as error:
                    logger.warning("No se pudo reenviar el respaldo; se conserva: %s", error,
                                   extra=contextoMedicion(trama) if respaldo is not None else contextoNodo())
                    proximoReenvio = time.monotonic() + reintento
            if registro is None:
                time.sleep(0.01)
    finally:
        if client is not None:
            client.disconnect()
            if loopIniciado:
                # Una resolución DNS del sistema puede seguir esperando al salir.
                cierre = threading.Thread(target=client.loop_stop, daemon=True)
                cierre.start()
                cierre.join(timeout=min(0.5, timeout))


