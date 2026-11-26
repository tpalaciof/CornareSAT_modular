import logging
import math
import queue
import re
import sqlite3

import interpretarTramasXbee as xbee
from configuracion import CONFIGURACION

LOG = logging.getLogger("PythonLogger")


def validarMedicion(trama):
    campo = 'nivel' if 'nivel' in trama else 'precipitacion'
    if set(trama) != {campo, 'codigo', 'id', 'ts'}:
        raise ValueError('Se esperan la medida, codigo, id y ts del ESP32')
    if not isinstance(trama['codigo'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', trama['codigo']):
        raise ValueError('Código de estación inválido')
    if not isinstance(trama['id'], str) or not re.fullmatch(r'[0-9A-F]{8}-[0-9A-F]{8}', trama['id']):
        raise ValueError('ID de lectura inválido')
    if type(trama['ts']) is not int or not 0 < trama['ts'] < 253402214400000:
        raise ValueError('Marca de tiempo inválida')
    if type(trama[campo]) not in (int, float) or not math.isfinite(trama[campo]):
        raise ValueError('Medida inválida')


def abrirHistorico(carpeta):
    # Cada lectura queda guardada con los milisegundos enviados por el nodo.
    db = sqlite3.connect(carpeta / 'lecturas_xbee.sqlite3')
    db.executescript("""
        CREATE TABLE IF NOT EXISTS lecturas (
            mac TEXT, id TEXT, codigo TEXT, campo TEXT, valor NUMERIC,
            ts INTEGER, fin INTEGER, pendiente INTEGER DEFAULT 1,
            PRIMARY KEY (mac, id)
        );
        CREATE INDEX IF NOT EXISTS por_enviar ON lecturas(pendiente) WHERE pendiente=1;
        CREATE INDEX IF NOT EXISTS por_intervalo ON lecturas(mac, codigo, fin);
        CREATE INDEX IF NOT EXISTS por_hora ON lecturas(mac, codigo, ts);
    """)
    return db


def guardarLectura(db, mac, trama):
    campo = 'nivel' if 'nivel' in trama else 'precipitacion'
    ts = trama['ts']
    fin = None
    if campo == 'nivel':
        intervalo = max(1, round(CONFIGURACION['intervalo'] * 1000))
        fin = (ts // intervalo + 1) * intervalo
    with db:
        db.execute("""INSERT INTO lecturas(mac,id,codigo,campo,valor,ts,fin)
                      VALUES (?,?,?,?,?,?,?) ON CONFLICT(mac,id) DO NOTHING""",
                   (mac, trama['id'], trama['codigo'], campo, trama[campo], ts, fin))


def siguienteSalida(db):
    # El ESP32 vacía su respaldo en orden. Una lectura posterior del mismo nodo
    # permite cerrar el intervalo anterior aunque llegue días después.
    fila = db.execute("""
        SELECT mac,id,codigo,campo,valor,ts,fin FROM lecturas AS l
        WHERE pendiente=1 AND (fin IS NULL OR EXISTS (
            SELECT 1 FROM lecturas AS otra WHERE otra.mac=l.mac
            AND otra.codigo=l.codigo AND otra.ts>=l.fin))
        ORDER BY l.rowid LIMIT 1
    """).fetchone()
    if fila is None:
        return None
    mac, clave, codigo, campo, valor, ts, fin = fila
    if fin is not None:
        # En empate prevalece el último valor medido, como en el acumulador original.
        moda = db.execute("""
            SELECT valor FROM lecturas WHERE mac=? AND codigo=? AND fin=?
            AND valor BETWEEN 0 AND ? GROUP BY valor
            ORDER BY count(*) DESC, max(ts) DESC, max(rowid) DESC LIMIT 1
        """, (mac, codigo, fin, CONFIGURACION['distancia_maxima_mm'])).fetchone()
        valor = moda[0] if moda else CONFIGURACION['valor_error_nivel']
        ts = fin
    return {'tipo': 'xbee', 'origen': mac, 'ts': ts, 'id': clave, 'fin': fin,
            'datos': {'trama_json': {campo: valor, 'codigo': codigo}}}


def marcarSalida(db, registro):
    mac = registro['origen']
    with db:
        if registro['fin'] is None:
            db.execute('UPDATE lecturas SET pendiente=0 WHERE mac=? AND id=?',
                       (mac, registro['id']))
        else:
            codigo = registro['datos']['trama_json']['codigo']
            db.execute('UPDATE lecturas SET pendiente=0 WHERE mac=? AND codigo=? AND fin=? AND pendiente=1',
                       (mac, codigo, registro['fin']))


def tarea_xbee(detener, colas):
    estado = {'puerto': None, 'proximo_intento': 0.0}
    try:
        while not detener.is_set():
            for registro in xbee.recibir(CONFIGURACION, estado):
                if registro['tipo'] == 'identificacion':
                    colas['identificacion'].put(registro)
                    continue
                mac = registro['origen']
                trama = registro['datos']['trama_json']
                if trama == {'pedir': 'hora'}:
                    xbee.responder(estado, mac, {})
                    continue
                try:
                    validarMedicion(trama)
                except (ValueError, OverflowError) as error:
                    LOG.warning('JSON XBee descartado: %s', error, extra=xbee.contextoNodo(mac))
                    continue
                xbee.CODIGOS_LOG_XBEE[mac] = trama['codigo']
                colas['xbee'].put(registro)

            while True:
                try:
                    mac, clave = colas['ack_xbee'].get_nowait()
                except queue.Empty:
                    break
                xbee.responder(estado, mac, {'ack': clave})
            if estado['puerto'] is None:
                detener.wait(0.05)
    finally:
        xbee.cerrarPuerto(estado)
