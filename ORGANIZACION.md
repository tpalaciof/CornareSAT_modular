# Organización de cornareSAT

El programa de medición tiene una única entrada: `main.py`.
El código ya no consulta, habilita ni inicia `rain.service`. 

## Responsabilidades

| Archivo | Función |
|---|---|
| main.py | Cargar configuración, validar recursos, iniciar y cerrar las tareas. |
| moduls/medicion_nivel.py | Lectura local TTL/ADC y moda de nivel local y remoto. |
| moduls/medicion_lluvia.py | Lectura local del RG15 y validación de precipitación. |
| moduls/recepcion_Xbee.py | Recibir y distribuir nivel y lluvia de los nodos. |
| moduls/salida.py | Publicar MQTT y coordinar históricos, pendientes y reenvíos. |
| moduls/registros.py | Colas compartidas entre las tareas. |
| utils/interpretarTramasXbee.py | Puerto serial, tramas API, reconstrucción JSON y NI. |
| utils/tunel.py | Iniciar el túnel TCP mediante /home/pi/shootback/slaver.py. |
| utils/configuracion.py | Configuración común desde settings.json. |
| utils/csvwritingv2.py | Escritura y recuperación de archivos. |
| utils/maxbotix.py, adc.py, rain_rg15v2.py | Controladores de los sensores. |

Se conservan el resto de utilidades y monitoring.py del ZIP del usuario.
Monitoring permanece independiente; no se inicia desde main.py.
No hay lanzadores alternativos ni carpeta de pruebas en esta entrega.

## Lluvia

`CONFIGURACION['H_RAIN']` toma el valor de `settings['RAIN']`.

- True: main inicia la tarea local de lluvia.
- False: main no inicia esa tarea.

La recepción XBee de lluvia permanece disponible en ambos casos.
No existe una segunda opción llamada lluvia_integrada.
La lluvia usa directamente acc del RG15, o precipitacion recibida por XBee.
No se calcula moda, promedio, suma ni diferencias de lluvia.
SAMPLETIME_RAIN controla las consultas locales; cada mensaje remoto de lluvia
se entrega directamente a salida, sin remuestrearlo.
LEVEL controla el nivel local: true lo activa y false lo desactiva.
Si LEVEL no existe, se utiliza true para conservar el funcionamiento anterior.
Usar booleanos JSON (true/false), no cadenas de texto.
MAXBOTIX_TTL selecciona TTL (true) o ADC (false) cuando LEVEL está activado.
Con LEVEL=false no se abre el sensor local de nivel ni se comprueba su puerto
ni su calibración. SAMPLETIME_LEVEL sigue siendo necesario para la moda XBee.
El túnel, MQTT y XBee funcionan independientemente de LEVEL y RAIN.

Para dejar únicamente lluvia local, añadir o cambiar en credentials/settings.json:

```json
"LEVEL": false,
"RAIN": true
```

Son entradas del objeto JSON existente; conservar las demás claves.
Los cambios se aplican al reiniciar main.py.

Mensajes XBee, cada uno terminado con salto de línea:

```json
{"nivel":500,"codigo":"667"}
{"precipitacion":2.4,"codigo":"668"}
```

## Rutas y archivos

Se conservan las rutas configuradas `/home/glima/cornareSAT` y
`/home/glima/datalogger`; monitoring mantiene sus rutas originales de usuario pi.
Este ZIP no incorpora credenciales: conservar la carpeta credentials existente
con settings.json y .env en CARPETA_PROGRAMA. No se trasladaron rutas a nombres
versionados ni se modificaron los identificadores MQTT.

Los históricos nuevos están en CARPETA_BACKUP/diarios, separados de los pendientes.
Nivel conserva levelAAAA-MM-DD.csv como pendientes; lluvia utiliza
rain_pendingAAAA-MM-DD.csv. Son JSON por línea. Los datos remotos pendientes
usan nodos/NI_MAC; el histórico remoto usa diarios/nodos/MAC.
No se importan automáticamente los antiguos backup_rain.csv separados por punto
y coma. Deben revisarse sus pendientes al planear la migración.
La confirmación QoS 1 es del broker, no una garantía de escritura en la API.

## Comprobaciones realizadas

Sintaxis e importaciones verificadas. Siete pruebas simuladas de mediciones,
recepción, archivos y MQTT superadas. Arranque simulado comprobado con RAIN
verdadero y falso. No se han probado sensores, radio, broker ni servicios reales.

El formulario html/index.html se conserva exactamente como en el ZIP original.
LEVEL se configura directamente en credentials/settings.json; no se añadió
ningún campo al formulario ni a los mensajes MQTT.
