"""
check_status.py

    Versión: 3

    Script verifica cada 10 minutos estado de la conexión a internet.
    
    En caso de no tener reinicia Dongle con el fin de forzar la
    búsqueda de enlace entre el dongle y la radio base.

    Elaborado: Jefferson David
    
"""

################### Importar Librerías ###################
import os
import subprocess
import time
import datetime
from pathlib import Path

PUERTO_MODEM = '/dev/modem'


################### Definición de funciones ###################

#Función que libera el puerto /dev/modem
def kill_process_on_usb(device=PUERTO_MODEM):
    try:
        # Ejecutar fuser para obtener el PID
        result = subprocess.run(['sudo', 'fuser', device], capture_output=True, text=True)
        # Revisar si hubo un error al ejecutar fuser
        if result.returncode != 0:
            print(f"No se encontraron procesos usando {device} o hubo un error.")
            return False
            
        else:    
            # Obtener el PID desde la salida
            pids = result.stdout.strip().split()
            # Matar cada proceso encontrado
            for pid in pids:
                print(f"Terminando proceso {pid} en {device}...")
                subprocess.run(['sudo', 'kill', pid])

            print(f"Todos los procesos en {device} han sido terminados.")
            return True

        

    except Exception as e:
        print(f"Ocurrió un error: {e}")

#Función que reinicia el Dongle, recibe como parámetro de entrada número
#de bus de dongle
def reiniciarDongle():
    muerte_proceso = kill_process_on_usb()
    if muerte_proceso:
        time.sleep(1)
    try:
        puerto = os.open(PUERTO_MODEM, os.O_WRONLY | os.O_NOCTTY)
        try:
            os.write(puerto, b'AT+CFUN=1,1\r\n')
        finally:
            os.close(puerto)
    except OSError as error:
        print(f"No se pudo reiniciar el módem en {PUERTO_MODEM}: {error}")

     


################### MAIN ###################

#Aquí se debe asignar a la variable numeroUSB el numero bus-device
#asociado al dongle, este número se puede consultar con el comando
# > dmesg | tail
#el número será el que esta asociado al resultado HUAWEI
numeroUSB = '1-1'
rebootDongle = True

#verifica conexión a internet
os.system('ping -c 4  google.com > /home/pi/cornareSAT/logs/pingStatus1.txt')

with open('/home/pi/cornareSAT/logs/pingStatus1.txt','r') as f:
    f = f.read()

resultadoPing = f.split('\n')


for linea in resultadoPing:
    if linea.find("4 received, 0% packet loss") != -1:
        print ('PING EXITOSO')
        rebootDongle = False
        break

#después de validar conexión establece si reinicia dongle o consuta datos
if rebootDongle and Path(PUERTO_MODEM).is_char_device():
    reiniciarDongle()
    time.sleep(40)
    os.system("sudo dhclient -v usb0")
    time.sleep(30)
    os.system("sudo route add default gw 192.168.225.1 usb0")
