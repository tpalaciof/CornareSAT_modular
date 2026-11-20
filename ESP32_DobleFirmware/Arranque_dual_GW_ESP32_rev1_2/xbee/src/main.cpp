#include <Arduino.h>
#include <Preferences.h>
#include <driver/gpio.h>
#include <math.h>
#include <string.h>

//***************************** CONFIGURACIÓN *****************************//

bool LEVEL = false;
bool RAIN = true;

String codigoEstacion = "";
Preferences ajustes;
bool ajustesDisponibles = false;
bool radioDisponible = false;
const unsigned int REFERENCIA_NOMINAL_MV = 3300;
unsigned int referenciaNivelMv = REFERENCIA_NOMINAL_MV;

// Durante las pruebas se envía cada 2 segundos.
// Posteriormente puede cambiarse a 30000.
const unsigned long FRECUENCIA_ENVIO_MS = 2000;
const unsigned long ESPERA_RG15_MS = 1000;

// XBee del nodo: AP=0, 9600 baudios y destino configurado hacia la Raspberry.
// XBee de la Raspberry: AP=1 y AO=0, en la misma red.
// Cada envío contiene solo la medición y su código, terminado en '\n'.
// La fecha y el procesamiento por intervalos quedan a cargo de la Raspberry.

//******************************** PINES **********************************//

// CONTROL_COMM rev. 1.2: MB7388 analógico en IN_AN1_V, pin 2 (AN0).
const int PIN_NIVEL = 15;
// Límite decidido para el rango calibrado del ESP32 clásico.
const unsigned int ADC_MIN_MV = 150;
const unsigned int ADC_MAX_MV = 2450;

// Enlace compartido con el módem. Direcciones vistas desde el ESP32.
const int PIN_RX_XBEE = 16;
const int PIN_TX_XBEE = 17;
const int PIN_XBEE_SLEEP = 23;
const int PIN_XBEE_RESET_KEY = 32;
const gpio_num_t PIN_EN_BOOST = GPIO_NUM_14;
HardwareSerial puertoXBee(2);

// RG-15 en su conector de la tarjeta.
const int PIN_RX_SENSOR_LLUV = 19;
const int PIN_TX_SENSOR_LLUV = 18;
HardwareSerial puertoSensor_lluv(1);

//******************************* VARIABLES ******************************//

unsigned long tiempoAnteriorEnvio = 0;
unsigned long inicioConsultaLluvia = 0;

String bufferRG15 = "";
bool esperandoLluvia = false;

//******************************* FUNCIONES ******************************//

//---------------------------------------------------------------------
// Configuración por el monitor serial USB
//---------------------------------------------------------------------

bool codigoValido(const char *codigo)
{
  const char alfanumericos[] =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  const char permitidos[] =
      "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-";

  const size_t longitud = strlen(codigo);
  return longitud <= 64 && strspn(codigo, alfanumericos) > 0 &&
         strspn(codigo, permitidos) == longitud;
}

void mostrarConfiguracion(const char *nombre, const String &codigo, bool rain, bool level, unsigned int referencia)
{
  Serial.printf("%s: codigo=%s rain=%s level=%s nivel_ref_mv=%u\n", nombre,
                codigo.length() ? codigo.c_str() : "(sin asignar)",
                rain ? "true" : "false", level ? "true" : "false", referencia);
}

void mostrarEstado()
{
  mostrarConfiguracion("Activa", codigoEstacion, RAIN, LEVEL, referenciaNivelMv);
  Serial.println(radioDisponible ? "UART XBee habilitada." : "UART XBee en pausa.");

  if (ajustesDisponibles)
  {
    String codigoGuardado = ajustes.getString("codigo", "");
    bool rainGuardado = ajustes.getBool("rain", true);
    bool levelGuardado = ajustes.getBool("level", false);
    unsigned int referenciaGuardada = ajustes.getUInt("nivel_ref_mv", REFERENCIA_NOMINAL_MV);

    if (codigoGuardado != codigoEstacion || rainGuardado != RAIN || levelGuardado != LEVEL ||
        referenciaGuardada != referenciaNivelMv)
    {
      mostrarConfiguracion("Guardada para el proximo arranque",
                           codigoGuardado, rainGuardado, levelGuardado, referenciaGuardada);
    }
  }
}

