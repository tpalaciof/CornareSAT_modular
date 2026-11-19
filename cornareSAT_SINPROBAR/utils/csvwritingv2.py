import csv
import datetime
from pathlib import Path
import logging
import json
import os
import re
import uuid


def anexarJson(filename, tramas):
    """Respaldo de nivel: un JSON por línea, sin cabecera, en el CSV diario."""
    lineas = [json.dumps(trama, separators=(',', ':'), allow_nan=False) + '\n'
              for trama in tramas]
    ruta = Path(filename)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, 'ab') as archivo:
        archivo.write(''.join(lineas).encode('utf-8'))
        archivo.flush()
        os.fsync(archivo.fileno())


def verifyDuplications(filename,data):
    """Comprueba un JSON completo o una fila CSV, según el tipo de data."""

    duplicates_found = False
    my_file = Path(filename)

    if not my_file.is_file():
        print('File does not exist. Duplications were not found.')
    else:
        with open(filename, 'r', encoding='utf-8') as path:
            if isinstance(data, dict):
                duplicates_found = any(json.loads(linea) == data
                                       for linea in path if linea.strip())
            else:
                file_list = ((path.read()).split('\n'))
                matched_data = ';'.join(map(str,data))
                if matched_data in file_list:
                    duplicates_found = True
        

    
    return duplicates_found   


def writeFile(filename, header, data=None):
    """JSON: writeFile(ruta, trama). CSV: writeFile(ruta, cabecera, fila).

    Devuelve True si se escribió el registro y False si hubo un error.
    """
    try:
        if data is None:
            data = header
        if isinstance(data, dict):
            anexarJson(filename, [data])
        else:
            my_file = Path(filename)
            nuevo = not my_file.is_file()
            with open(filename, 'a', newline='') as path:
                writer = csv.writer(path,delimiter=';')
                if nuevo:
                    writer.writerow(header)
                writer.writerow(data)
        
        data_written = True
    except Exception as e:
        logging.exception(e)
        data_written = False

    return data_written


def leerPendienteRespaldo(carpeta):
    """Lee la primera medición pendiente de nivel o lluvia."""
    carpeta = Path(carpeta)
    rutas = list(carpeta.glob('local/pendientes_*.csv'))
    rutas.extend(carpeta.glob('nodos/*/pendientes_*.csv'))
    for ruta in sorted(rutas):
        with open(ruta, 'rb') as archivo:
            while True:
                linea = archivo.readline()
                if not linea:
                    break
                if linea.strip():
                    return json.loads(linea), (ruta, archivo.tell())
        ruta.unlink(missing_ok=True)
    return None


def confirmarRespaldo(ruta, posicion):
    """Elimina el prefijo confirmado; conserva íntegros los datos pendientes."""
    ruta = Path(ruta)
    # La misma tarea realiza escrituras y confirmaciones: no hay otro escritor
    # interno mientras se copia el resto, incluidos datos anexados durante MQTT.
    temporal = None
    try:
        with open(ruta, 'rb') as origen:
            tamano = os.fstat(origen.fileno()).st_size
            if not 0 <= posicion <= tamano:
                raise ValueError('Posición de respaldo fuera del archivo: ' + str(ruta))
            if posicion == tamano:
                ruta.unlink()
                return
            origen.seek(posicion)
            temporal = ruta.with_name(ruta.name + '.' + uuid.uuid4().hex + '.tmp')
            with open(temporal, 'xb') as destino:
                while True:
                    bloque = origen.read(65536)
                    if not bloque:
                        break
                    destino.write(bloque)
                destino.flush()
                os.fsync(destino.fileno())
        # Reemplazo atómico: ante un fallo previo permanece el archivo original.
        os.replace(temporal, ruta)
    finally:
        if temporal is not None:
            temporal.unlink(missing_ok=True)


