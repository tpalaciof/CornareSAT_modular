import csv
import datetime
from pathlib import Path
import logging
import json
import os
import re
import uuid


REGISTRO_NODOS = 'nodos_xbee.json'


def _macValida(mac):
    return isinstance(mac, str) and re.fullmatch(r'[0-9A-F]{16}', mac) is not None


def _niValido(ni):
    return (isinstance(ni, str) and re.fullmatch(r'[ -~]{1,20}', ni) is not None
            and ni == ni.strip() and ni not in ('.', '..')
            and '/' not in ni and '\\' not in ni)


def _existeRuta(ruta):
    return ruta.exists() or ruta.is_symlink()


def _directorioNodo(carpeta, mac, nombres):
    if nombres is not None:
        ni = nombres.get(mac)
        if ni is not None:
            return carpeta / 'nodos' / ni
        legado = carpeta / 'nodos' / mac
        if legado.is_dir() and not legado.is_symlink() and mac not in nombres.values():
            return legado
    return carpeta / 'sin_identificar' / mac


def _sincronizarDirectorio(carpeta):
    descriptor = os.open(carpeta, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _escribirRegistroNodos(carpeta, estado):
    ruta = carpeta / REGISTRO_NODOS
    temporal = carpeta / ('.' + ruta.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporal.open('x', encoding='utf-8') as archivo:
            json.dump(estado, archivo, indent=2, sort_keys=True)
            archivo.write('\n')
            archivo.flush()
            os.fsync(archivo.fileno())
        os.replace(temporal, ruta)
        _sincronizarDirectorio(carpeta)
    finally:
        temporal.unlink(missing_ok=True)


def _cerrarRenombreNodo(carpeta, estado):
    cambio = estado['renombre']
    origen = carpeta / cambio['origen']
    destino = carpeta / 'nodos' / cambio['ni']
    nombres = estado['nombres']
    if not _existeRuta(origen) and destino.is_dir() and not destino.is_symlink():
        nombres[cambio['mac']] = cambio['ni']
        _sincronizarDirectorio(destino.parent)
        if origen.parent != destino.parent and origen.parent.is_dir():
            _sincronizarDirectorio(origen.parent)
    _escribirRegistroNodos(carpeta, {'nombres': nombres})
    del estado['renombre']


def cargarRegistroNodos(carpeta):
    carpeta = Path(carpeta)
    try:
        with (carpeta / REGISTRO_NODOS).open(encoding='utf-8') as archivo:
            estado = json.load(archivo)
    except FileNotFoundError:
        return {'nombres': {}}

    nombres = estado.get('nombres') if isinstance(estado, dict) else None
    if (not isinstance(nombres, dict)
            or any(not _macValida(mac) or not _niValido(ni) for mac, ni in nombres.items())
            or len(nombres) != len(set(nombres.values()))):
        raise ValueError('Registro de MAC y NI inválido')

    cambio = estado.get('renombre')
    if cambio is not None:
        if not isinstance(cambio, dict):
            raise ValueError('Renombrado de nodo inválido')
        mac, ni = cambio.get('mac'), cambio.get('ni')
        if not _macValida(mac) or not _niValido(ni) or ni in nombres.values():
            raise ValueError('Renombrado de nodo inválido')
        origenes = {f'sin_identificar/{mac}', 'nodos/' + nombres.get(mac, mac)}
        if not isinstance(cambio.get('origen'), str) or cambio['origen'] not in origenes:
            raise ValueError('Carpeta de origen del renombrado inválida')
        try:
            _cerrarRenombreNodo(carpeta, estado)
        except OSError as error:
            logging.getLogger('PythonLogger').warning(
                'Se completará el registro del renombrado al volver a consultar el NI: %s', error)
    return estado


def _moverSinReemplazar(ruta, destino, nombre):
    nueva = destino / nombre
    numero = 2
    while _existeRuta(nueva):
        nueva = destino / (Path(nombre).stem + f'_{numero}.csv')
        numero += 1
    ruta.rename(nueva)


def _reubicarCsvDelNodo(carpeta, mac, nombres):
    destino = carpeta / 'nodos' / nombres[mac]
    origenes = [carpeta / 'sin_identificar' / mac]
    if mac not in nombres.values():
        origenes.append(carpeta / 'nodos' / mac)
    for origen in origenes:
        if not origen.is_dir() or origen.is_symlink():
            continue
        for ruta in sorted(origen.glob('*.csv')):
            if ruta.is_file() and not ruta.is_symlink():
                destino.mkdir(parents=True, exist_ok=True)
                _moverSinReemplazar(ruta, destino, ruta.name)
        if not any(origen.iterdir()):
            origen.rmdir()


def registrarNiNodo(carpeta, estado, mac, ni):
    """Asocia un NI a la MAC y renombra su directorio si ya existe."""
    if not _macValida(mac) or not _niValido(ni):
        raise ValueError('MAC o NI inválido como nombre de carpeta')
    carpeta = Path(carpeta)
    if estado.get('renombre') is not None:
        _cerrarRenombreNodo(carpeta, estado)
    nombres = estado['nombres']
    if nombres.get(mac) == ni:
        _reubicarCsvDelNodo(carpeta, mac, nombres)
        return False

    origen = _directorioNodo(carpeta, mac, nombres)
    destino = carpeta / 'nodos' / ni
    if ni in nombres.values() or (destino != origen and _existeRuta(destino)):
        raise ValueError(f'El nombre {ni!r} ya está en uso')
    if _existeRuta(origen) and (not origen.is_dir() or origen.is_symlink()):
        raise OSError(f'El origen no es un directorio de datos: {origen}')

    if destino == origen or not origen.exists():
        _escribirRegistroNodos(carpeta, {'nombres': {**nombres, mac: ni}})
        nombres[mac] = ni
    else:
        destino.parent.mkdir(parents=True, exist_ok=True)
        # Persiste la operación para recuperar la relación tras un corte de energía.
        cambio = {'mac': mac, 'ni': ni, 'origen': origen.relative_to(carpeta).as_posix()}
        _escribirRegistroNodos(carpeta, {'nombres': nombres, 'renombre': cambio})
        estado['renombre'] = cambio
        try:
            origen.rename(destino)
        finally:
            _cerrarRenombreNodo(carpeta, estado)

    _reubicarCsvDelNodo(carpeta, mac, nombres)
    return True


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
    rutas.extend(carpeta.glob('sin_identificar/*/pendientes_*.csv'))
    for ruta in sorted(rutas):
        with open(ruta, 'rb') as archivo:
            while True:
                linea = archivo.readline()
                if not linea:
                    break
                if linea.strip():
                    trama = json.loads(linea)
                    trama.pop('id', None)  # Campos del histórico local, fuera de MQTT.
                    trama.pop('ts', None)
                    return trama, (ruta, archivo.tell())
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
        mac = registro['origen'].upper()
        if not _macValida(mac):
            raise ValueError('MAC XBee no válida')
        directorio = carpeta / 'nodos' / mac
        if 'nombres_nodos' in configuracion:
            directorio = _directorioNodo(carpeta, mac, configuracion['nombres_nodos'])
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


def migrarRespaldosAnteriores(carpeta, nombres_nodos=None):
    """Reubica los JSON de la estructura anterior antes de empezar a enviar."""
    carpeta = Path(carpeta)
    diarios = carpeta / 'diarios'
    nodos = carpeta / 'nodos'
    local = carpeta / 'local'
    logger = logging.getLogger('PythonLogger')
    origenes = [(carpeta, local, True), (diarios, local, False)]
    for raiz, pendientes in ((nodos, True), (diarios / 'nodos', False)):
        for origen in sorted(raiz.glob('*')):
            if raiz == nodos and nombres_nodos is not None and origen.name in nombres_nodos.values():
                continue
            mac = origen.name.rsplit('_', 1)[-1].upper()
            if pendientes and '_' not in origen.name:
                continue
            if _macValida(mac) and origen.is_dir() and not origen.is_symlink():
                destino = nodos / mac if nombres_nodos is None else _directorioNodo(carpeta, mac, nombres_nodos)
                origenes.append((origen, destino, pendientes))

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
                    _moverSinReemplazar(ruta, destino, nombre)
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


def guardarSalidaXBee(configuracion, registro, trama):
    # Un único escritor. Si se reinicia entre los dos archivos y el commit,
    # la última línea permite completar la escritura sin repetir la medición.
    fila = dict(trama, id=registro['id'], ts=registro['ts'])
    linea = json.dumps(fila, separators=(',', ':'), allow_nan=False).encode() + b'\n'
    for pendiente in (False, True):
        ruta = rutaMedicion(configuracion, registro, trama, pendiente)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with ruta.open('a+b') as archivo:
            fin = archivo.tell()
            inicio = max(0, fin - max(1024, 2 * len(linea)))
            archivo.seek(inicio)
            cola = archivo.read()
            if cola.endswith(linea):
                continue
            if cola and not cola.endswith(b'\n'):
                # Una interrupción dejó incompleta la última escritura.
                corte = cola.rfind(b'\n') + 1
                if inicio and not corte:
                    raise OSError('No se pudo recuperar la última línea en ' + str(ruta))
                archivo.truncate(inicio + corte)
            archivo.write(linea)
            archivo.flush()
            os.fsync(archivo.fileno())
