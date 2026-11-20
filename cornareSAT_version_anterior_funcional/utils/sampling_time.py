import time
import datetime
import math


def segundos(sample_time, unit='minutes'):
    intervalo = float(sample_time) * (1.0 if unit == 'seconds' else 60.0)
    if not math.isfinite(intervalo) or intervalo <= 0:
        raise ValueError('El tiempo de muestreo debe ser positivo y finito')
    return intervalo


def iniciar_intervalo(sample_time, unit='minutes'):
    return time.monotonic() + segundos(sample_time, unit)


def avanzar_intervalo(proximo, ahora, sample_time, unit='minutes'):
    intervalo = segundos(sample_time, unit)
    return proximo + (int((ahora - proximo) // intervalo) + 1) * intervalo

def delay(sample_time, unit='minutes'):
    now = datetime.datetime.now()

    if unit == 'seconds':
        total_seconds = now.minute * 60 + now.second
        next_trigger = ((total_seconds // sample_time) + 1) * sample_time
        delta = next_trigger - total_seconds
    else:  # 'minutes'
        total_minutes = now.hour * 60 + now.minute
        next_trigger = ((total_minutes // sample_time) + 1) * sample_time
        delta = (next_trigger - total_minutes) * 60 - now.second  # en segundos

    if delta > 0:
        time.sleep(delta)
'''
if __name__ == '__main__':
    sample_time = 60  # minutos
    while True:
        delay(sample_time, 'minutes')
        print(datetime.datetime.now())
'''
