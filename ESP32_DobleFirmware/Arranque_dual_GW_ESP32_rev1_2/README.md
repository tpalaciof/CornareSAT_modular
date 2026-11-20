# Arranque dual GLIMA para CONTROL_COMM rev. 1.2

La tarjeta objetivo es la **ESP32-WROOM-32E-N16 con 16 MiB de flash**. Se instala un selector de arranque por USB. **NORMAL** inicia el firmware existente del pluviógrafo, con su selección habitual entre `app0` y `app1`. **XBEE** inicia el firmware de `xbee/src/main.cpp`. La elección se conserva al desconectar el USB, reiniciar o cortar la alimentación.

Se conserva el código y la asignación de pines del pluviógrafo. Los siguientes cambios son archivos independientes para el gestor de arranque, la tabla de flash y el programa XBee.

| Archivo o carpeta | Función |
|---|---|
| `selector.py` | Instalar los archivos del arranque dual y cambiar el modo por USB. |
| `arranque/` | Gestor de arranque basado en ESP-IDF v4.4.7 y tabla de particiones. |
| `xbee/` | Programa XBee para compilar con PlatformIO y Arduino ESP32. |

## Instalación inicial por USB

1. Conecta la tarjeta por su micro-USB y aliméntala con su conexión habitual de batería. El USB de esta tarjeta alimenta el CP2102. Cierra el monitor serial mientras usas el selector.
2. Usa una tarjeta que ya tenga instalado el pluviógrafo con la tabla original de 16 MiB. Para una tarjeta vacía, instala primero el proyecto original con el entorno que corresponda a la estación, normalmente `estacion-v1`, y confirma que arranca en NORMAL. Conserva la configuración y el firmware de esa estación. Si la tarjeta ya está desplegada, respalda los datos de operación antes de instalar.
3. Instala Python y, en una terminal de Windows, instala la versión de esptool usada por el selector.

```powershell
py -m pip install "esptool>=4.7,<5"
```

4. Desde la carpeta del paquete, reemplaza `COM5` por el puerto de la tarjeta y ejecuta el instalador. Guarda el respaldo en un archivo nuevo y conserva una copia junto con el identificador de la estación.

```powershell
py selector.py --puerto COM5 instalar --bootloader binarios/bootloader.bin --tabla binarios/partition-table.bin --xbee binarios/xbee.bin --respaldo arranque_original_COM5.bin
```

El instalador compara la tabla que hay en la tarjeta con la original, verifica los binarios, guarda una copia del gestor y de la tabla originales y programa solo las regiones del arranque dual. La selección inicial es NORMAL. Los dispositivos con Secure Boot o cifrado de flash requieren su procedimiento de aprovisionamiento propio.

## Cambiar de firmware

Desde la terminal del computador, con el monitor serial cerrado.

```powershell
py selector.py --puerto COM5 xbee
py selector.py --puerto COM5 normal
py selector.py --puerto COM5 estado
```

Ejecuta el comando del modo que quieras. Los comandos usan el modo de programación USB del ESP32, por lo que también pueden reiniciar la placa al consultar `estado`. El mensaje del arranque a 115200 baudios muestra la aplicación elegida. Si la imagen XBee falla su verificación, el gestor intenta iniciar NORMAL y lo indica en el log.

La selección se guarda en `modo_dual` alternando dos sectores. Durante un cambio sigue existiendo el registro anterior hasta que quede completo el nuevo. El modo de arranque y la configuración de sensores son independientes.

## Configurar una estación en modo XBee

Después de elegir XBee, abre el monitor serial a 115200 baudios.

```powershell
pio device monitor --port COM5 --baud 115200 --echo
```

Ejemplo para la estación 667 con solo lluvia. Envía un comando por línea.

```text
config codigo 667
config rain true
config level false
reiniciar
```

`estado` muestra los ajustes activos y la configuración pendiente de reiniciar, si cambió. Ambos sensores envían el mismo código de estación. Una estación recién configurada debe tener código antes de publicar.

| Función en el firmware XBee | Conexión en CONTROL_COMM rev. 1.2 |
|---|---|
| Consola USB | UART0 en GPIO3 RX y GPIO1 TX, a través del CP2102. |
| RG-15 | UART1 en GPIO19 RX y GPIO18 TX. |
| XBee S3 Pro | UART2 en GPIO16 RX y GPIO17 TX. Es la UART compartida con el módem. |
| Petición de sueño del XBee | GPIO23 en bajo mientras se usa la radio. |
| `RESET/KEY_4G` | GPIO32 se lee como entrada sin pull-up. Si la línea sigue baja, se pausa la transmisión. |
| `EN_BOOST` | GPIO14 se lleva a bajo al iniciar XBEE. Deshabilitar el boost no garantiza que se desconecte eléctricamente el módem. |
| MB7388 | Salida analógica del sensor a `AN0`, pin 2 de `IN_AN1_V`, GPIO15. El conector ofrece 3,3 V y GND para el sensor. |
| Estado `ON_SLP` e interfaz de corriente | GPIO25 y GPIO33, respectivamente, según el plano rev. 1.2. El firmware XBee no usa estas dos señales. |

