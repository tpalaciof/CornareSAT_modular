"""Comunicación con XBee AP=1/AO=0 y mensajes JSON de la ESP32."""
import json
import logging
import time

LOG = logging.getLogger("PythonLogger")
REVISION_NI_S = 300.0

# Asociaciones conocidas: configuración inicial o JSON válido recibido por radio.
CODIGOS_LOG_XBEE = {}

def contextoNodo(mac=None, codigo=None):     # Sirve para los logs
    if codigo is None:                      
        codigo = CODIGOS_LOG_XBEE.get(mac)   # Si no se proporcionó el código, busca la MAC en CODIGOS_LOG_XBEE y devuelve el código. 
                                             # Por ejemplo: CODIGOS_LOG_XBEE.get("0013A20012345678")  devuelve "667"
    # No atribuir al nodo el nombre ni la ciudad de la Raspberry en el log (loggingTelegraf.py)                
    return {'station_code': codigo, 'station_name': None, 'station_city': None} # 


# ************************** TRAMAS API *************************** #

def calcularChecksum(datosTrama):
    return 0xFF - (sum(datosTrama) & 0xFF)

# Genera la trama según el formato AP = 1, Delimitador de Inicio (0x7E) + longitud + datosTrama (ID + datos específicos) + checksum
def construirTramaApi(datosTrama):
    longitud = len(datosTrama)
    return b"\x7e" + longitud.to_bytes(2, "big") + datosTrama + bytes([
        calcularChecksum(datosTrama)
    ])


def decodificarTramasApi(configuracion, datos, bufferApi, ultimaActividad):
    """AP=1: conserva fragmentos entre lecturas; no espera una trama completa."""
    ahora = time.monotonic()

    # Si el buffer está vacío, actualiza el timepo de ultimaActividad
    if not bufferApi:               
        ultimaActividad = ahora

    # Si quedaron bytes en el búfer y ha pasado más tiempo que tiempo_fragmento_api_s
    if bufferApi and ahora - ultimaActividad > configuracion['tiempo_fragmento_api_s']:    
        LOG.warning("Caducó una trama API incompleta; buscando el siguiente inicio.", extra=contextoNodo())
        del bufferApi[0]            # borra el primer byte del búfer y actualiza el tiempo. Borrar ese byte permite que la búsqueda posterior examine el resto en busca de otro 0x7E.
        ultimaActividad = ahora
    if datos:
        bufferApi.extend(datos)  # Añade los datos al final del búfer
        ultimaActividad = ahora  # Reinicia el timeout con cada fragmento UART.
    tramas = []                  # Lista donde pondrá las tramas completas encontradas en esta llamada.

    while bufferApi:             # Mientras hayan datos en el búfer
        inicio = bufferApi.find(b"\x7e")  # find devuelve la pocisión donde se encuentra x7e o -1
        if inicio < 0:              
            bufferApi.clear()             # Si no hay delimitador de inicio en todo el búfer, se limpia completamente
            break                         # Se sale del while
        if inicio:
            ultimaActividad = ahora
        del bufferApi[:inicio]
        if len(bufferApi) < 3:  # Si hay menos de tres bytes, todavía faltan bytes del encabezado. (8b'0 = 0x7e, 0b'1,2 = longitud)
            break
        longitud = int.from_bytes(bufferApi[1:3], "big")                        # Bytes 1-2, pues en Python el límite derecho de un corte se excluye.
        if not 1 <= longitud <= configuracion['longitud_maxima_trama_api']:
            LOG.warning("Longitud API no válida: %d.", longitud, extra=contextoNodo())
            del bufferApi[0]            # Si la longitud no está en el rango admitido, el programa descarta ese posible inicio y busca el siguiente.
            ultimaActividad = ahora
            continue
        total = longitud + 4        # (1 byte 0x7e + 2 bytes longitud + longitud (trama de datos) + 1 byte checksum)
        if len(bufferApi) < total:  # Claramente un búfer que contenga una trama correcta, debe contener por lo menos, esta trama correcta
            break
        datos_trama = bytes(bufferApi[3:total - 1])

        checksum_recibido = bufferApi[total - 1]
        checksum_esperado = calcularChecksum(datos_trama)

        if checksum_recibido != checksum_esperado:
            LOG.warning("Trama API descartada por checksum incorrecto.", extra=contextoNodo())
            del bufferApi[0]
            ultimaActividad = ahora
            continue

        del bufferApi[:total]       # Se elimina del búfer lo que equivale a la trama completa, una vez confirmada que era correcta
        ultimaActividad = ahora     # Se actualiza el tiempo
        tramas.append(datos_trama)  # Se añade los datos de la trama valida al arreglo
    return tramas, ultimaActividad


