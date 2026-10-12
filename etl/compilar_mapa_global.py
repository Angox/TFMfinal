import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from config_aws import S3_BUCKET, AWS_REGION

PREFIX_RUTAS = "resultados_web/api/rutas/"
CLAVE_SALIDA = "resultados_web/mapa_global/global_hinterland.pmtiles"

DIR_TRABAJO = os.getenv("PMTILES_DIR_TRABAJO") or "."
OUTPUT_PMTILES = os.path.join(DIR_TRABAJO, "global_hinterland.pmtiles")
TEMP_GEOJSON = os.path.join(DIR_TRABAJO, "temp_global.geojson")

DESCARGAS_PARALELAS = int(os.getenv("PMTILES_DESCARGAS_PARALELAS", "8"))
ZOOM_MAXIMO = os.getenv("PMTILES_ZOOM_MAXIMO", "12")
TRAFICO_MINIMO = float(os.getenv("PMTILES_TRAFICO_MINIMO", "0"))

PROPIEDADES_MAPA = ("trafico", "tipo_via")

CAPA_TESELAS = "rutas_termicas"

DECIMALES = 5


def formato_bytes(n):
    valor = float(n)
    for unidad in ("B", "KiB", "MiB", "GiB"):
        if valor < 1024.0:
            return f"{valor:.1f} {unidad}"
        valor /= 1024.0
    return f"{valor:.1f} TiB"


def iterar_features(texto):
    decodificador = json.JSONDecoder()
    marca = texto.find('"features"')
    if marca == -1:
        return
    i = texto.find("[", marca)
    if i == -1:
        return
    i += 1
    n = len(texto)
    while i < n:
        while i < n and texto[i] in " \t\r\n,":
            i += 1
        if i >= n or texto[i] == "]":
            return
        feature, i = decodificador.raw_decode(texto, i)
        yield feature


def redondear(coordenadas):
    if not coordenadas:
        return coordenadas
    if isinstance(coordenadas[0], (int, float)):
        return [round(float(c), DECIMALES) for c in coordenadas]
    return [redondear(c) for c in coordenadas]


def adelgazar(feature, trafico_minimo=0.0):
    geometria = (feature or {}).get("geometry") or {}
    coordenadas = geometria.get("coordinates")
    if not coordenadas or not geometria.get("type"):
        return None

    propiedades = feature.get("properties") or {}
    try:
        trafico = float(propiedades.get("trafico") or 0.0)
    except (TypeError, ValueError):
        trafico = 0.0
    if trafico < trafico_minimo:
        return None

    return {
        "type": "Feature",
        "geometry": {
            "type": geometria["type"],
            "coordinates": redondear(coordenadas),
        },
        "properties": {
            "trafico": round(trafico, 2),
            "tipo_via": propiedades.get("tipo_via") or "unclassified",
        },
    }


def listar_rutas(s3):
    paginador = s3.get_paginator("list_objects_v2")
    claves, total_bytes = [], 0
    for pagina in paginador.paginate(Bucket=S3_BUCKET, Prefix=PREFIX_RUTAS):
        for item in pagina.get("Contents", []):
            if not item["Key"].endswith(".json"):
                continue
            claves.append(item["Key"])
            total_bytes += int(item.get("Size") or 0)
    return claves, total_bytes


def por_ventanas(secuencia, tamano):
    for inicio in range(0, len(secuencia), tamano):
        yield secuencia[inicio:inicio + tamano]


def volcar_geojson(s3, claves, destino, trafico_minimo=0.0, paralelas=None):
    paralelas = max(1, paralelas or DESCARGAS_PARALELAS)

    def descargar(clave):
        return s3.get_object(Bucket=S3_BUCKET, Key=clave)["Body"].read().decode("utf-8")

    puertos = features = ultimo_aviso = 0
    arranque = time.time()
    with open(destino, "w", encoding="utf-8") as salida:
        with ThreadPoolExecutor(max_workers=paralelas) as pool:
            for ventana in por_ventanas(list(claves), paralelas):
                for texto in pool.map(descargar, ventana):
                    for feature in iterar_features(texto):
                        magra = adelgazar(feature, trafico_minimo)
                        if magra is None:
                            continue
                        salida.write(json.dumps(magra, separators=(",", ":")) + "\n")
                        features += 1
                    del texto
                    puertos += 1

                if puertos - ultimo_aviso >= 100:
                    ultimo_aviso = puertos
                    print(f"   ... {puertos}/{len(claves)} puertos · "
                          f"{features:,} vías · {formato_bytes(salida.tell())} "
                          f"escritos · {time.time() - arranque:.0f}s", flush=True)
    return puertos, features


