"""Configuración compartida; importar este módulo no inicia dispositivos."""
from pathlib import Path
from zoneinfo import ZoneInfo
import sampling_time
import json
CARPETA_PROGRAMA = Path("/home/pi/cornareSAT")
CARPETA_BACKUP = Path("/home/pi/datalogger")
CONFIGURACION = {}
settings = {}

def cargar():
    file_settings = CARPETA_PROGRAMA / "credentials" / "settings.json"
    settings.clear()
    with open(file_settings, 'r') as archivo:
        settings.update(json.load(archivo))
    nivel_local = settings.get("LEVEL", True)
    xbee_habilitado = settings.get("XBEE", True)
    if not isinstance(nivel_local, bool):
        raise ValueError("LEVEL debe ser true o false en settings.json")
    if not isinstance(xbee_habilitado, bool):
        raise ValueError("XBEE debe ser true o false en settings.json")
    CONFIGURACION.clear()
    CONFIGURACION.update({
    "nivel_local": nivel_local,  # Activa o desactiva únicamente el nivel local.
    "H_XBEE": xbee_habilitado,
    "H_LEVEL": settings['MAXBOTIX_TTL'],
    "H_RAIN": settings['RAIN'],
    "codigo": settings['CODE'],
    "intervalo": (
        sampling_time.segundos(settings['SAMPLETIME_LEVEL'], 'minutes')
        if nivel_local or xbee_habilitado else None
    ),
    "calibracion": (
        float(settings['MAXBOTIX_ZERO_RAW']),
        float(settings['MAXBOTIX_SPAN_RAW']),
        float(settings['MAXBOTIX_ZERO']),
        float(settings['MAXBOTIX_SPAN']),
    ) if nivel_local else None,

    # Puerto del adaptador USB donde está conectado el XBee receptor.
    "xbee": "/dev/xbee",

    # Si utilizas el CP2102.
    # Si existe el alias /dev/maxbotix (por ejemplo, creado con udev), lo utiliza.
    # Si no existe, utiliza /dev/ttyUSB1 directamente; no requiere configurar udev.
    "sensor": "/dev/maxbotix" if Path('/dev/maxbotix').exists() else "/dev/ttyUSB1",

    # Si conectaras el sensor al UART GPIO de la Raspberry,
    # normalmente sería: "/dev/serial0"

    "baudios_sensor": 9600,
    "baudios_xbee": 9600,
    "distancia_maxima_mm": 9998,
    "valor_error_nivel": -888.8,
    "reintento_puerto_s": 3.0,
    "reintento_ni_s": 30.0,
    "timeout_mqtt": 3.0,
    "reintento_mqtt": 5.0,
    "periodo_lectura_analogica_s": 0.1,

    # Protección frente a una longitud corrupta recibida por la UART.
    "longitud_maxima_trama_api": 2048,
    "tiempo_fragmento_api_s": 3.0,
    "zona_horaria": ZoneInfo("America/Bogota"),
    "ver_xbee": False,
    "settings": file_settings,
    "credenciales": CARPETA_PROGRAMA / "credentials" / ".env",
    "carpeta_csv": CARPETA_BACKUP,
    "log_file": Path('/var/log/python_errors.log'),
    })
    CONFIGURACION.update(
        intervalo_lluvia=(
            sampling_time.segundos(settings['SAMPLETIME_RAIN'], 'minutes')
            if CONFIGURACION['H_RAIN'] else None
        ),
        sensor_lluvia='/dev/rain',
    )
    return CONFIGURACION