def reconstruirLineasJSON(mac, datos, fragmentosPorMac):
    """La ESP32 termina cada JSON con LF; conserva lo incompleto por MAC."""
    anterior, momento = fragmentosPorMac.get(mac, (b"", 0.0))

    """
    Ejemplo: 
    {
    '0013A200422AB555': (b'{"nivel":50', 100.0)
    }
    """
    ahora = time.monotonic()
    if ahora - momento > 5.0:   # Si han pasado más de 5 segundos
        anterior = b""          # Evita unir datos nuevos con fragmentos viejos

    partes = (anterior + datos).split(b"\n")    # Une el fragmento anterior con los bytes nuevos. Divide el resultado donde encuentre saltos de línea.
    resto = partes.pop()    # Extra el último elemento separado por \n, lo elimina de 'partes' y lo añade a 'resto'. Si no hay elemento separado por \n, entonces extrae todo el fragmento y queda como pendiente. 

    """
    partes = [
    b'{"nivel":500,"codigo":"667"}',
    b'{"nivel":501,"codigo":"667"}',
    b'{"nivel":50'
    ]

    Luego: 

    resto = partes.pop()

    resto = b'{"nivel":50'

    partes = [
    b'{"nivel":500,"codigo":"667"}',
    b'{"nivel":501,"codigo":"667"}'
    ]
    """
    if len(resto) > 512:
        LOG.warning("Mensaje XBee sin terminador; se descarta el fragmento excesivo.", extra=contextoNodo(mac))
        resto = b""

    fragmentosPorMac[mac] = (resto, ahora)  # Se crea o actualiza la entrada del diccionario.

    lineas = []

    for linea in partes:
        limpia = linea.strip()  # devuelve el contenido de linea quitando los caracteres en blanco de sus extremos: espacios, tabulaciones, retornos de carro y saltos de línea.

        if limpia:              # Si contiene bytes
            lineas.append(limpia)

    return lineas


def procesarTramaRecepcion90(trama, fragmentosPorMac):
    """0x90: tipo, MAC[1:9], reservado[9:11], opciones[11], RF[12:]."""
    if len(trama) < 12:
        LOG.warning("Trama 0x90 demasiado corta.", extra=contextoNodo())
        return []
    mac = trama[1:9].hex().upper()
    recepcion_ms = time.time_ns() // 1_000_000
    registros = []
    for linea in reconstruirLineasJSON(mac, trama[12:], fragmentosPorMac):
        try:
            mensaje = json.loads(linea)                     # convierte en formato json. Mensaje se convierte en un diccionario mensaje = {'nivel': 500,'codigo': '667'}
        except (ValueError, UnicodeDecodeError) as error:
            LOG.warning('JSON del nodo descartado: %s', error, extra=contextoNodo(mac))
            continue    # Salta a la siguiente vuelta del for

        registros.append({'tipo': 'xbee', 'origen': mac, 'ts': recepcion_ms,
                          'datos': {'trama_json': mensaje}})
    return registros

    """
    registros = [
    {
        'tipo': 'xbee',
        'origen': '0013A200422AB555',
        'ts': 1700000000123,
        'datos': {
            'trama_json': {
                'nivel': 500,
                'codigo': '667'
            }
        }
    }
    """

