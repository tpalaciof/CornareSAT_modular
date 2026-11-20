import os
import subprocess
import requests
from dotenv import load_dotenv

# Configuración
load_dotenv('/home/pi/cornareSAT/credentials/.env')
GITHUB_USER = os.getenv('USERNAME_GIT')
GITHUB_TOKEN = os.getenv('TOKEN_GIT')
GITHUB_REPO = os.getenv('REPO_GITHUB')
LOCAL_REPO_PATH = os.getenv('LOCAL_REPO')

GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}/commits/main"

def get_latest_commit():
    """Consulta el último commit en GitHub con autenticación"""
    try:
        response = requests.get(GITHUB_API_URL, auth=(GITHUB_USER, GITHUB_TOKEN), timeout=10)
        response.raise_for_status()
        latest_commit = response.json().get("sha", "")
        return latest_commit
    except requests.RequestException as e:
        print(f"Error al consultar GitHub: {e}")
        return None

def get_local_commit():
    """Obtiene el hash del último commit en el repositorio local"""
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=LOCAL_REPO_PATH, capture_output=True, text=True)
        return result.stdout.strip()
    except Exception as e:
        print(f"Error al obtener commit local: {e}")
        return None

def set_upstream_branch():
    """Configura el seguimiento de la rama main si no está configurado"""
    try:
        subprocess.run(["git", "branch", "--set-upstream-to=origin/main", "main"], cwd=LOCAL_REPO_PATH, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        pass  # Si ya está configurado, no es necesario hacer nada

def update_repository():
    """Ejecuta git pull con autenticación"""
    try:
        remote_url = f"https://{GITHUB_USER}:{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
        subprocess.run(["git", "remote", "set-url", "origin", remote_url], cwd=LOCAL_REPO_PATH, check=True)

        # Configurar seguimiento de la rama si no está establecido
        set_upstream_branch()

        subprocess.run(["git", "pull"], cwd=LOCAL_REPO_PATH, check=True)
        print("Repositorio actualizado correctamente.")
    except subprocess.CalledProcessError as e:
        print(f"Error al actualizar el repositorio: {e}")

def main():
    latest_commit = get_latest_commit()
    local_commit = get_local_commit()

    if latest_commit and local_commit:
        if latest_commit != local_commit:
            print("Nueva actualización disponible. Ejecutando git pull...")
            update_repository()
        else:
            print("El repositorio ya está actualizado.")
    else:
        print("No se pudo obtener información del repositorio.")

if __name__ == "__main__":
    main()
