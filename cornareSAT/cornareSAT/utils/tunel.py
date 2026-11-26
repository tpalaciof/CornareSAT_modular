"""Inicio del túnel TCP del proyecto."""
import logging
import subprocess
from pathlib import Path

LOG = logging.getLogger("PythonLogger")

def iniciarTunel(configuracion):
    tunnel = None
    programa = Path('/home/pi/shootback/slaver.py')
    if programa.is_file():
        puerto = '500' + configuracion['codigo']
        if puerto.isdigit() and 0 < int(puerto) <= 65535:
            socket = '172.235.149.138:' + puerto
            try:
                tunnel = subprocess.Popen(
                    ['python3', str(programa), '-m', socket, '-t', '127.0.0.1:22', '--ssl'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                LOG.info('Se activo el tunnel TCP en el siguiente socket: %s', socket)
            except OSError as error:
                LOG.warning('Falló la conexión con el tunnel TCP: %s', error)
        else:
            LOG.warning('El puerto del túnel original 500%s no es válido; revisar la configuración del servidor.', configuracion['codigo'])
    else:
        LOG.info('El túnel no se inició: no existe %s', programa)
    return tunnel