def solicitarNiNodo(configuracion, puerto, mac, estadoNi):
    """Consulta NI por MAC; NI es el nombre configurado del xbee."""
    ahora = time.monotonic()
    anterior = estadoNi["nodos"].get(mac)   # Busca la MAC dentro de "nodos", si es la primera vez que aparece esa MAC, vale none, 

    """
    En la primera llamada, el diccionario estadoNi se vería así: 
    estadoNi = {
        "identificador": 0,
        "nodos": {}
        }
    }

    En otras llamadas: 

    estadoNi = {
        "identificador": 1,
        "nodos": {
            "0013A20012345678": {
                "identificador": 1,
                "ultimo_intento": 100.0,
                "ni": None
            }
        }
    }

    Y anterior = estadoNi["nodos"].get(mac), toma el diccionario nodos según su MAC y se queda con esta información: 

    {
    "identificador": 1,
    "ultimo_intento": 100.0,
    "ni": None
    }
    """

    # Si el NI ya se conoce, o todavía no ha pasado el tiempo de reintento_ni_s después del último intento
    # Un NI conocido también se vuelve a consultar, con un intervalo mayor.
    if anterior is not None:
        espera = REVISION_NI_S if anterior["ni"] is not None else configuracion['reintento_ni_s']
        if ahora - anterior["ultimo_intento"] < espera:
            return
    
    # Si no se encuentra asociado un NI para esa MAC
    # La misma consulta se utiliza para comprobar si cambió un NI conocido.
    estadoNi["identificador"] = estadoNi["identificador"] % 255 + 1 # Genera un identificador para reconocer la respuesta
    identificador = estadoNi["identificador"]

    # Solicitud para obtener NI.
    # datosTrama para consultar NI: tipo (0x17) + identificador + MAC destino + reservado (0xFFFE) + opciones (0x00) + comando NI (0x4E49).
    tipo_e_identificador = bytes([0x17, identificador])
    mac_destino = bytes.fromhex(mac)
    campo_reservado = b"\xff\xfe"
    opciones = b"\x00"
    comando = b"NI"

    datos_trama = (
        tipo_e_identificador
        + mac_destino
        + campo_reservado
        + opciones
        + comando
    )

    trama = construirTramaApi(datos_trama)

    estadoNi["nodos"][mac] = {"identificador": identificador,
                              "ultimo_intento": ahora, "ni": None}

    """
    estadoNi = {
        "identificador": 1,
        "nodos": {
            "0013A20012345678": {
                "identificador": 1,
                "ultimo_intento": 100.0,
                "ni": None
            }
        }
    }
    """
    try:

        bytes_esperados = len(trama)         # Cuántos bytes tiene la trama.
        bytes_escritos = puerto.write(trama) # Primero se envía la trama al puerto, luego devuelve cuántos bytes escribió.

        if bytes_escritos != bytes_esperados: 
            raise OSError("Escritura de AT NI incompleta")

    except OSError as error:
        LOG.warning("No se pudo consultar el NI del nodo: %s", error, extra=contextoNodo(mac))


def procesarRespuestaAt97(trama, estadoNi):
    """0x97: tipo, ID, MAC[2:10], reservado, comando[12:14], estado, NI."""
    if len(trama) < 15 or trama[12:14] != b"NI":
        return
    mac = trama[2:10].hex().upper()
    pendiente = estadoNi["nodos"].get(mac)
    if pendiente is None or trama[1] != pendiente["identificador"]:
        return
    if trama[14] != 0:
        LOG.warning("NI no disponible para el nodo.", extra=contextoNodo(mac))
        return
    try:
        ni = trama[15:].rstrip(b"\x00").decode("ascii").strip()
    except UnicodeDecodeError:
        LOG.warning("Respuesta NI no válida.", extra=contextoNodo(mac))
        return
    if len(ni) > 20 or any(ord(caracter) < 32 or ord(caracter) > 126 for caracter in ni):
        LOG.warning("Respuesta NI no válida.", extra=contextoNodo(mac))
        return
    if pendiente["ni"] == ni:
        return
    pendiente["ni"] = ni
    return {'tipo': 'identificacion', 'origen': mac,
            'datos': {'mac': mac, 'ni': ni}}


def cerrarPuerto(estado):
    puerto = estado['puerto']
    if puerto is not None:
        try:
            puerto.close()
        except OSError:
            LOG.warning("No se pudo cerrar el puerto XBee", exc_info=True)
        estado['puerto'] = None


