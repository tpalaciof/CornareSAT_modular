# Nueva configuración de la imagen

## 1. Cambios en los servicios

El propósito era que la Raspberry ejecutara `main.py` automáticamente al encenderse, igual que antes ejecutaba `nivel.py`. Para esto, reutilizamos `nivel.service` porque ya estaba configurado para ejecutar el programa como usuario `pi`, usar el Python de `venv` y guardar la salida en los logs.

Antes, `nivel.service` arrancaba `nivel.py` y `rain.service` arrancaba `rain.py` como un proceso separado. De esta manera, si `RAIN` estaba en `true`, dentro de `nivel.py` se activaba el servicio `rain.service` y `rain.py` quedaba en ejecución, donde el propio programa esperaba entre lecturas según `SAMPLETIME_RAIN`.

Ahora, todo esto quedó integrado dentro de `main.py`, el cual se encarga del pluviómetro local cuando `RAIN` está en `true` y del sensor de nivel local cuando `LEVEL` está en `true`. Debido a esto, `rain.service` quedó deshabilitado. Si los dos procesos estuvieran activos, intentarían leer el mismo puerto y se generarían conflictos.

### Servicios actuales

| Servicio | Qué hace en CornareSAT |
| --- | --- |
| `main.service` | Ejecuta `main.py`. Mide el nivel local si `LEVEL` está activo, mide la lluvia local si `RAIN` está activo y recibe lecturas de nivel o lluvia de los nodos XBee. Publica las mediciones por MQTT y guarda el histórico y los envíos pendientes en CSV. |
| `monitoring.service` | Ejecuta `monitoring.py`. Registra el estado de la estación, como batería, panel solar, temperatura, CPU, memoria, tarjeta SD y señal del módem. Envía esos datos a InfluxDB y guarda sus CSV en `/home/pi/datalogger/monitoreo/`. |

### 1.1. Preparar la carpeta de logs y detener la lluvia anterior

```bash
mkdir -p /home/pi/cornareSAT/logs
sudo systemctl stop rain.service
```

### 1.2. Configurar el servicio para ejecutar main.py

```bash
sudo systemctl edit nivel.service
```

Añade el siguiente contenido al archivo de edición.

```ini
[Service]
ExecStart=
ExecStart=/home/pi/cornareSAT/venv/bin/python /home/pi/cornareSAT/main.py
```

#### Alternativa si el editor no permite guardar

Crea directamente el archivo `override.conf` con este bloque.

```bash
sudo mkdir -p /etc/systemd/system/nivel.service.d
sudo tee /etc/systemd/system/nivel.service.d/override.conf >/dev/null <<'EOF'
[Service]
ExecStart=
ExecStart=/home/pi/cornareSAT/venv/bin/python /home/pi/cornareSAT/main.py
EOF
```

### 1.3. Arrancar y verificar el servicio

```bash
sudo systemctl daemon-reload
sudo systemctl restart nivel.service
systemctl status nivel.service --no-pager -l
```

Para seguir los logs, ejecuta este comando. Pulsa `Ctrl+C` para salir del seguimiento y continuar con los siguientes pasos.

```bash
tail -F /home/pi/cornareSAT/logs/nivel.log /home/pi/cornareSAT/logs/nivel_error.log
```

### 1.4. Deshabilitar el servicio de lluvia antiguo

```bash
sudo systemctl disable --now rain.service
```

### 1.5. Cambiar el nombre de nivel.service a main.service

```bash
sudo cp /etc/systemd/system/nivel.service /etc/systemd/system/main.service
sudo mkdir -p /etc/systemd/system/main.service.d
sudo cp /etc/systemd/system/nivel.service.d/override.conf /etc/systemd/system/main.service.d/
sudo systemctl daemon-reload
systemctl show main.service -p User -p ExecStart
```

Si la salida muestra `User=pi` y `/home/pi/cornareSAT/main.py` en `ExecStart`, apaga el servicio anterior y activa el nuevo.

```bash
sudo systemctl disable --now nivel.service && sudo systemctl enable --now main.service
systemctl status main.service --no-pager
```

### 1.6. Actualizar la descripción del servicio

```bash
sudo sed -i 's/^Description=.*/Description=Servicio para ejecutar main.py en un entorno virtual/' /etc/systemd/system/main.service
sudo systemctl daemon-reload
sudo systemctl restart main.service
systemctl status main.service --no-pager
```

## 2. Cambios en los puertos

Debido a que se añadió el XBee, un nuevo dispositivo que ocupa un puerto más, fue necesario cambiar la asignación de los puertos seriales para identificar correctamente cada equipo y evitar conflictos entre ellos.

La Raspberry asigna nombres como `/dev/ttyUSB0`, `/dev/ttyUSB1` y `/dev/ttyUSB2`, que pueden variar al desconectar los dispositivos o reiniciar el equipo. Por eso, se configuraron reglas `udev` que permiten utilizar nombres específicos en el programa.

| Nombre utilizado en el programa | Dispositivo |
| --- | --- |
| `/dev/xbee` | Receptor XBee. |
| `/dev/maxbotix` | Sensor de nivel local. |
| `/dev/rain` | Sensor de lluvia local. |

Estos nombres están asociados al **puerto USB físico** donde se conecta cada dispositivo. Así, el programa puede encontrar cada equipo aunque cambie su número `ttyUSB`. Para conservar esta identificación, cada dispositivo debe permanecer conectado al puerto USB físico que se le asignó.

### 2.1. Configurar las reglas udev

```bash
sudo python3 - <<'PY'
from pathlib import Path
import re

carpeta = Path('/etc/udev/rules.d')
nueva = carpeta / '99-zz-cornaresat-serial.rules'
alias_viejo = re.compile(r',\s*SYMLINK\s*(?:\+=|:=|=(?!=))\s*"(?:rain|maxbotix)"(?=\s*(?:,|$))')
asignacion = re.compile(r'[\w{}.-]+\s*(?:[+:-]=|=(?!=))')

for archivo in carpeta.glob('*.rules'):
    if archivo == nueva or archivo.is_symlink():
        continue
    original = archivo.read_text()
    lineas = []
    for linea in original.splitlines(keepends=True):
        corregida = linea if linea.lstrip().startswith('#') else alias_viejo.sub('', linea)
        if corregida != linea and not asignacion.search(re.sub(r'"[^"\n]*"', '""', corregida)):
            corregida = '# ' + linea
        lineas.append(corregida)
    corregido = ''.join(lineas)
    if corregido != original:
        respaldo = archivo.with_suffix('.rules.antes-cornaresat')
        if not respaldo.exists():
            respaldo.write_text(original)
        archivo.write_text(corregido)

respaldo = nueva.with_suffix('.rules.antes-cornaresat')
if nueva.exists() and not respaldo.exists():
    respaldo.write_bytes(nueva.read_bytes())

nueva.write_text('''SUBSYSTEM=="tty", ENV{ID_PATH}=="platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.2:1.0", SYMLINK+="xbee"
SUBSYSTEM=="tty", ENV{ID_PATH}=="platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.3:1.0", SYMLINK+="maxbotix"
SUBSYSTEM=="tty", ENV{ID_PATH}=="platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.4:1.0", SYMLINK+="rain"
''')
PY
```

### 2.2. Recargar las reglas y verificar los nombres

```bash
sudo udevadm control --reload-rules
sudo udevadm trigger --action=add --subsystem-match=tty --sysname-match='ttyUSB[012]'
sudo udevadm settle --timeout=10
ls -l /dev/xbee /dev/maxbotix /dev/rain
```