def comando_tippecanoe(entrada, salida, zoom=None, temporal=None):
    return [
        "tippecanoe", "-o", salida, "--force",
        "-l", CAPA_TESELAS,
        "-z", str(zoom or ZOOM_MAXIMO),
        "--drop-densest-as-needed",
        "--read-parallel",
        "--temporary-directory", temporal or DIR_TRABAJO,
        entrada,
    ]


def avisar_de_disco(destino, bytes_en_bucket):
    libres = shutil.disk_usage(os.path.dirname(os.path.abspath(destino))).free
    estimado = int(bytes_en_bucket * 0.4 * 2.5)
    print(f"Disco en {DIR_TRABAJO}: {formato_bytes(libres)} libres · "
          f"necesidad estimada {formato_bytes(estimado)}", flush=True)
    if estimado > libres:
        print(" El disco puede quedarse corto. Opciones: PMTILES_DIR_TRABAJO "
              "a un volumen mayor, PMTILES_TRAFICO_MINIMO por encima de 0 o "
              "PMTILES_ZOOM_MAXIMO más bajo.", flush=True)


def compilar_pmtiles():
    import boto3
    from botocore.config import Config

    s3 = boto3.client(
        "s3", region_name=AWS_REGION,
        config=Config(max_pool_connections=DESCARGAS_PARALELAS + 4,
                      retries={"max_attempts": 5, "mode": "standard"}),
    )

    print("1. Localizando las redes portuarias en S3...", flush=True)
    claves, bytes_en_bucket = listar_rutas(s3)
    if not claves:
        print("No hay rutas generadas en S3: el ETL no ha dejado nada que "
              "compilar.", flush=True)
        sys.exit(1)

    print(f"   -> {len(claves)} puertos · {formato_bytes(bytes_en_bucket)} en bruto",
          flush=True)
    os.makedirs(DIR_TRABAJO, exist_ok=True)
    avisar_de_disco(TEMP_GEOJSON, bytes_en_bucket)

    print(f"2. Volcando a NDJSON en {TEMP_GEOJSON} "
          f"({DESCARGAS_PARALELAS} descargas en paralelo)...", flush=True)
    puertos, features = volcar_geojson(s3, claves, TEMP_GEOJSON, TRAFICO_MINIMO)
    print(f"   -> {puertos} puertos leídos, {features:,} vías, "
          f"{formato_bytes(os.path.getsize(TEMP_GEOJSON))} de GeoJSON maestro.",
          flush=True)
    if features == 0:
        print("Ninguna vía superó el filtro: revisa PMTILES_TRAFICO_MINIMO.",
              flush=True)
        sys.exit(1)

    print("3. Ejecutando Tippecanoe para generar el archivo PMTiles...", flush=True)
    arranque = time.time()
    subprocess.run(comando_tippecanoe(TEMP_GEOJSON, OUTPUT_PMTILES), check=True)
    print(f"   -> {formato_bytes(os.path.getsize(OUTPUT_PMTILES))} de teselas "
          f"en {time.time() - arranque:.0f}s.", flush=True)

    os.remove(TEMP_GEOJSON)

    print("4. Subiendo el PMTiles maestro a S3...", flush=True)
    s3.upload_file(
        OUTPUT_PMTILES,
        S3_BUCKET,
        CLAVE_SALIDA,
        ExtraArgs={
            'ContentType': 'application/x-pmtiles',
            'ServerSideEncryption': 'AES256'
        }
    )
    print("¡Mapa global publicado con éxito!", flush=True)


if __name__ == "__main__":
    compilar_pmtiles()