def recibir(configuracion, estado):
    """Lee el puerto y devuelve mensajes; reintenta la conexión sin esperas largas."""
    import serial

    registros = []
    try:    
        if estado['puerto'] is None:                            
            if time.monotonic() < estado['proximo_intento']:    # En el primer intento siempre va ser False: esto es válido por ejemplo cuando ocurre un fallo, y se actualiza el valor de proximo_intento 
                return registros                                # Si aún no ha pasado el tiempo de próximo intento, entonces se manda el registro vacío
            estado['puerto'] = serial.Serial(                           # Configura el puerto por primera vez dentro del while de tarea_xbee(). El objeto que devuelve serial.Serial() queda guardado en estado['puerto'].
                configuracion['xbee'], configuracion['baudios_xbee'],   
                timeout=0.1, write_timeout=0.25, exclusive=True)
            estado.update(buffer_api=bytearray(), ultima_actividad=time.monotonic(),    # estado.update(...) añade o reemplaza estas entradas en el diccionario. Crea los búferes y contadores, o los resetea, al abrir el puerto. 
                          fragmentos={}, ni={'identificador': 0, 'nodos': {}},
                          ultimo_aviso=time.monotonic(), bytes_recibidos=0, tramas_recibidas=0)
            LOG.info("XBee conectado: %s. Requiere AP=1 y AO=0.", configuracion['xbee'])

        puerto = estado['puerto']    # Recordemos que esto está dentro de un while en tarea_xbee, por lo que los valores del objeto pueden ser los recién configurados o otros
        datos = puerto.read(min(4096, puerto.in_waiting or 1))  # puerto.in_waiting dice cuántos bytes están listos para leer en ese instante. Si no hay bytes disponibles en el puerto,  puerto.read(1) pausa el hilo XBee mientras espera un byte para que se almacene en 'datos'

        """
        Bytes Disponibles   Llamada que se hace 
        0	                puerto.read(1)
        20	                puerto.read(20)
        5000	            puerto.read(4096)

        """
        # Sirve para ver qué bytes llegan del XBee cuando se está buscando un fallo. Se activa al poner ver_xbee en True.
        if configuracion['ver_xbee'] and datos:                 # cuando está activado ver_xbee y datos contiene al menos un byte. Si read() devolvió b'', Python considera ese valor falso y salta el bloque
            estado['bytes_recibidos'] += len(datos)
            LOG.info("XBEE UART RX: %d bytes; HEX=%s; TEXTO=%r",
                     len(datos), datos.hex(' ').upper(), datos)

        tramas, estado['ultima_actividad'] = decodificarTramasApi(
            configuracion, datos, estado['buffer_api'], estado['ultima_actividad'])

        for trama in tramas:
            if configuracion['ver_xbee']:
                estado['tramas_recibidas'] += 1
                LOG.info("XBEE API RX: tipo=0x%02X, longitud=%d", trama[0], len(trama))

            # 0x90 --> llegaron datos de un nodo.
            if trama[0] == 0x90:     #Como ya estamos tratando únicamnete los datos de la trama, el primer byte corresponde la API ID
                registros.extend(procesarTramaRecepcion90(trama, estado['fragmentos']))

                """
                procesarTramaRecepcion90(trama, estado['fragmentos']) devulve registros. Utiliza reconstruirLineasJSON para devolver tramas completas. 
                
                registros = [
                {
                    'tipo': 'xbee',
                    'origen': '0013A200422AB555',
                    'ts': 1700000000123,
                    'datos': {
                        'trama_json': {
                            'nivel': 500,
                            'codigo': '667'
                        }
                    }
                }
                """
                if len(trama) >= 12:    # 8b'0 = Tipo 0x90, 8b'1-8 = MAC, 8b'9-10 = Reservado, 8b'11 = opciones de recepción, 8b'12 en adelante = Los bytes que envió el nodo

                    # trama[1:9].hex().upper() --> toma los ocho bytes de la MAC, del índice 1 al 8. .hex().upper() los convierte en un texto como "0013A20012345678"
                    solicitarNiNodo(configuracion, puerto, trama[1:9].hex().upper(), estado['ni']) 
                    
                    """
                    Consulta el estado de estado['ni']: 

                    estadoNi = {
                        "identificador": 1,
                        "nodos": {
                            "0013A20012345678": {
                                "identificador": 1,
                                "ultimo_intento": 100.0,
                                "ni": None
                            }
                        }
                    }

                    Si ya conoce el ni, lo deja y se sale de la función, si no existe ni para esa mac, entonces 
                    escribe en el puerto la solicitud para obtener el NI: esta respuesta llegará en una trama 0x97
                    """
                    
            # 0x97 --> llego una respuesta a una consulta.
            elif trama[0] == 0x97:
                identificacion = procesarRespuestaAt97(trama, estado['ni'])

                """
                return {'tipo': 'identificacion', 'origen': mac,'datos': {'mac': mac, 'ni': ni}}
            
                """
                if identificacion is not None:
                    registros.append(identificacion)
            
            # 0x8A --> llegó un estado del radio.
            elif trama[0] == 0x8A:
                LOG.info("Estado del módem XBee: %s", trama.hex().upper())

        if configuracion['ver_xbee'] and time.monotonic() - estado['ultimo_aviso'] >= 45:
            if not estado['bytes_recibidos']:
                LOG.warning("XBEE: en 45 s no llegó ningún byte por %s. El problema ocurre antes de interpretar el JSON.", configuracion['xbee'])
            elif not estado['tramas_recibidas']:
                LOG.warning("XBEE: llegaron %d bytes, pero ninguna trama API válida. Revisar formato API y baudios con los bytes mostrados arriba.", estado['bytes_recibidos'])
            estado.update(bytes_recibidos=0, tramas_recibidas=0, ultimo_aviso=time.monotonic())

    except OSError as error:
        LOG.warning("XBee no disponible: %s. El sensor local continúa.", error)
        cerrarPuerto(estado)
        estado['proximo_intento'] = time.monotonic() + configuracion['reintento_puerto_s']
    return registros
