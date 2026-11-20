"""
chronos1.py

Se ejecuta cuando la raspberry se enciende por primera vez,
su objetivo es verificar cada minuto la conexión a internet
hasta que esta sea exitosa, cuando logra una buena conexión
realiza configuración de fecha y hora de la estación, además
configura la contraseña de acceso por teamviewer.

Modificado por: Jefferson David.

"""

################### Importar Librerías ###################
import urllib.request
import urllib.parse
import os
import time

################### Definición de funciones ###################

#Función para configuración de hora en la estación
def setDateTime():
    url = 'http://172.235.149.138/chronos.php'
    f = urllib.request.urlopen(url)
    response = f.read().decode('utf-8')
    print(response)
   # print(datetime)
    #date = '20'+datetime[:2]+'-'+datetime[2:4]+'-'+datetime[4:6]
    #time = datetime[6:8]+':'+datetime[8:10]+':'+datetime[10:12]
    datetimenow = response

    comand = 'sudo date --set "'+datetimenow+'"'
    print(comand)
    os.system(comand)

#Función que verifica conexión a internet
def validateConection():
    os.system('ping -c 4  8.8.8.8 > /home/pi/cornareSAT/logs/pingStatus.txt')

    with open('/home/pi/cornareSAT/logs/pingStatus.txt','r') as f:
        f = f.read()

    resultadoPing = f.split('\n')

    for linea in resultadoPing:
        if linea.find("4 received, 0% packet loss") != -1:
            print ('PING EXITOSO')
            return True
            break

    return False


################### MAIN ####################

setDate = False

while (not setDate):
    if (validateConection()):
        setDateTime()
        setDate = True
    else:
        print('Trying to set date and teamviewer pass...')
        time.sleep(60)