El conector `IN_AN1_V` recibe la **salida analógica del MB7388 (pin 3 del sensor)**. El firmware envía distancia en milímetros, como en el protocolo previo. La referencia nominal es 3300 mV. Para ajustar la escala de una instalación medida se puede usar `config nivel_ref_mv 3300` con la referencia que corresponda y después `reiniciar`. Mantén la entrada AN0 dentro de los límites eléctricos del ESP32. El firmware solo acepta lecturas ADC entre 150 y 2450 mV. Con la escala nominal eso cubre aproximadamente 0,5 a 7,6 m, sin asumir que toda la distancia de 10 m cabe en el rango útil del ADC.

El proyecto original documenta que el módem y la radio comparten `RESET/KEY_4G` y que el módem puede retener esa red en bajo. Si la placa informa `XBee en pausa: RESET/KEY ... sigue en bajo`, el arranque XBEE funcionó. La radio sigue bloqueada por el estado eléctrico de la red. La comprobación física de este punto y la recepción real en la Raspberry quedan pendientes.

## Compilar a partir de los archivos del paquete

Para generar el gestor y la tabla, abre una terminal de **ESP-IDF v4.4.7**, entra en `arranque` y ejecuta.

```powershell
idf.py set-target esp32
idf.py bootloader partition-table
```

Los resultados quedan en `arranque/build/bootloader/bootloader.bin` y `arranque/build/partition_table/partition-table.bin`. El objetivo de aplicación auxiliar de `arranque` solo permite compilar el gestor y la tabla. El archivo XBee se genera desde la raíz del paquete con PlatformIO.

```powershell
pio run -d xbee -e glima-xbee
```

El resultado XBee está en `xbee/.pio/build/glima-xbee/firmware.bin`. Úsalo con el instalador en el argumento `--xbee`. Para seleccionar el modo después de instalar, usa `selector.py`. Subir de nuevo el proyecto original con su orden normal de carga USB puede reemplazar la tabla y el gestor dual. Las actualizaciones OTA del pluviógrafo conservan sus dos ranuras `app0` y `app1`.

## Verificación y estado de la entrega

El gestor y XBee están compilados para ESP32 clásico de 16 MiB. El arranque personalizado usa ESP-IDF v4.4.7 y el firmware XBee usa Arduino ESP32 2.0.17 con PlatformIO espressif32 6.12. La herramienta oficial verificó las dos imágenes ESP32 y la tabla de particiones. En simulación se comprobó la instalación, el respaldo y el cambio en ambos sentidos, conservando las regiones del pluviógrafo. La prueba en la tarjeta ensamblada sigue pendiente.

### Prueba en la tarjeta prevista

1. Arranca en NORMAL y confirma que el pluviógrafo inicia. Apaga y vuelve a encender. Debe seguir en NORMAL.
2. Elige XBEE por USB, configura una estación, ejecuta `reiniciar` y verifica `estado`. Desconecta el USB y la alimentación. Al recuperar la alimentación, debe seguir en XBEE.
3. En XBEE, verifica el log del estado de `RESET/KEY_4G` y que las tramas lleguen a la Raspberry. Para nivel, verifica primero una distancia conocida.
4. Selecciona NORMAL por USB. Confirma el despertar habitual del pluviógrafo y que vuelve a NORMAL tras apagar y encender.
5. Si necesitas recuperar el arranque original de esa misma tarjeta, escribe el respaldo en la dirección `0x1000` con esptool 4.x. El respaldo cubre solo el gestor y la tabla de esa placa. Las aplicaciones y las colas quedan en sus direcciones originales.

```powershell
py -m esptool --chip esp32 --port COM5 write_flash 0x1000 arranque_original_COM5.bin
```

Fuentes del diseño: `firmware/partitions.csv` y `firmware/src/app/ota_client.cpp` del proyecto Pluviógrafo, y la hoja CONTROL_COMM, revisión 1.2, del esquemático suministrado. El punto de selección del gestor se basa en el [ejemplo oficial de ESP-IDF v4.4.7](https://github.com/espressif/esp-idf/tree/v4.4.7/examples/custom_bootloader/bootloader_override). La escala analógica usa la [referencia MaxBotix para HRXL de 10 m](https://maxbotix.com/blogs/blog/analog-voltage).
