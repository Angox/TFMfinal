import os
from pathlib import Path


def _cargar_config_env():
    valores = {}
    for directorio in Path(__file__).resolve().parents:
        fichero = directorio / "config.env"
        if not fichero.is_file():
            continue
        for linea in fichero.read_text(encoding="utf-8").splitlines():
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, valor = linea.split("=", 1)
            valores[clave.strip()] = valor.strip().strip('"').strip("'")
        break
    return valores


_CONFIG = _cargar_config_env()


def obtener(clave, por_defecto=None):
    valor = os.getenv(clave) or _CONFIG.get(clave) or por_defecto
    if not valor:
        raise RuntimeError(
            f"Falta la configuración '{clave}'. Defínela en config.env (raíz del "
            f"repositorio) o expórtala como variable de entorno."
        )
    return valor


S3_BUCKET = obtener("S3_BUCKET_NAME")
AWS_REGION = obtener("AWS_REGION", "us-west-2")
