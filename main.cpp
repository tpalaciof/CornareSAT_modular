#include <Arduino.h>
#include <math.h>
#include <stdio.h>
#include <string.h>
#include <esp_timer.h>
#include <inttypes.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <esp_partition.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>

// Configuración del nodo.
const char CODIGO_ESTACION[] = "667";
const bool LEVEL = false;
const bool RAIN = true;
const unsigned long FRECUENCIA_ENVIO_MS = 5000; // 5 segundos.
const unsigned long ESPERA_RG15_MS = 1000;

// MB7388 analógico en AN0 (IN_AN1_V) de la GW rev. 1.2.
const int PIN_NIVEL = 15;
const unsigned int REFERENCIA_NIVEL_MV = 3300;
const unsigned int ADC_MIN_MV = 150;
const unsigned int ADC_MAX_MV = 2450;

// XBee del nodo en modo transparente (AP=0), con destino a la Raspberry.
const int PIN_RX_XBEE = 16;
const int PIN_TX_XBEE = 17;
const int PIN_XBEE_SLEEP = 23;
const int PIN_XBEE_RESET_KEY = 32;
const int PIN_EN_BOOST = 14;
HardwareSerial puertoXBee(2);

// RG-15 en el conector de lluvia de la GW.
const int PIN_RX_SENSOR_LLUV = 19;
const int PIN_TX_SENSOR_LLUV = 18;
HardwareSerial puertoSensor_lluv(1);

unsigned long tiempoAnteriorEnvio = 0;
unsigned long inicioConsultaLluvia = 0;
String bufferRG15 = "";
bool esperandoLluvia = false;

// Respaldo de lecturas en la memoria flash del ESP32.
static const char DIRECTORIO[] = "/littlefs/xbee";
static uint32_t arranque, secuencia;
static char rutaEnvio[96] = "";
static long posicion = 0, siguiente = 0;
static int64_t referenciaEnvio = 0;

// Se prepara automáticamente solo una partición que está completamente borrada.
static bool particionVacia()
{
  const esp_partition_t *part = esp_partition_find_first(
      ESP_PARTITION_TYPE_DATA, ESP_PARTITION_SUBTYPE_ANY, "spiffs");
  if (!part) return false;
  uint8_t bloque[512];
  for (size_t i = 0; i < part->size; i += sizeof(bloque))
  {
    const size_t n = min(sizeof(bloque), size_t(part->size - i));
    if (esp_partition_read(part, i, bloque, n) != ESP_OK) return false;
    for (size_t j = 0; j < n; ++j)
      if (bloque[j] != 0xff) return false;
  }
  return true;
}

bool iniciarRespaldo()
{
  if (!LittleFS.begin(false) && !(particionVacia() && LittleFS.begin(true))) return false;
  if (mkdir(DIRECTORIO, 0755) != 0 && errno != EEXIST) return false;
  Preferences memoria;
  if (!memoria.begin("xbee-tiempo", false)) return false;
  // Una instalación nueva empieza en un número aleatorio. Los reinicios lo incrementan.
  uint32_t anterior = memoria.isKey("arranque") ? memoria.getUInt("arranque")
                                                : (esp_random() & 0x7fffffffU);
  arranque = anterior + 1;
  return arranque && memoria.putUInt("arranque", arranque) == sizeof(arranque);
}

bool guardarReferencia(int64_t desfase)
{
  char ruta[96], temporal[96];
  snprintf(ruta, sizeof(ruta), "%s/%08" PRIX32 ".hora", DIRECTORIO, arranque);
  snprintf(temporal, sizeof(temporal), "%s/referencia.tmp", DIRECTORIO);
  FILE *f = fopen(temporal, "w");
  if (!f) return false;
  bool ok = fprintf(f, "%" PRId64 "\n", desfase) > 0 && fflush(f) == 0 && fsync(fileno(f)) == 0;
  if (fclose(f) != 0) ok = false;
  return ok && rename(temporal, ruta) == 0;
}

bool respaldarMedicion(const char *campo, double valor, const char *codigo, int64_t tiempo)
{
  char ruta[96], linea[160];
  // Reserva espacio para poder guardar la primera hora y vaciar un respaldo lleno.
  static bool espacio = true;
  if (!espacio || secuencia % 32 == 0)
    espacio = LittleFS.totalBytes() > LittleFS.usedBytes() + 16384;
  if (!espacio) return false;
  const uint32_t numero = ++secuencia;
  // En cortes largos se liberan grupos de hasta 128 lecturas al confirmarlos.
  snprintf(ruta, sizeof(ruta), "%s/%08" PRIX32 "-%08" PRIX32 ".csv",
           DIRECTORIO, arranque, (numero - 1) / 128);
  int n = snprintf(linea, sizeof(linea), "%" PRIu32 ",%" PRId64 ",%s,%.10g,%s\n",
                   numero, tiempo, campo, valor, codigo);
  if (n <= 0 || size_t(n) >= sizeof(linea)) return false;
  // LittleFS publica el nuevo contenido al sincronizar o cerrar el archivo.
  int fd = open(ruta, O_WRONLY | O_CREAT | O_APPEND, 0644);
  if (fd < 0) return false;
  off_t fin = lseek(fd, 0, SEEK_END);
  bool ok = fin >= 0 && write(fd, linea, n) == n && fsync(fd) == 0;
  if (!ok && fin >= 0) ftruncate(fd, fin);
  if (close(fd) != 0) ok = false;
  return ok;
}

