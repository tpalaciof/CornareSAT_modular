import serial
import time
import subprocess
from pathlib import Path

PUERTO_MODEM = '/dev/modem'

# Diccionarios de mapeo
csq = {i: -113 + 2 * i for i in range(2, 32)}
net = {'0': "No service", '1': "GSM", '2': "GPRS", '3': "EDGE", '4': "WCDMA", '5': "HSDPA", '6': "HSUPA", 
       '7': "HSPA", '8': "LTE"}

def kill_process_on_usb(device=PUERTO_MODEM):
    try:
        result = subprocess.run(['sudo', 'fuser', device], capture_output=True, text=True)
        if result.returncode != 0:
            return False
        for pid in result.stdout.strip().split():
            subprocess.run(['sudo', 'kill', pid])
        return True
    except Exception as e:
        print(f"[ERROR] kill_process_on_usb: {e}")
        return False

def send_command(modem, command, delay=1):
    modem.write((command + '\r').encode())
    time.sleep(delay)
    response = modem.readall().decode(errors='ignore')
    return response.strip()

def parse_csq(response):
    try:
        if "+CSQ:" in response:
            csq_value = response.split(":")[1].split(",")[0].strip()
            rssi_val = int(csq_value)
            return csq.get(rssi_val, -9999)
    except Exception:
        pass
    return -9999

def parse_network_type(response):
    try:
        if "+CNSMOD:" in response:
            net_code = ''.join(filter(str.isdigit, response.split(":")[1].split(",")[1]))
            print("Aca estamos " + net_code)
            print("Esta es la red "+net.get(net_code, "Unknown"))
            return net.get(net_code, "Unknown"), net_code
    except Exception:
        pass
    return "Unknown", "-1"

def parse_cpsi(response, net_code):
    try:
        parts = response.replace("OK", "").strip().split(",")
        if net_code == "8":  # LTE
            rssi = float(parts[-2]) / 10
            snr = parts[-1]
            return rssi, snr
        elif net_code in ["4", "5", "6", "7"]:  # WCDMA/HSPA/HSUPA
            rssi = float(parts[-2]) / 10
            snr = parts[-5]  # ECIO (en dB)
            return rssi, snr
    except Exception:
        pass
    return -9999, -9999

def metrics_modem():
    if not Path(PUERTO_MODEM).is_char_device():
        return -9999, "null", -9999

    kill_process_on_usb()
    time.sleep(0.5)

    try:
        with serial.Serial(PUERTO_MODEM, 115200, timeout=3) as modem:
            modem.flushInput()
            modem.flushOutput()
            time.sleep(0.5)

            csq_resp = send_command(modem, 'AT+CSQ')
            rssi = parse_csq(csq_resp)
            print(f"[INFO] CSQ Response: {csq_resp} -> RSSI: {rssi} dBm")

            net_resp = send_command(modem, 'AT+CNSMOD?')
            red, net_code = parse_network_type(net_resp)
            print(f"[INFO] CNSMOD Response: {net_resp} -> Network: {red}")

            if net_code in ["8", "7", "6", "5", "4"]:
                cpsi_resp = send_command(modem, 'AT+CPSI?')
                rssi_val, snr = parse_cpsi(cpsi_resp, net_code)
                print(f"[INFO] CPSI Response: {cpsi_resp}")
                return rssi_val, red, snr

            print("[WARN] No compatible network or unsupported mode.")
            return -9999, "No Network", -9999

    except Exception as e:
        print(f"[ERROR] metrics_modem: {e}")
        return -9999, "null", -9999

def metrics_modem_with_retry(retries=3, delay=2):
    for attempt in range(1, retries + 1):
        print(f"\n[INFO] Intento {attempt} de {retries}...")
        rssi, red, snr = metrics_modem()
        if rssi != -9999 and snr != -9999:
            print("[INFO] Lectura exitosa.")
            return rssi, red, snr
        print(f"[WARN] Lectura fallida. Reintentando en {delay} segundos...")
        time.sleep(delay)
    print("[ERROR] Fallaron todos los intentos de lectura del modem.")
    return -9999, "null", -9999

# Uso
rssi, red, snr = -9999, "null", -9999
if Path(PUERTO_MODEM).is_char_device():
    rssi, red, snr = metrics_modem_with_retry()
#print(f"RSSI: {rssi} dBm, Red: {red}, SNR: {snr}")