void procesarComandoSerial(char *linea)
{
  char *resto;
  const char *comando = strtok_r(linea, " \t", &resto);
  if (!comando)
    return;

  const char *ajuste = strtok_r(nullptr, " \t", &resto);

  if (strcmp(comando, "estado") == 0 && !ajuste)
  {
    mostrarEstado();
    return;
  }

  if (strcmp(comando, "reiniciar") == 0 && !ajuste)
  {
    Serial.println("Reiniciando...");
    Serial.flush();
    ESP.restart();
    return;
  }

  const char *valor = strtok_r(nullptr, " \t", &resto);
  if (strcmp(comando, "config") != 0 || !ajuste || !valor ||
      strtok_r(nullptr, " \t", &resto))
  {
    Serial.println("Comandos: config codigo <codigo> | config rain <true/false> | "
                   "config level <true/false> | config nivel_ref_mv <mV> | estado | reiniciar");
    return;
  }

  if (!ajustesDisponibles)
  {
    Serial.println("Error: no se puede acceder a la configuracion guardada.");
    return;
  }

  bool guardado;
  if (strcmp(ajuste, "codigo") == 0)
  {
    if (!codigoValido(valor))
    {
      Serial.println("Error: el codigo debe iniciar con una letra o un numero "
                     "y solo admite letras, numeros, _, . y - (hasta 64 caracteres).");
      return;
    }
    guardado = ajustes.putString("codigo", valor) == strlen(valor);
  }
  else if (strcmp(ajuste, "rain") == 0 || strcmp(ajuste, "level") == 0)
  {
    if (strcmp(valor, "true") != 0 && strcmp(valor, "false") != 0)
    {
      Serial.println("Error: usa true o false.");
      return;
    }
    guardado = ajustes.putBool(ajuste, strcmp(valor, "true") == 0) == 1;
  }
  else if (strcmp(ajuste, "nivel_ref_mv") == 0)
  {
    // El valor representa Vcc del MB7388 multiplicada por la relación de la entrada.
    if (strlen(valor) > 4 || strspn(valor, "0123456789") != strlen(valor))
    {
      Serial.println("Error: indica un valor entero entre 500 y 3300 mV.");
      return;
    }
    unsigned long mv = strtoul(valor, nullptr, 10);
    if (mv < 500 || mv > 3300)
    {
      Serial.println("Error: indica un valor entero entre 500 y 3300 mV.");
      return;
    }
    guardado = ajustes.putUInt("nivel_ref_mv", mv) == sizeof(uint32_t);
  }
  else
  {
    Serial.println("Error: los ajustes disponibles son codigo, rain, level y nivel_ref_mv.");
    return;
  }

  if (guardado)
    Serial.printf("Guardado: %s=%s. Escribe reiniciar para aplicarlo.\n", ajuste, valor);
  else
    Serial.println("Error: no se pudo guardar el ajuste.");
}

void atenderComandosSerial()
{
  static char linea[96];
  static size_t longitud = 0;
  static bool descartar = false;

  while (Serial.available())
  {
    char caracter = Serial.read();
    if (caracter == '\r' || caracter == '\n')
    {
      linea[longitud] = '\0';
      longitud = 0;
      const bool lineaInvalida = descartar;
      descartar = false;

      if (lineaInvalida)
        Serial.println("Error: linea demasiado larga o invalida.");
      else if (linea[0] != '\0')
        procesarComandoSerial(linea);
    }
    else if (caracter == '\0' || longitud >= sizeof(linea) - 1)
      descartar = true;
    else if (!descartar)
      linea[longitud++] = caracter;
  }
}

void enviarMedicion(const char *variable, double valor)
{
  char trama[128];
  snprintf(trama, sizeof(trama), "{\"%s\":%.10g,\"codigo\":\"%s\"}\n",
           variable, valor, codigoEstacion.c_str());

  puertoXBee.print(trama);
  Serial.print("ESP32 -> XBee: ");
  Serial.print(trama);
}

//---------------------------------------------------------------------
// Lectura analógica MB7388 en el conector CN3
//---------------------------------------------------------------------

double leerNivelMm()
{
  if (referenciaNivelMv == 0)
    return -888.8;

  const unsigned int mv = analogReadMilliVolts(PIN_NIVEL);
  if (mv < ADC_MIN_MV || mv > ADC_MAX_MV)
    return -888.8;

  // MB7388 de 10 m: Vcc/1024 por 10 mm (ajustado a la entrada AN0).
  const long distancia = lround(1024.0 * mv / referenciaNivelMv) * 10;
  return distancia >= 500 && distancia <= 9998 ? distancia : -888.8;
}

//---------------------------------------------------------------------
// Lectura RG-15
//---------------------------------------------------------------------

void enviarComando(const char *comando)
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

