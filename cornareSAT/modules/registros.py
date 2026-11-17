import queue
import time

def crearColas():
    return {
        'local': queue.Queue(),
        'xbee': queue.Queue(),
        'identificacion': queue.Queue()
    }


def guardarRegistro(colas, tipo, origen, valores):
    colas[tipo].put({'tipo': tipo, 'origen': origen,
                     'ts': time.time_ns() // 1_000_000, 'datos': valores})


def obtenerPendiente(colas, dar_turno_remoto=False):
    # Tres turnos favorecen al dato local; el cuarto favorece a XBee.
    # Cada grupo conserva su orden.
    prioridades = ("xbee", "local", "identificacion") if dar_turno_remoto else (
        "local", "xbee", "identificacion"
    )
    for tipo in prioridades:
        try:
            return colas[tipo].get_nowait()
        except queue.Empty:
            continue
    return None


