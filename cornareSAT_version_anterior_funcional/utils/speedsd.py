import os
import time
import json
from datetime import datetime

# Constantes
TEST_FILE = "/home/pi/cornareSAT/logs/test_speed.tmp"
OUTPUT_FILE = "/home/pi/cornareSAT/logs/dd_output.txt"
CACHE_FILE = "/home/pi/cornareSAT/logs/write_speed_cache.json"
BLOCK_SIZE = 4 * 1024 * 1024  # 4 MB
FILE_SIZE_MB = 100

# Momentos exactos en que se permite medir: 06:00 y 18:00
ALLOWED_TIMES = [("06", "00"), ("18", "00")]

def measure_write_speed():
    """Mide la velocidad de escritura en MB/s"""
    os.system(f"dd if=/dev/zero of={TEST_FILE} bs={BLOCK_SIZE} count={FILE_SIZE_MB // 4} conv=fdatasync 2> {OUTPUT_FILE}")

    try:
        with open(OUTPUT_FILE, "r") as f:
            output = f.readlines()[-1]
        speed = float(output.split(",")[-1].strip().split(" ")[0])
    except Exception:
        speed = -1  # Error en la medicion

    # Limpiar archivos temporales
    if os.path.exists(TEST_FILE):
        os.remove(TEST_FILE)
    if os.path.exists(OUTPUT_FILE):
        os.remove(OUTPUT_FILE)

    return speed

def save_cache(speed, timestamp):
    data = {"speed": speed, "timestamp": timestamp}
    with open(CACHE_FILE, "w") as f:
        json.dump(data, f)

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return None
    with open(CACHE_FILE, "r") as f:
        return json.load(f)

def get_speed():
    now = datetime.now()
    hh, mm = now.strftime("%H"), now.strftime("%M")

    if (hh, mm) in ALLOWED_TIMES:
        speed = measure_write_speed()
        save_cache(speed, now.isoformat())
        print(f"[Medido a las {hh}:{mm}] Velocidad de escritura: {speed} MB/s")
    else:
        cache = load_cache()
        if cache:
            speed = cache["speed"]
            print(f"[Cache] Ultima medicion a las {cache['timestamp']}: {speed} MB/s")
        else:
            speed = -1
            print("[Error] No hay datos en la cache.")
    return speed

# Uso de la variable
'''
if __name__ == "__main__":
    speed = get_speed()
    # Usar la variable speed para lo que necesites
    print(f"Velocidad usada: {speed} MB/s")
'''