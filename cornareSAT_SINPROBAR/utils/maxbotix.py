import re
import logging
import os
LOG = logging.getLogger("PythonLogger")


def abrir_puerto(ruta, baudios):
    import serial
    opciones = dict(port=ruta, baudrate=baudios, bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE, stopbits=serial.STOPBITS_ONE,
                    timeout=0.1, write_timeout=0.25)
    if os.name == "posix":
        opciones["exclusive"] = True
    return serial.Serial(**opciones)


def cerrar_puerto(puerto):
    if puerto is not None:
        try:
            puerto.close()
        except OSError:
            LOG.warning("No se pudo cerrar un puerto", exc_info=True)


def decodificar_tramas(datos, buffer):
    buffer.extend(datos)
    lecturas = []
    while b'\r' in buffer:
        trama, _, resto = buffer.partition(b'\r')
        buffer[:] = resto
        inicio = trama.rfind(b'R')
        candidato = bytes(trama[inicio:]) if inicio >= 0 else bytes(trama)
        if re.fullmatch(rb'R[0-9]{4}', candidato):
            lecturas.append(int(candidato[1:]))
        else:
            logging.getLogger('PythonLogger').warning('Trama local no válida: %r', bytes(trama))
    if len(buffer) > 64:
        buffer[:] = buffer[-5:]
    return lecturas


def a_centimetros(distancia_mm):
    # La API original de nivel.py expresa el sensor TTL en centímetros.
    return round(distancia_mm / 10.0, 2)
