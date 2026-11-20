"""Instala el arranque dual y selecciona el modo por USB. Requiere esptool 4.x."""
import argparse
import hashlib
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

BOOT = 0x1000
TABLA = 0x8000
XBEE = 0xD40000
TAM_XBEE = 0x280000
MODO = 0xFC0000
SECTOR = 0x1000
TAM_FLASH = 0x1000000
MARCA_BOOT = b"GLIMA_DUAL_V1"
MARCA_XBEE = b"GLIMA XBEE CONTROL_COMM REV1.2"
FIRMA = 0x314D4C47

COMUNES = (
    ("nvs", 1, 2, 0x9000, 0x5000, 0),
    ("otadata", 1, 0, 0xE000, 0x2000, 0),
    ("app0", 0, 16, 0x10000, 0x300000, 0),
    ("app1", 0, 17, 0x310000, 0x300000, 0),
    ("coredump", 1, 3, 0x610000, 0x10000, 0),
    ("nvs_state", 1, 2, 0x620000, 0x20000, 0),
    ("q_mqtt", 0x40, 0, 0x640000, 0x300000, 0),
    ("q_influx", 0x40, 1, 0x940000, 0x400000, 0),
)
ORIGINAL = COMUNES + (("reserved", 0x40, 2, XBEE, TAM_FLASH - XBEE, 0),)
DUAL = COMUNES + (
    ("xbee", 0, 0x20, XBEE, TAM_XBEE, 0),
    ("modo_dual", 0x40, 3, MODO, 2 * SECTOR, 0),
    ("reserved", 0x40, 2, MODO + 2 * SECTOR, TAM_FLASH - MODO - 2 * SECTOR, 0),
)


def leer_tabla(blob):
    filas = []
    for i in range(0, min(len(blob), 0xC00), 32):
        fila = blob[i:i + 32]
        if fila[:16] == b"\xeb\xeb" + b"\xff" * 14:
            if fila[16:] == hashlib.md5(blob[:i]).digest():
                return tuple(filas)
            break
        if len(fila) != 32 or fila[:2] != b"\xaa\x50":
            break
        _, tipo, subtipo, offset, size, label, flags = struct.unpack("<HBBII16sI", fila)
        filas.append((label.rstrip(b"\x00").decode("ascii"), tipo, subtipo, offset, size, flags))
    raise ValueError("La tabla no se reconoce o su MD5 es incorrecto.")


def codificar_modo(secuencia, modo):
    return struct.pack("<4I", FIRMA, secuencia, modo, ~(FIRMA ^ secuencia ^ modo) & 0xFFFFFFFF)


def seleccion_guardada(blob):
    registros = []
    if len(blob) != 2 * SECTOR:
        raise ValueError("Lectura incompleta de la selección.")
    for sector in range(2):
        inicio = sector * SECTOR
        firma, sec, modo, comprobacion = struct.unpack_from("<4I", blob, inicio)
        if (firma == FIRMA and 0 < sec < 0xFFFFFFFF and modo in (0, 1)
                and comprobacion == (~(firma ^ sec ^ modo) & 0xFFFFFFFF)):
            registros.append((sec, sector, modo))
    return max(registros, key=lambda r: (r[0], -r[1]), default=(0, 1, 0))


class Placa:
    def __init__(self, puerto, tmp):
        self.base = [sys.executable, "-m", "esptool", "--chip", "esp32", "--port", puerto]
        self.tmp = Path(tmp)

    def ejecutar(self, *args, captura=False):
        proceso = subprocess.run(self.base + list(args), text=True,
                                 stdout=subprocess.PIPE if captura else None,
                                 stderr=subprocess.STDOUT if captura else None)
        if proceso.returncode:
            if captura:
                print(proceso.stdout.strip(), file=sys.stderr)
            raise ValueError("La operación por USB falló. Revisa el puerto, alimentación y log.")
        return proceso.stdout or ""

    def leer(self, offset, size, reiniciar=False):
        destino = self.tmp / "lectura.bin"
        self.ejecutar("--after", "hard_reset" if reiniciar else "no_reset",
                      "read_flash", hex(offset), hex(size), str(destino), captura=True)
        datos = destino.read_bytes()
        if len(datos) != size:
            raise ValueError("Lectura incompleta de la flash.")
        return datos

    def escribir(self, *pares):
        self.ejecutar("--after", "hard_reset", "write_flash", *(s for offset, ruta in pares for s in (hex(offset), str(ruta))))


