#!/bin/bash

echo "🚮 Iniciando limpieza de logs y archivos temporales..."

# Ruta base (ajusta si es necesario)
RUTA_BASE="/home/pi/cornareSAT/logs/"

# 1. Eliminar todos los archivos dentro de carpetas llamadas "logs"
echo "🗑️ Eliminando archivos dentro de carpetas 'logs'..."
find "$RUTA_BASE" -type d -name "logs" -exec rm -v -f {}/* \;

# 2. Eliminar archivos temporales comunes
echo "🧹 Eliminando archivos temporales (*.tmp, *.log, *.bak, etc)..."
find "$RUTA_BASE" -type f \( -name "*.tmp" -o -name "*.log" -o -name "*.bak" -o -name "*~" \) -exec rm -v -f {} \;

# 3. (Opcional) Vaciar carpeta /tmp
echo "🧼 Limpiando /tmp..."
sudo rm -rf /tmp/*

echo "✅ Limpieza completada."
