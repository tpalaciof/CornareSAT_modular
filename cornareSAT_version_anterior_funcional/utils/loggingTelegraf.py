import logging
import json
from pathlib import Path

file = Path(__file__).resolve().parents[1] / 'credentials' / 'settings.json'
codigo = nombre = municipio = ''


def configurar(ruta=file, ajustes=None):
    global codigo, nombre, municipio
    if ajustes is None:
        with open(ruta, 'r') as archivo:
            settings = json.load(archivo)
    else:
        settings = ajustes
    codigo = str(settings['CODE'])
    nombre = settings.get('NAME', '')
    municipio = settings.get('MUNICIPIO', '')


# Los programas existentes siguen obteniendo los metadatos al importar.
# nivel.py vuelve a configurarlos si se utiliza --settings con otra ruta.
try:
    configurar()
except (OSError, ValueError, KeyError, TypeError):
    pass


class JSONFormatter(logging.Formatter): # Toma los campos del log y los convierte en texto JSON
    def format(self, record):
        log_record = {
            "time": self.formatTime(record, "%Y-%m-%dT %H:%M:%S"),
            "level": record.levelname,
            "code": getattr(record, "station_code", codigo),
            "name": getattr(record, "station_name", nombre),
            "city": getattr(record, "station_city", municipio),
            "message": record.getMessage()
        }
        return json.dumps(log_record, ensure_ascii=False)