static bool buscarArchivo()
{
  DIR *dir = opendir(DIRECTORIO);
  if (!dir) return false;
  char primero[22] = "";
  dirent *entrada;
  while ((entrada = readdir(dir)))
  {
    const char *nombre = entrada->d_name;
    if (strlen(nombre) != 21 || strcmp(nombre + 17, ".csv") != 0) continue;
    if (primero[0] && strcmp(nombre, primero) >= 0) continue;
    char ruta[96];
    snprintf(ruta, sizeof(ruta), "%s/%.8s.hora", DIRECTORIO, nombre);
    FILE *ref = fopen(ruta, "r");
    if (!ref) continue;  // Un arranque sin referencia conserva su CSV local.
    int64_t desfase;
    bool valido = fscanf(ref, "%" SCNd64, &desfase) == 1;
    fclose(ref);
    if (!valido) continue;
    strcpy(primero, nombre);
    referenciaEnvio = desfase;
  }
  closedir(dir);
  if (!primero[0]) return false;
  snprintf(rutaEnvio, sizeof(rutaEnvio), "%s/%s", DIRECTORIO, primero);
  posicion = 0;
  return true;
}

bool leerPendiente(char *json, unsigned capacidad, char *id)
{
  if (!rutaEnvio[0] && !buscarArchivo()) return false;
  FILE *f = fopen(rutaEnvio, "r");
  if (!f) return false;
  char linea[160], campo[16], valor[32], codigo[64];
  uint32_t numero;
  int64_t tiempo;
  if (fseek(f, posicion, SEEK_SET) != 0 || !fgets(linea, sizeof(linea), f))
  {
    bool vacio = feof(f) && !ferror(f);
    fclose(f);
    if (vacio && unlink(rutaEnvio) == 0) rutaEnvio[0] = '\0';
    return false;
  }
  bool ok = strchr(linea, '\n') && sscanf(linea, "%" SCNu32 ",%" SCNd64 ",%15[^,],%31[^,],%63s",
                                             &numero, &tiempo, campo, valor, codigo) == 5;
  siguiente = ftell(f);
  fclose(f);
  if (!ok) { Serial.println("No se pudo leer la fila pendiente XBee."); return false; }
  const char *nombre = strrchr(rutaEnvio, '/') + 1;
  snprintf(id, 18, "%.8s-%08" PRIX32, nombre, numero);
  // Antes de la primera sincronización se guardó -(contador_ms + 1).
  int64_t ts = tiempo < 0 ? referenciaEnvio - tiempo - 1 : tiempo;
  int n = snprintf(json, capacidad, "{\"%s\":%s,\"codigo\":\"%s\",\"id\":\"%s\",\"ts\":%" PRId64 "}\n",
                   campo, valor, codigo, id, ts);
  return n > 0 && unsigned(n) < capacidad;
}

void confirmarPendiente()
{
  // Tras un reinicio se relee el bloque. La Raspberry reconoce los ID ya guardados.
  struct stat info;
  if (stat(rutaEnvio, &info) != 0) return;
  if (siguiente < info.st_size)
    posicion = siguiente;
  else if (unlink(rutaEnvio) == 0)
    rutaEnvio[0] = '\0';
}

// El contador continúa aunque el enlace esté caído. El desfase lo convierte a Unix ms.
bool horaValida = false;
int64_t desfaseMs = 0;
char idEnviado[18] = "";
char tramaEnviada[192];
char respuesta[96];
size_t recibidos = 0;
int64_t proximoEnvio = 0;

int64_t contadorMs()
{
  return esp_timer_get_time() / 1000;
}

void enviarMedicion(const char *variable, double valor)
{
  const int64_t contador = contadorMs();
  const int64_t marca = horaValida ? desfaseMs + contador : -(contador + 1);
  if (!respaldarMedicion(variable, valor, CODIGO_ESTACION, marca))
    Serial.println("No se pudo guardar la medición XBee. Revise el espacio disponible.");
}

