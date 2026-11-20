#include "seleccion.h"
#include <stdint.h>
#include "bootloader_flash_priv.h"
#include "esp_image_format.h"
#include "esp_log.h"

// Cada registro ocupa el principio de un sector independiente. Formato
// uint32_t little-endian: firma, generacion, modo, comprobacion por complemento.
#define FIRMA 0x314D4C47u
#define MODO_XBEE 1u
#define OFFSET_XBEE 0xD40000u
#define TAMANO_XBEE 0x280000u
#define OFFSET_MODO 0xFC0000u
#define TAMANO_SECTOR 0x1000u

typedef struct {
    uint32_t firma, generacion, modo, comprobacion;
} RegistroModo;

static bool leer_registro(uint32_t offset, RegistroModo *r)
{
    return bootloader_flash_read(offset, r, sizeof(*r), false) == ESP_OK &&
           r->firma == FIRMA && r->generacion > 0 && r->generacion < UINT32_MAX &&
           r->modo <= MODO_XBEE &&
           r->comprobacion == ~(r->firma ^ r->generacion ^ r->modo);
}

bool glima_arrancar_xbee(const bootloader_state_t *estado)
{
    static const char *TAG_GLIMA = "GLIMA_DUAL_V1";
    if (estado->test.offset != OFFSET_XBEE || estado->test.size != TAMANO_XBEE) {
        ESP_LOGW(TAG_GLIMA, "NORMAL: tabla sin particion XBee del proyecto");
        return false;
    }

    RegistroModo a = {0}, b = {0};
    const bool a_valido = leer_registro(OFFSET_MODO, &a);
    const bool b_valido = leer_registro(OFFSET_MODO + TAMANO_SECTOR, &b);
    const RegistroModo *ultimo = a_valido && (!b_valido || a.generacion >= b.generacion)
                                ? &a : b_valido ? &b : NULL;

    if (ultimo == NULL || ultimo->modo != MODO_XBEE) {
        ESP_LOGI(TAG_GLIMA, "NORMAL");
        return false;
    }

    esp_image_metadata_t datos = {0};
    if (esp_image_verify(ESP_IMAGE_VERIFY_SILENT, &estado->test, &datos) != ESP_OK) {
        ESP_LOGW(TAG_GLIMA, "NORMAL: no se pudo validar la imagen XBEE");
        return false;
    }

    ESP_LOGI(TAG_GLIMA, "XBEE");
    return true;
}