def rutaMedicion(configuracion, registro, trama, pendiente=False):
    dia = datetime.datetime.strptime(trama['fecha'], '%Y-%m-%d %H:%M').strftime('%Y-%m-%d')
    carpeta = Path(configuracion['carpeta_csv'])
    directorio = carpeta / 'local'
    if registro['tipo'] == 'xbee':
        # MAC estable: el histórico no cambia de ruta cuando cambia el NI.
        mac = registro['origen'].upper()
        if not re.fullmatch(r'[0-9A-F]{16}', mac):
            raise ValueError('MAC XBee no válida')
        directorio = carpeta / 'nodos' / mac
    prefijo = 'rain' if 'precipitacion' in trama else 'level'
    if pendiente:
        prefijo = 'pendientes_' + prefijo
    return directorio / (prefijo + dia + '.csv')


def guardarRespaldoNivel(configuracion, registro, trama):
    '''
    Write data in a backup file
    '''
    ruta = rutaMedicion(configuracion, registro, trama, pendiente=True)
    '''
    Write data in file
    '''
    if 'precipitacion' not in trama and ruta.is_file() and verifyDuplications(ruta, trama):
        return
    if not writeFile(ruta, trama):
        raise OSError("No se pudo guardar el respaldo: " + str(ruta))


def migrarRespaldosAnteriores(carpeta):
    """Reubica los JSON de la estructura anterior antes de empezar a enviar."""
    carpeta = Path(carpeta)
    diarios = carpeta / 'diarios'
    nodos = carpeta / 'nodos'
    local = carpeta / 'local'
    logger = logging.getLogger('PythonLogger')
    origenes = [(carpeta, local, True), (diarios, local, False)]
    for raiz, pendientes in ((nodos, True), (diarios / 'nodos', False)):
        for origen in sorted(raiz.glob('*')):
            mac = origen.name.rsplit('_', 1)[-1].upper()
            if pendientes and '_' not in origen.name:
                continue
            if re.fullmatch(r'[0-9A-F]{16}', mac) and origen.is_dir() and not origen.is_symlink():
                origenes.append((origen, nodos / mac, pendientes))

    for origen, destino, pendientes in origenes:
        lluvia = 'rain_pending' if pendientes else 'rain'
        for prefijo, campo in (('level', 'nivel'), (lluvia, 'precipitacion')):
            for ruta in sorted(origen.glob(prefijo + '????-??-??.csv')):
                try:
                    if ruta.is_symlink() or not ruta.is_file():
                        continue
                    with ruta.open('rb') as archivo:
                        if origen == carpeta:
                            if archivo.readline().strip() == b'Date Time;Level':
                                continue
                            archivo.seek(0)
                        for linea in archivo:
                            if linea.strip():
                                trama = json.loads(linea)
                                if not isinstance(trama, dict) or not {campo, 'fecha', 'codigo'} <= trama.keys():
                                    raise ValueError('Registro de medición incompleto')
                    nombre = ruta.name.replace('rain_pending', 'rain', 1)
                    if pendientes:
                        nombre = 'pendientes_' + nombre
                    destino.mkdir(parents=True, exist_ok=True)
                    nueva = destino / nombre
                    numero = 2
                    while nueva.exists() or nueva.is_symlink():
                        nueva = destino / (Path(nombre).stem + f'_{numero}.csv')
                        numero += 1
                    ruta.rename(nueva)
                except (OSError, ValueError) as error:
                    logger.warning('Se conserva el archivo anterior %s: %s', ruta, error)

    for ruta in [origen for origen, _, _ in origenes[2:]] + [diarios / 'nodos', diarios]:
        if ruta.is_dir() and not ruta.is_symlink() and not any(ruta.iterdir()):
            ruta.rmdir()


'''
if __name__ == '__main__':
    if not(verifyDuplications('Test.csv',['2022-06-03 07:38:41',0.0])):
        writeFile('Test.csv',['fecha','hora'],['hoy','ahora'])
    else:
        print('Duplications found.')
'''


def guardarHistorico(configuracion, registro, trama):
    """Histórico permanente separado de los pendientes que elimina PUBACK."""
    anexarJson(rutaMedicion(configuracion, registro, trama), [trama])