void atenderXBee()
{
  while (puertoXBee.available())
  {
    char c = puertoXBee.read();
    if (c != '\n')
    {
      if (recibidos < sizeof(respuesta) - 1) respuesta[recibidos++] = c;
      continue;
    }
    respuesta[recibidos] = '\0';
    recibidos = 0;
    int64_t hora;
    int fin = 0;
    char id[18];
    if (!horaValida && sscanf(respuesta, "{\"hora\":%" SCNd64 "}%n", &hora, &fin) == 1
        && fin && !respuesta[fin] && hora > 0)
    {
      const int64_t desfase = hora - contadorMs();
      if (guardarReferencia(desfase))
      {
        desfaseMs = desfase;
        horaValida = true;
        proximoEnvio = 0;
      }
    }
    else if (horaValida && sscanf(respuesta, "{\"ack\":\"%17[0-9A-F-]\",\"hora\":%" SCNd64 "}%n",
                                   id, &hora, &fin) == 2 && fin && !respuesta[fin] && hora > 0
             && strcmp(id, idEnviado) == 0)
    {
      desfaseMs = hora - contadorMs();
      confirmarPendiente();
      idEnviado[0] = '\0';
      proximoEnvio = 0;
    }
  }

  int64_t ahora = contadorMs();
  if (ahora < proximoEnvio) return;
  proximoEnvio = ahora + 3000;
  if (!horaValida)
    puertoXBee.print("{\"pedir\":\"hora\"}\n");
  else
  {
    if (!idEnviado[0] && !leerPendiente(tramaEnviada, sizeof(tramaEnviada), idEnviado))
    {
      idEnviado[0] = '\0';
      proximoEnvio = ahora + 200;
      return;
    }
    puertoXBee.print(tramaEnviada);
    Serial.print(tramaEnviada); // Copia del JSON en el monitor USB.
  }
}

double leerNivelMm()
{
  const unsigned int mv = analogReadMilliVolts(PIN_NIVEL);
  if (mv < ADC_MIN_MV || mv > ADC_MAX_MV)
    return -888.8;

  // MB7388 de 10 m: Vcc/1024 por 10 mm (ajustado a la entrada AN0).
  const long distancia = lround(1024.0 * mv / REFERENCIA_NIVEL_MV) * 10;
  return distancia >= 500 && distancia <= 9998 ? distancia : -888.8;
}

void enviarComandoRG15(const char *comando)
{
  puertoSensor_lluv.print(comando);
  puertoSensor_lluv.print('\n');
}

void recibirRG15()
{
  while (puertoSensor_lluv.available())
  {
    char caracter = puertoSensor_lluv.read();

    if (caracter == '\n')
    {
      bufferRG15.trim();
      double lluvia;
      char unidad[5] = "";

      // Acc es la precipitación adicional desde el último mensaje, en mm.
      // No se envían EventAcc, TotalAcc ni RInt.
      if (esperandoLluvia &&
          sscanf(bufferRG15.c_str(), "Acc %lf %4s", &lluvia, unidad) == 2 &&
          (strcmp(unidad, "mm,") == 0 || strcmp(unidad, "mm") == 0) &&
          isfinite(lluvia) && lluvia >= 0)
      {
        enviarMedicion("precipitacion", lluvia);
        esperandoLluvia = false;
      }

      bufferRG15 = "";
    }
    else if (caracter != '\r')
    {
      if (bufferRG15.length() < 160)
      {
        bufferRG15 += caracter;
      }
      else
      {
        bufferRG15 = "";
      }
    }
  }
}

void setup()
{
  Serial.begin(115200);

  pinMode(PIN_EN_BOOST, OUTPUT);
  digitalWrite(PIN_EN_BOOST, LOW); // Deshabilita el boost del módem en la UART compartida.
  pinMode(PIN_XBEE_RESET_KEY, INPUT); // Línea compartida en alta impedancia.
  pinMode(PIN_XBEE_SLEEP, OUTPUT);
  digitalWrite(PIN_XBEE_SLEEP, LOW); // Mantiene despierto el XBee.
  delay(250);
  puertoXBee.begin(9600, SERIAL_8N1, PIN_RX_XBEE, PIN_TX_XBEE);

  while (!iniciarRespaldo())
  {
    Serial.println("Respaldo XBee no disponible. Revise la partición de datos.");
    delay(5000);
  }

  if (LEVEL)
    analogSetPinAttenuation(PIN_NIVEL, ADC_11db);

  if (RAIN)
  {
    puertoSensor_lluv.begin(9600, SERIAL_8N1, PIN_RX_SENSOR_LLUV, PIN_TX_SENSOR_LLUV);
    delay(1000);
    enviarComandoRG15("M"); // Unidades métricas: mm.
    delay(200);
    enviarComandoRG15("H"); // Alta resolución.
    delay(200);
    enviarComandoRG15("P"); // Responder solamente cuando se solicita una lectura.
    delay(200);
    recibirRG15();
  }

  atenderXBee();
  tiempoAnteriorEnvio = millis();
}

void loop()
{
  atenderXBee();
  if (RAIN)
  {
    recibirRG15();
  }

  unsigned long tiempoActual = millis();

  if (esperandoLluvia && tiempoActual - inicioConsultaLluvia >= ESPERA_RG15_MS)
  {
    // -999 indica que no se obtuvo una lectura de lluvia válida.
    enviarMedicion("precipitacion", -999);
    esperandoLluvia = false;
    bufferRG15 = "";
  }

  if (tiempoActual - tiempoAnteriorEnvio >= FRECUENCIA_ENVIO_MS)
  {
    tiempoAnteriorEnvio = tiempoActual;

    if (LEVEL)
      enviarMedicion("nivel", leerNivelMm());

    if (RAIN && !esperandoLluvia)
    {
      bufferRG15 = "";
      enviarComandoRG15("R");
      inicioConsultaLluvia = tiempoActual;
      esperandoLluvia = true;
    }
  }

  delay(1);
}

