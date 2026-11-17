import serial
import time
import re
import logging


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

def measure():
    try: 
        with serial.Serial('/dev/maxbotix', 9600, timeout=1) as ser:
            data = ser.read_until(b'\r')
        range = data[1:-1] #Don't include the first and last character ('R' and '\r')
        range = int(range)
        #print(range*0.1)
        return a_centimetros(range)
    except:
        print("Error decoding value!")
        return 888.8

#measure()
        