//---------------------------------------------------------------------
// SETUP
//---------------------------------------------------------------------

// Mantener el boost apagado incluso al venir del modo NORMAL.
bool apagarBoost()
{
  gpio_hold_dis(PIN_EN_BOOST);
  gpio_deep_sleep_hold_dis();
  gpio_set_level(PIN_EN_BOOST, 0);

  gpio_config_t config{};
  config.pin_bit_mask = 1ULL << PIN_EN_BOOST;
  config.mode = GPIO_MODE_INPUT_OUTPUT;
  config.pull_up_en = GPIO_PULLUP_DISABLE;
  config.pull_down_en = GPIO_PULLDOWN_DISABLE;
  config.intr_type = GPIO_INTR_DISABLE;
  return gpio_config(&config) == ESP_OK &&
         gpio_set_level(PIN_EN_BOOST, 0) == ESP_OK &&
         gpio_get_level(PIN_EN_BOOST) == 0;
}

void setup()
{
  const bool boostApagado = apagarBoost();
  // Monitor serial de PlatformIO
  Serial.begin(115200);
  Serial.println("GLIMA XBEE CONTROL_COMM REV1.2");

  ajustesDisponibles = ajustes.begin("xbee_cfg", false);
  if (ajustesDisponibles)
  {
    codigoEstacion = ajustes.getString("codigo", "");
    if (!codigoValido(codigoEstacion.c_str()))
      codigoEstacion = "";

    RAIN = ajustes.getBool("rain", true);
    LEVEL = ajustes.getBool("level", false);
    referenciaNivelMv = ajustes.getUInt("nivel_ref_mv", REFERENCIA_NOMINAL_MV);
    if (referenciaNivelMv < 500 || referenciaNivelMv > 3300)
      referenciaNivelMv = 0;
  }
  else
    Serial.println("Error: no se pudo abrir la configuracion guardada.");

  Serial.println("Escribe estado para consultar la configuracion.");
  if (!codigoEstacion.length())
  {
    mostrarEstado();
    Serial.println("Configura el codigo de la estacion y reinicia para iniciar las mediciones.");
    return;
  }

  if (!boostApagado)
  {
    Serial.println("XBee en pausa: GPIO14 EN_BOOST no quedo en bajo.");
    return;
  }

  if (!RAIN && !LEVEL)
  {
    mostrarEstado();
    return;
  }

  pinMode(PIN_XBEE_RESET_KEY, INPUT); // GPIO32 compartido. Nunca conducirlo.
  pinMode(PIN_XBEE_SLEEP, OUTPUT);
  digitalWrite(PIN_XBEE_SLEEP, LOW);
  delay(250);

  if (digitalRead(PIN_XBEE_RESET_KEY) == LOW)
  {
    Serial.println("XBee en pausa: RESET/KEY (GPIO32) sigue en bajo. Revisar la tarjeta.");
    return;
  }

  puertoXBee.begin(9600, SERIAL_8N1, PIN_RX_XBEE, PIN_TX_XBEE);
  radioDisponible = true;

  //========================== MB7388 ===============================//

  if (LEVEL)
  {
    if (referenciaNivelMv)
      analogSetPinAttenuation(PIN_NIVEL, ADC_11db);
    else
      Serial.println("Nivel sin referencia. Configura nivel_ref_mv antes de medir.");
  }

  //========================== RG-15 ================================//

  if (RAIN)
  {
    puertoSensor_lluv.begin(9600, SERIAL_8N1,
                            PIN_RX_SENSOR_LLUV, PIN_TX_SENSOR_LLUV);
    delay(1000);
    enviarComando("M"); // Unidades métricas: mm.
    delay(200);
    enviarComando("H"); // Alta resolución.
    delay(200);
    enviarComando("P"); // Responder solamente cuando se solicita una lectura.
    delay(200);
    recibirRG15();
  }

  mostrarEstado();
  Serial.println("ESP32 lista. Enviando JSON de los sensores habilitados.");
  tiempoAnteriorEnvio = millis();
}

//---------------------------------------------------------------------
// LOOP
//---------------------------------------------------------------------

void loop()
{
  atenderComandosSerial();
  if (!radioDisponible)
  {
    delay(1);
    return;
  }

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

    if (LEVEL && referenciaNivelMv)
      enviarMedicion("nivel", leerNivelMm());

    if (RAIN && !esperandoLluvia)
    {
      bufferRG15 = "";
      enviarComando("R");
      inicioConsultaLluvia = tiempoActual;
      esperandoLluvia = true;
    }
  }

  delay(1);
}
