import argparse
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import boto3
from botocore import UNSIGNED
from botocore.config import Config

_motor = None


def cargar_motor():
    global _motor
    if _motor is None:
        import etl_procesamiento
        _motor = etl_procesamiento
    return _motor


def obtener_release():
    try:
        return cargar_motor().OVERTURE_RELEASE
    except Exception as e:
        print(f"   (motor no disponible: {e}; consultando el STAC directamente)", flush=True)
        import urllib.request
        req = urllib.request.Request("https://stac.overturemaps.org/catalog.json",
                                     headers={"User-Agent": "tfm/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))["latest"]

BUCKET_OVERTURE = "overturemaps-us-west-2"
REGION_OVERTURE = "us-west-2"

TEMAS_CONSULTADOS = [
    ("transportation", "segment"),
    ("places", "place"),
    ("buildings", "building"),
    ("base", "land_use"),
]


def medir_universo(release):
    s3 = boto3.client("s3", region_name=REGION_OVERTURE,
                      config=Config(signature_version=UNSIGNED))
    paginador = s3.get_paginator("list_objects_v2")

    detalle, total_bytes, total_ficheros = {}, 0, 0
    for tema, tipo in TEMAS_CONSULTADOS:
        prefijo = f"release/{release}/theme={tema}/type={tipo}/"
        tam, n = 0, 0
        for pagina in paginador.paginate(Bucket=BUCKET_OVERTURE, Prefix=prefijo):
            for objeto in pagina.get("Contents", []):
                tam += objeto["Size"]
                n += 1
        detalle[f"{tema}/{tipo}"] = {"bytes": tam, "gb": round(tam / 1e9, 2), "ficheros": n}
        total_bytes += tam
        total_ficheros += n
        print(f"   {tema}/{tipo:10s} {tam / 1e9:8.2f} GB en {n:4d} ficheros", flush=True)

    return {"por_tema": detalle, "bytes": total_bytes,
            "gb": round(total_bytes / 1e9, 2), "ficheros": total_ficheros}


def _bytes_del_log(con):
    try:
        mensajes = [f[0] for f in con.execute(
            "SELECT message FROM duckdb_logs WHERE type='HTTP'").fetchall()]
    except Exception as e:
        print(f"   no se pudo leer duckdb_logs: {e}", flush=True)
        return None, None

    total = 0
    for mensaje in mensajes:
        for valor in re.findall(r"Content-Length=(\d+)", mensaje):
            total += int(valor)
    return total, len(mensajes)


def medir_puerto(con, datos_puerto):
    motor = cargar_motor()
    nombre = datos_puerto.get("portname", "Desconocido")
    lat = motor.safe_float(datos_puerto.get("lat"))
    lon = motor.safe_float(datos_puerto.get("lon"))

    try:
        con.execute("CALL truncate_duckdb_logs()")
        con.execute("CALL enable_logging('HTTP')")
        logging_ok = True
    except Exception as e:
        print(f"   el log HTTP de DuckDB no está disponible: {e}", flush=True)
        logging_ok = False

    t0 = time.perf_counter()
    vias, industrias, poligono = motor.extraer_entorno_overture(
        con, lon, lat, radio_km=motor.PARAMETROS["radio_extraccion_km"])
    duracion = time.perf_counter() - t0

    bytes_leidos, peticiones = (None, None)
    if logging_ok:
        try:
            con.execute("CALL disable_logging()")
        except Exception:
            pass
        bytes_leidos, peticiones = _bytes_del_log(con)

    resultado = {
        "puerto": nombre,
        "lat": lat, "lon": lon,
        "radio_km": motor.PARAMETROS["radio_extraccion_km"],
        "segundos": round(duracion, 2),
        "filas_vias": len(vias),
        "filas_industrias": len(industrias),
        "poligono_puerto_encontrado": bool(poligono),
        "bytes_leidos": bytes_leidos,
        "mb_leidos": round(bytes_leidos / 1e6, 2) if bytes_leidos else None,
        "peticiones_http": peticiones,
    }
    print(f"   {nombre:28s} {resultado['mb_leidos'] or '?':>8} MB  "
          f"{peticiones or '?':>4} peticiones  {duracion:6.1f}s  "
          f"{len(vias)} vías / {len(industrias)} industrias", flush=True)
    return resultado


def render_markdown(informe):
    u = informe["universo"]
    L = ["# Volumen de datos procesado\n"]
    L.append(f"Release de Overture Maps: **{informe['overture_release']}**  ")
    L.append(f"Medición realizada el {informe['fecha']}.\n")
    L.append("> Overture conserva cada release unos 60 días, por lo que el ETL usa la "
             "versión más reciente disponible en el momento de la ejecución.\n")

    L.append("## 1. Universo de datos consultado\n")
    L.append("| Tema Overture | Tamaño | Ficheros Parquet |")
    L.append("|---|---|---|")
    for tema, d in u["por_tema"].items():
        L.append(f"| `{tema}` | {d['gb']:.2f} GB | {d['ficheros']} |")
    L.append(f"| **Total** | **{u['gb']:.2f} GB** | **{u['ficheros']}** |")
    L.append("")

    L.append("## 2. Volumen realmente leído por puerto\n")
    L.append("| Puerto | Descargado | Peticiones HTTP | Tiempo | Vías | Industrias |")
    L.append("|---|---|---|---|---|---|")
    for m in informe["mediciones"]:
        L.append(f"| {m['puerto']} | {m['mb_leidos'] or '?'} MB | {m['peticiones_http'] or '?'} | "
                 f"{m['segundos']} s | {m['filas_vias']} | {m['filas_industrias']} |")
    L.append("")

    agregado = informe["agregado"]
    if agregado.get("mb_medio") is not None:
        L.append("## 3. Eficiencia del *predicate pushdown*\n")
        L.append("| Métrica | Valor |")
        L.append("|---|---|")
        L.append(f"| Universo de datos | {u['gb']:.2f} GB |")
        L.append(f"| Media leída por puerto | {agregado['mb_medio']:.2f} MB |")
        L.append(f"| Fracción leída | {agregado['fraccion_leida_pct']:.4f} % |")
        L.append(f"| Factor de reducción | **{agregado['factor_reduccion']:,.0f}×** |")
        L.append("")
        L.append(f"Por puerto se descarga aproximadamente 1 de cada "
                 f"{agregado['factor_reduccion']:,.0f} bytes del universo de datos. DuckDB "
                 "filtra por *bounding box* usando las estadísticas de los grupos de filas "
                 "del Parquet y solo descarga los grupos que intersectan con el área del "
                 "puerto.\n")
    return "\n".join(L)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Mide el volumen de datos del ETL")
    ap.add_argument("--puertos", type=int, default=2)
    ap.add_argument("--talla", default="S", choices=["S", "M", "L"])
    ap.add_argument("--salida", default="docs/volumen")
    ap.add_argument("--release", default=None,
                    help="release de Overture a medir (por defecto, la más reciente)")
    ap.add_argument("--solo-universo", action="store_true",
                    help="mide únicamente el tamaño del dataset, sin ejecutar consultas")
    args = ap.parse_args()

    release = args.release or obtener_release()
    print(f"Midiendo el universo de datos de Overture {release}...", flush=True)
    universo = medir_universo(release)

    mediciones = []
    if not args.solo_universo:
        motor = cargar_motor()
        obj = motor.s3_client.get_object(
            Bucket=motor.S3_BUCKET,
            Key=f"fuentes_externas/fmi_ports/puertos_{args.talla}.json")
        lista = json.loads(obj["Body"].read().decode("utf-8"))[:args.puertos]
        if not lista:
            print("No hay puertos de esa talla; solo se mide el universo.")
        else:
            print(f"\nMidiendo {len(lista)} puertos (talla {args.talla})...", flush=True)
            con = motor.inicializar_duckdb()
            for datos_puerto in lista:
                mediciones.append(medir_puerto(con, datos_puerto))
            con.close()

    leidos = [m["bytes_leidos"] for m in mediciones if m["bytes_leidos"]]
    agregado = {}
    if leidos:
        media = sum(leidos) / len(leidos)
        agregado = {
            "mb_medio": round(media / 1e6, 2),
            "fraccion_leida_pct": round(media / universo["bytes"] * 100.0, 6),
            "factor_reduccion": round(universo["bytes"] / media, 0),
        }

    informe = {
        "fecha": time.strftime("%Y-%m-%d"),
        "overture_release": release,
        "universo": universo,
        "mediciones": mediciones,
        "agregado": agregado,
    }

    os.makedirs(args.salida, exist_ok=True)
    with open(os.path.join(args.salida, "volumen.json"), "w", encoding="utf-8") as f:
        json.dump(informe, f, indent=2, ensure_ascii=False)
    with open(os.path.join(args.salida, "volumen.md"), "w", encoding="utf-8") as f:
        f.write(render_markdown(informe))

    print(f"\nInforme escrito en {args.salida}/volumen.md")
    print(f"   Universo: {universo['gb']:.2f} GB en {universo['ficheros']} ficheros Parquet")
    if agregado:
        print(f"   Leído por puerto: {agregado['mb_medio']:.2f} MB "
              f"({agregado['fraccion_leida_pct']:.4f} % del universo, "
              f"reducción {agregado['factor_reduccion']:,.0f}×)")


if __name__ == "__main__":
    main()
