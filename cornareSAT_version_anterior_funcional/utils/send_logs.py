import json
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
from datetime import datetime

# Parámetros de conexión a InfluxDB
url = "http://172.233.171.103:8086"  # Dirección de tu servidor InfluxDB
token = "qNutPmUtbqbIOyKshkhl7GLKoDKJBtn6OtwOwUlS74N2Id5-XcxWPKmtdIjc310rgPVnP7XvIWSZTiaayJhTZg=="  # Reemplaza con tu token de autenticación
org = "rain"  # Reemplaza con tu organización
bucket = "cornare-bucket"  # Reemplaza con el nombre de tu bucket

# Crear cliente de InfluxDB
client = InfluxDBClient(url=url, token=token, org=org)
write_api = client.write_api()

# Abre el archivo JSON
file_path = '/var/log/python_errors.log'
with open(file_path, "r") as file:
    for line in file:  # Leer línea por línea
        try:
            log = json.loads(line.strip())  # Convertir cada línea a JSON

            timestamp = datetime.fromisoformat(log["time"])

            # Crear el punto para InfluxDB
            point = (
                Point("python_logs")
                .tag("level", log["level"])
                .tag("code", log["code"])
                .tag("name", log["name"])
                .tag("city", log["city"])
                .tag("filename", log["filename"])
                .field("lineno", float(log["lineno"]))
                .field("message", log["message"])
                .time(timestamp)
            )

            write_api.write(bucket=bucket, record=point)

        except json.JSONDecodeError as e:
            print(f"Error decodificando JSON en línea: {line}\n{e}")

# Cerrar el cliente
write_api.__del__()
client.close()
