#!/usr/bin/env python3
"""Entrada integrada. No instala ni modifica servicios systemd."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent / 'utils'))
import logging
import math
import os
import signal
import threading
import loggingTelegraf as lt
from configuracion import CONFIGURACION, settings
LOG = logging.getLogger("PythonLogger")
from configuracion import cargar
from moduls.registros import crearColas
from moduls.medicion_nivel import tarea_sensor
from moduls.medicion_lluvia import tarea_lluvia
from moduls.recepcion_Xbee import tarea_xbee
from moduls.salida import tarea_salida

from tunel import iniciarTunel


def main():
    cargar()
    if CONFIGURACION['H_RAIN']:
        puertos = [CONFIGURACION['xbee'], CONFIGURACION['sensor_lluvia']]
        if CONFIGURACION['nivel_local'] and CONFIGURACION['H_LEVEL']:
            puertos.append(CONFIGURACION['sensor'])
        if len(set(map(os.path.realpath, puertos))) != len(puertos):
            LOG.error('Los sensores y XBee requieren puertos distintos.')
            return 1
    lt.configurar(ajustes=settings)
    # Config logs
    LOG.setLevel(logging.INFO)
    LOG.propagate = False
    formato = lt.JSONFormatter()
    consola = logging.StreamHandler()
    consola.setLevel(logging.INFO if CONFIGURACION['ver_xbee'] else logging.WARNING)
    consola.setFormatter(formato)
    LOG.addHandler(consola)
    try:
        archivo = logging.FileHandler(CONFIGURACION['log_file'])
        archivo.setFormatter(formato)
        LOG.addHandler(archivo)
    except OSError as error:
        LOG.warning('No se pudo abrir el registro de Telegraf %s: %s', CONFIGURACION['log_file'], error)

    if CONFIGURACION['nivel_local'] and CONFIGURACION['H_LEVEL'] and (
            os.path.realpath(CONFIGURACION['sensor']) == os.path.realpath(CONFIGURACION['xbee'])):
        LOG.error('Sensor y XBee requieren puertos seriales diferentes')
        return 1
    if CONFIGURACION['nivel_local'] and not CONFIGURACION['H_LEVEL']:
        calibracion = CONFIGURACION['calibracion']
        if not all(math.isfinite(v) for v in calibracion) or calibracion[0] == calibracion[1]:
            LOG.error('Calibración ADC no válida')
            return 1
    try:
        import serial  # noqa: F401
    except ImportError:
        LOG.error("Falta pyserial. Instalar en el entorno: python -m pip install pyserial==3.5")
        return 1

    CONFIGURACION['carpeta_csv'].mkdir(parents=True, exist_ok=True)
    # Impide dos instancias ejecutando este mismo programa.
    # En Raspberry Pi OS se dispone de flock. Los puertos también son exclusivos.
    import fcntl
    with open(Path(__file__).resolve(), 'r', encoding='utf-8') as bloqueo:
        try:
            fcntl.flock(bloqueo.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            LOG.error("Ya hay una instancia ejecutando este programa.")
            return 1

        tunnel = iniciarTunel(CONFIGURACION)
        colas = crearColas()
        detener = threading.Event()
        finalizarSalida = threading.Event()
        resultado = 0

        def terminar(numero, marco):
            detener.set()

        sigintAnterior = signal.signal(signal.SIGINT, terminar)
        sigtermAnterior = signal.signal(signal.SIGTERM, terminar)
        hiloSensor = None
        if CONFIGURACION['nivel_local']:
            hiloSensor = threading.Thread(target=tarea_sensor, args=(detener, colas), daemon=True)
        hiloXBee = threading.Thread(target=tarea_xbee, args=(detener, colas), daemon=True)
        hiloSalida = threading.Thread(target=tarea_salida, args=(finalizarSalida, colas), daemon=True)
        if CONFIGURACION['nivel_local']:
            LOG.info('Inicio de nivel: sensor=%s, código=%s, intervalo=%s s',
                     'TTL' if CONFIGURACION['H_LEVEL'] else 'ADS1015 analógico', CONFIGURACION['codigo'], CONFIGURACION['intervalo'])
        else:
            LOG.info('Nivel local desactivado; recepción XBee habilitada.')
        hiloLluvia = None
        if CONFIGURACION['H_RAIN']:
            hiloLluvia = threading.Thread(target=tarea_lluvia, args=(detener, colas), daemon=True)
        try:
            if hiloLluvia:
                hiloLluvia.start()
            hiloSalida.start()
            if hiloSensor:
                hiloSensor.start()
            hiloXBee.start()
            while not detener.wait(0.5):
                if (hiloSensor is not None and not hiloSensor.is_alive()) or not hiloXBee.is_alive() or not hiloSalida.is_alive() or (hiloLluvia and not hiloLluvia.is_alive()):
                    LOG.error('Una tarea terminó inesperadamente. Se detiene el programa.')
                    resultado = 1
                    break
        finally:
            detener.set()
            # Primero terminan las lecturas; después se vacían las colas al CSV.
            if hiloSensor is not None and hiloSensor.ident is not None:
                hiloSensor.join(timeout=6.0)
            if hiloXBee.ident is not None:
                hiloXBee.join(timeout=6.0)
            if (hiloSensor is not None and hiloSensor.is_alive()) or hiloXBee.is_alive():
                LOG.error('No terminó la lectura del sensor o del XBee.')
                resultado = 1
            if hiloLluvia and hiloLluvia.ident is not None:
                hiloLluvia.join()
            finalizarSalida.set()
            if hiloSalida.ident is not None:
                hiloSalida.join()
            signal.signal(signal.SIGINT, sigintAnterior)
            signal.signal(signal.SIGTERM, sigtermAnterior)
            if tunnel is not None and tunnel.poll() is None:
                tunnel.terminate()
        return resultado


if __name__ == '__main__':
    raise SystemExit(main())