def verificar_imagen(ruta, maximo, marca):
    datos = ruta.read_bytes()
    # E9 = imagen ESP. El ID del ESP32 clásico se codifica como cero en su cabecera.
    if not 24 <= len(datos) <= maximo or datos[0] != 0xE9 or datos[12:14] != b"\0\0" or marca not in datos:
        raise ValueError(f"{ruta.name} no corresponde a la imagen esperada o supera su partición.")
    informe = subprocess.run(
        [sys.executable, "-m", "esptool", "--chip", "esp32", "image_info", str(ruta)],
        check=True, text=True, stdout=subprocess.PIPE,
    ).stdout
    for campo in ("Checksum", "Validation Hash"):
        if not re.search(rf"^{campo}: [^\n]+ \(valid\)$", informe, re.MULTILINE):
            raise ValueError(f"{ruta.name}: no se pudo verificar {campo}.")


def instalar(placa, acceso, args):
    if leer_tabla(acceso[TABLA - BOOT:]) != ORIGINAL:
        raise ValueError("Se requiere la tabla original del pluviógrafo de 16 MiB.")
    if leer_tabla(args.tabla.read_bytes()) != DUAL:
        raise ValueError("La tabla nueva debe ser exactamente la de este proyecto.")
    verificar_imagen(args.bootloader, TABLA - BOOT, MARCA_BOOT)
    verificar_imagen(args.xbee, TAM_XBEE, MARCA_XBEE)

    flash_id = placa.ejecutar("--after", "no_reset", "flash_id", captura=True)
    if not re.search(r"Detected flash size:\s*16\s*MB\b", flash_id, re.IGNORECASE):
        raise ValueError("No se detectó una flash de 16 MiB.")
    if not any(placa.leer(fila[3], 1) == b"\xe9" for fila in COMUNES if fila[0] in ("app0", "app1")):
        raise ValueError("Instala primero el firmware original del pluviógrafo.")

    with args.respaldo.open("xb") as archivo:
        archivo.write(acceso)
    inicial = placa.tmp / "modo_inicial.bin"
    inicial.write_bytes(codificar_modo(1, 0).ljust(2 * SECTOR, b"\xff"))
    placa.escribir((BOOT, args.bootloader), (TABLA, args.tabla), (XBEE, args.xbee), (MODO, inicial))
    print(f"Instalado. Selección inicial NORMAL. Respaldo del arranque y la tabla: {args.respaldo}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--puerto", required=True, help="Puerto del CP2102. Ejemplo: COM5")
    sub = ap.add_subparsers(dest="comando", required=True)
    for nombre in ("estado", "normal", "xbee"):
        sub.add_parser(nombre)
    ins = sub.add_parser("instalar")
    ins.add_argument("--bootloader", required=True, type=Path)
    ins.add_argument("--tabla", required=True, type=Path)
    ins.add_argument("--xbee", required=True, type=Path)
    ins.add_argument("--respaldo", required=True, type=Path)
    args = ap.parse_args()

    try:
        with tempfile.TemporaryDirectory(prefix="glima_dual_") as tmp:
            placa = Placa(args.puerto, tmp)
            acceso = placa.leer(BOOT, TABLA + SECTOR - BOOT)
            if args.comando == "instalar":
                instalar(placa, acceso, args)
                return 0

            if leer_tabla(acceso[TABLA - BOOT:]) != DUAL or MARCA_BOOT not in acceso[:TABLA - BOOT]:
                raise ValueError("La placa no tiene instalado este arranque dual.")
            consultar = args.comando == "estado"
            sec, sector, anterior = seleccion_guardada(placa.leer(MODO, 2 * SECTOR, reiniciar=consultar))
            if consultar:
                print(f"Próximo arranque guardado: {('NORMAL', 'XBEE')[anterior]}")
                return 0

            nuevo = int(args.comando == "xbee")
            if nuevo == anterior:
                placa.ejecutar("--after", "hard_reset", "flash_id", captura=True)
                print(f"Ya está seleccionado {args.comando.upper()}.")
                return 0
            if sec >= 0xFFFFFFFE:
                raise ValueError("Contador agotado. Se necesita reprovisionar el selector.")

            registro = Path(tmp) / "modo.bin"
            registro.write_bytes(codificar_modo(sec + 1, nuevo))
            placa.escribir((MODO + (1 - sector) * SECTOR, registro))
            print(f"Selección guardada: {args.comando.upper()}. La placa se reinició.")
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
