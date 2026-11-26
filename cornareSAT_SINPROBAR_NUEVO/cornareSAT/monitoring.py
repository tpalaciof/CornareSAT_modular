import sys
sys.path.append('/home/pi/cornareSAT/utils')
import datetime
import time
import csvwritingv2 as csvwriting
import sampling_time
import logging
import loggingTelegraf as lt
import json
import os
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
import speedsd
import INA
import modem
from dotenv import load_dotenv
from pathlib import Path

CARPETA_DATOS = Path('/home/pi/datalogger')
CARPETA_MONITOREO = CARPETA_DATOS / 'monitoreo'
ARCHIVO_RESPALDO = CARPETA_MONITOREO / 'backup_monitoreo.csv'

# Config logs
log_file = "/var/log/python_errors.log" 
logger = logging.getLogger("PythonLogger")
logger.setLevel(logging.INFO)
file_handler = logging.FileHandler(log_file)
file_handler.setFormatter(lt.JSONFormatter())
logger.addHandler(file_handler)

console_handler = logging.StreamHandler()
console_handler.setFormatter(lt.JSONFormatter())
logger.addHandler(console_handler)

'''
Load credentials to connect to Influxdb
'''
load_dotenv('/home/pi/cornareSAT/credentials/.env')
url = os.getenv('HOST_DB')
token = os.getenv('TOKEN')
bucket = os.getenv('BUCKET')
org = os.getenv('ORG')

#Load settings file
file = '/home/pi/cornareSAT/credentials/settings.json'
with open(file, 'r') as archivo:
    settings = json.load(archivo)
code = settings['CODE']
municipio = settings['MUNICIPIO']
nombre = settings['NAME']
sampletime = settings['SAMPLETIME_MONITORING']

CARPETA_MONITOREO.mkdir(parents=True, exist_ok=True)
for origen in (*CARPETA_DATOS.glob('monitoreo????-??-??.csv'),
               CARPETA_DATOS / ARCHIVO_RESPALDO.name):
    if not origen.is_file():
        continue
    destino = CARPETA_MONITOREO / origen.name
    numero = 2
    while destino.exists():
        destino = CARPETA_MONITOREO / f'{origen.stem}_{numero}{origen.suffix}'
        numero += 1
    origen.rename(destino)

def meassures(command, path,replace1,replace2):

    os.system(command+ ' > '+path)
    with open(path,'r') as f:
        f = f.read()
    
    if replace1 == "" and replace2 == "":
        result = f
    elif replace2 == "":
        result = f.replace(replace1,'')
    else:
        result = f.replace(replace1,"").replace(replace2,"")
    os.remove(path)
    return result

print(f'sampletime: {sampletime}')

while True:
    '''
    Wait for sample time. If the 2nd parameter can be: seconds or minutes
    '''
    print('antes')
    
    ######## cambiar muestreo
    sampling_time.delay(sampletime, 'minutes')
    print('despues')
    
    
    try:
        temp = meassures("vcgencmd measure_temp", "/home/pi/cornareSAT/logs/temperatura.txt","temp=","'C")
        #print(temp)    
        cpu = meassures("top -d 0,5 -b -n2 | grep 'Cpu(s)' | tail -n 1 | awk '{print $2 + $4}'","/home/pi/cornareSAT/logs/cpu.txt","","")

        sd = meassures("df -h | grep '/dev/mmcblk0p2' | awk '{print $5}' | cut -c 1-2", "/home/pi/cornareSAT/logs/sd.txt","","")
        #print(sd)

        ram = meassures("free | grep Mem | awk '{print 100*($3)/$2}'", "/home/pi/cornareSAT/logs/ram.txt","","")

        swap = meassures("free | grep Swap | awk '{print 100*($3)/$2}'","/home/pi/cornareSAT/logs/swap.txt","","")

        err_volt = meassures("vcgencmd get_throttled", "/home/pi/cornareSAT/logs/error_voltaje.txt",'throttled=0x',"")
        err_volt = err_volt.rstrip()

        uptime = meassures("uptime -p", "/home/pi/cornareSAT/logs/uptime.txt","","")
        uptime = uptime.rstrip()
        
        try:
            v_bat, c_bat, v_panel, c_panel = INA.measure_energy()
            pot_panel = v_panel*c_panel/1000
        except Exception as e:
            logger.error(f'Falla en la medición de parametros de energía por la excepción: {e}')
            v_bat = -999
            c_bat = -999
            v_panel = -999
            c_panel = -999
            pot_panel = -999
        
            
        speed_sd = speedsd.get_speed()
        if speed_sd == -1:
            logger.error("Error en la medición de la velocidad de escritura de la sd: {e}")

        try:
            rssi, red, snr = modem.metrics_modem()
            #rssi = float(rssi)/10
        except Exception as e:
            logger.error(f"Falló en la medición de parametros de red por excepción: {e}")
            rssi = -999
            red = "null"
            snr = -999
        
    except Exception as e:
        logger.error(f"Falló en la medición de los parametros por la excepción {e}")
        rssi = -999
        red = "null"
        snr = -999
    
    now = datetime.datetime.utcnow()
    header = ["Fecha","volt_bateria","corriente_carga","volt_panel","I_panel","pot_panel","rssi","updatime","snr","red","tempInt","cpu","ram","swap","sdcard","speed_sd","volt_error"]
    data = [now, float(v_bat), float(c_bat), float(v_panel), float(c_panel), float(pot_panel), float(rssi), uptime, float(snr), red, float(temp), float(cpu), float(ram), float(swap), float(sd), float(speed_sd), str(err_volt)]
    
    try:

        # Crear cliente de InfluxDB
        client = InfluxDBClient(url=url, token=token, org=org)
        write_api = client.write_api(write_options=SYNCHRONOUS)  

        respaldos = sorted(CARPETA_MONITOREO.glob('backup_monitoreo_*.csv'))
        for file in (*respaldos, ARCHIVO_RESPALDO):
            my_file = Path(file)
            if not my_file.is_file():
                continue
            print('entra al if backup')
            #try:
            my_file = Path(file)
            if not my_file.is_file():
                pass
                
            else:
                path = open(file, 'r')
                file_list = (path.read()).split('\n')
                fields_number = len(file_list[0].split(';'))
                try:
                    file_list.remove(';'*(fields_number-1)) 
                except:
                    pass
                file_list = [x for x in file_list if x != '']
                file_list.pop(0)
                
                points = []                                                                                                                                                    
                for data1 in file_list:

                    data1 = data1.split(';')
                    for i in range (0, len(data1)):
                        try:
                            data1[i] = float(data1[i])
                        except Exception as e:
                            pass
                    
                    point = Point("measures") \
                        .tag("Codigo", code) \
                        .tag("Nombre_estacion", nombre)\
                        .tag("Municipio", municipio) \
                        .field("volt_bateria", float(data1[1])) \
                        .field("corriente_carga", float(float(data1[2]))) \
                        .field("volt_panel", float(data1[3]) )\
                        .field("corriente_panel", float(data1[4]) )\
                        .field("potencia_panel", float(data1[5]) )\
                        .field("rssi", float(data1[6]) ) \
                        .field("updatime",data1[7]) \
                        .field("snr",float(data1[8]))\
                        .field("red", data1[9])\
                        .field("temperatura", float(data1[10])) \
                        .field("cpu", float(data1[11])) \
                        .field("ram", float(data1[12])) \
                        .field("swap", float(data1[13])) \
                        .field("sdcard", float(data1[14])) \
                        .field("speedw_sd", float(data1[15])) \
                        .field("throttled", str(data1[16])) \
                        .time(data1[0])
                    points.append(point)

                write_api.write(bucket=bucket, org=org, record=points)
                path.close()
                os.remove(file)
            
                logger.info("Datos del archivo de respaldo escritos en InfluxDB y archivo eliminado.")
                time.sleep(0.1)
            
            '''      
            except Exception as e:
                logger.warning(f"Error Enviando los datos de backup: {e}")
                path.close()
                
                #Write data in a backup file
                
                if not csvwriting.verifyDuplications('/home/pi/datalogger/backup_monitoreo.csv', data):
                    try:
                        csvwriting.writeFile('/home/pi/datalogger/backup_monitoreo.csv',
                                            header, data)
                        print('New data was registered in backup file. When connection'
                            'to database is restarted, data will be written from csv.')
                    except Exception as e:
                        print(e)
                    
                else:
                    print('Data is already registered in backup file. No new rows were registered.')
                        #return False
            '''            

        print('entra al if hora actual')    
        point = Point("measures") \
            .tag("Codigo", code) \
            .tag("Nombre_estacion", nombre)\
            .tag("Municipio", municipio) \
            .field("volt_bateria", data[1]) \
            .field("corriente_carga", data[2]) \
            .field("volt_panel", data[3]) \
            .field("corriente_panel", data[4]) \
            .field("potencia_panel", data[5]) \
            .field("rssi", data[6])  \
            .field("updatime",data[7]) \
            .field("snr", data[8]) \
            .field("red", data[9]) \
            .field("temperatura", data[10]) \
            .field("cpu", data[11]) \
            .field("ram", data[12]) \
            .field("swap", data[13]) \
            .field("sdcard", data[14]) \
            .field("speedw_sd", data[15]) \
            .field("throttled", data[16]) \
            .time(data[0])

        write_api.write(bucket=bucket, org=org, record=point)
        logger.info("Datos enviados exitosamente a InfluxDB.")

        client.close()
        
    except Exception as e:
        
        logger.warning(f'Falló conexión con base de datos por excepción: {e}, guardando en archivo backup')

        '''
        Write data in a backup file
        '''
        if not csvwriting.verifyDuplications(ARCHIVO_RESPALDO, data):
            try:
                csvwriting.writeFile(ARCHIVO_RESPALDO,
                                     header, data)
                print('New data was registered in backup file. When connection'
                      'to database is restarted, data will be written from csv.')
            except Exception as e:
                print(e)
            
        else:
            print('Data is already registered in backup file. No new rows were registered.')

    
    '''
    Write data in file
    '''
    try:
        filename = CARPETA_MONITOREO / ('monitoreo'+datetime.datetime.strftime(datetime.datetime.now(),'%Y-%m-%d')+'.csv')
        if not csvwriting.verifyDuplications(filename,data):
            data_written = csvwriting.writeFile(filename, header, data)
                
    except Exception as e:
        logger.warning(f"El dato no se almacenó en el archivo diario por: {e}")

