import argparse
import csv
import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config_aws import AWS_REGION, S3_BUCKET


PREFIX_DETALLES = "resultados_web/api/detalles/"
PREFIX_BASICOS = "resultados_web/api/basicos/"
PREFIX_FALLIDOS = "resultados_web/api/fallidos/"


def leer_json_bajo(s3, prefijo):
    documentos = []
    paginador = s3.get_paginator("list_objects_v2")
    for pagina in paginador.paginate(Bucket=S3_BUCKET, Prefix=prefijo):
        for objeto in pagina.get("Contents", []):
            clave = objeto["Key"]
            if not clave.endswith(".json"):
                continue
            try:
                cuerpo = s3.get_object(Bucket=S3_BUCKET, Key=clave)["Body"].read()
                documentos.append((clave, json.loads(cuerpo.decode("utf-8"))))
            except Exception as e:
                print(f"   no se pudo leer {clave}: {e}", flush=True)
    return documentos


def describir_distribucion(valores):
    limpios = [v for v in valores if isinstance(v, (int, float))]
    if not limpios:
        return {"n": 0}
    ordenados = sorted(limpios)
    n = len(ordenados)

    def percentil(q):
        k = (n - 1) * q
        bajo = int(k)
        alto = min(bajo + 1, n - 1)
        if bajo == alto:
            return ordenados[bajo]
        return ordenados[bajo] + (ordenados[alto] - ordenados[bajo]) * (k - bajo)

    return {
        "n": n,
        "min": round(ordenados[0], 3),
        "p25": round(percentil(0.25), 3),
        "mediana": round(percentil(0.50), 3),
        "p75": round(percentil(0.75), 3),
        "max": round(ordenados[-1], 3),
        "media": round(statistics.fmean(ordenados), 3),
        "desviacion": round(statistics.stdev(ordenados), 3) if n > 1 else 0.0,
    }


def agregar_calidad(detalles):
    totales = defaultdict(int)
    con_calidad = 0
    for d in detalles:
        calidad = d.get("calidad_datos")
        if not isinstance(calidad, dict):
            continue
        con_calidad += 1
        for clave, valor in calidad.items():
            if isinstance(valor, (int, float)) and not clave.endswith("_pct"):
                totales[clave] += valor

    recibidas = totales.get("vias_recibidas", 0)
    descartadas = totales.get("vias_geometria_invalida", 0) + totales.get("vias_sin_aristas", 0)
    return {
        "puertos_con_metricas": con_calidad,
        "totales": dict(totales),
        "vias_descartadas": descartadas,
        "vias_descartadas_pct": round(descartadas / recibidas * 100.0, 2) if recibidas else 0.0,
    }


def agregar_sectores(detalles):
    acumulado = defaultdict(float)
    n = 0
    for d in detalles:
        perfil = d.get("distribucion_comercial_comtrade")
        if not isinstance(perfil, dict) or not perfil:
            continue
        n += 1
        for sector, cuota in perfil.items():
            if isinstance(cuota, (int, float)):
                acumulado[sector] += cuota
    if not n:
        return {}
    return {s: round(v / n, 4) for s, v in sorted(acumulado.items(), key=lambda x: -x[1])}


def construir_filas(detalles_por_puerto, basicos_por_puerto):
    filas = []
    for puerto, d in sorted(detalles_por_puerto.items()):
        basico = basicos_por_puerto.get(puerto, {})
        calidad = d.get("calidad_datos") or {}
        filas.append({
            "puerto": puerto,
            "pais": d.get("pais"),
            "lat": basico.get("lat"),
            "lng": basico.get("lng"),
            "indice_estres": d.get("indice_estres"),
            "riesgo_cuello_botella": d.get("riesgo_cuello_botella"),
            "riesgo_macroeconomico": d.get("riesgo_macroeconomico"),
            "volumen_diario": d.get("volumen_diario", d.get("volumen_teus")),
            "unidad_volumen": d.get("unidad_volumen"),
            "origen_volumen": d.get("origen_volumen", "desconocido"),
            "capacidad_diaria": d.get("capacidad_diaria"),
            "saturacion": d.get("saturacion"),
            "vulnerabilidad": d.get("vulnerabilidad"),
            "origen_saturacion": d.get("origen_saturacion"),
            "origen_puertas": d.get("origen_puertas"),
            "incremento_interdiccion": d.get("incremento_interdiccion"),
            "indice_comparable": bool(d.get(
                "indice_comparable",
                d.get("origen_volumen") == "portwatch_diario")),
            "carga_principal": d.get("carga_principal"),
            "porcentaje_container_roro": d.get("porcentaje_container_roro"),
            "cuota_import": d.get("cuota_import"),
            "cuota_export": d.get("cuota_export"),
            "vias_totales": d.get("vias_totales", d.get("vias_totales_km")),
            "puertas_reales": len(d.get("puertas_reales") or []),
            "rating_color": basico.get("rating_color"),
            "vias_descartadas_pct": calidad.get("vias_descartadas_pct"),
            "nodo_industrial_principal": d.get("nodo_industrial_principal"),
            "top_calles_colapsadas": d.get("top_calles_colapsadas"),
        })
    return filas


def _ranking(filas, tope):
    validos = [f for f in filas if isinstance(f.get("indice_estres"), (int, float))]
    return sorted(validos, key=lambda f: -f["indice_estres"])[:tope]


def _tabla_ranking(filas):
    if not filas:
        return ["_Ningun puerto en esta categoria._"]
    L = ["| # | Puerto | País | I_EL | Saturación | Vulnerabilidad | Volumen/día | Capacidad | Vías |",
         "|---|---|---|---|---|---|---|---|---|"]
    for i, fila in enumerate(filas, 1):
        cap = fila.get("capacidad_diaria")
        sat = fila.get("saturacion")
        vul = fila.get("vulnerabilidad")
        L.append(f"| {i} | {fila['puerto']} | {fila['pais']} | {fila['indice_estres']} | "
                 f"{sat if sat is not None else '—'} | {vul if vul is not None else '—'} | "
                 f"{fila['volumen_diario']} | {round(cap) if cap else '—'} | "
                 f"{fila['vias_totales']} |")
    return L


def render_markdown(inf):
    f = inf["filas"]
    L = ["# Resultados\n"]
    L.append(f"Generado el {inf['fecha']} a partir de `s3://{S3_BUCKET}`.\n")

    L.append("## 1. Cobertura del procesamiento\n")
    L.append("| Métrica | Valor |")
    L.append("|---|---|")
    L.append(f"| Puertos con resultados | {inf['cobertura']['procesados']} |")
    L.append(f"| Puertos fallidos | {inf['cobertura']['fallidos']} |")
    L.append(f"| Tasa de éxito | {inf['cobertura']['tasa_exito_pct']:.1f} % |")
    L.append(f"| Países representados | {inf['cobertura']['paises']} |")
    L.append("")
    if inf["cobertura"]["motivos_fallo"]:
        L.append("**Motivos de fallo**\n")
        L.append("| Motivo | Puertos |")
        L.append("|---|---|")
        for motivo, n in inf["cobertura"]["motivos_fallo"].items():
            L.append(f"| `{motivo}` | {n} |")
        L.append("")

    L.append("## 2. Distribución del Índice de Estrés Logístico\n")
    L.append("> El I_EL de un puerto con volumen medido usa como saturación la frecuencia "
             "con la que ha superado su capacidad demostrada; el de un puerto con volumen "
             "estimado usa un cociente contra una constante de 8.000. Las dos escalas no "
             "son comparables y se separan en el apartado 2.1.\n")
    L.append("| Estadístico | I_EL | Riesgo macroeconómico | Volumen diario |")
    L.append("|---|---|---|---|")
    d_iel, d_macro, d_vol = inf["distribuciones"]["indice_estres"], \
        inf["distribuciones"]["riesgo_macroeconomico"], inf["distribuciones"]["volumen_diario"]
    for clave in ("n", "min", "p25", "mediana", "p75", "max", "media", "desviacion"):
        L.append(f"| {clave} | {d_iel.get(clave, '—')} | {d_macro.get(clave, '—')} | "
                 f"{d_vol.get(clave, '—')} |")
    L.append("")

    L.append("**Clasificación de riesgo**\n")
    L.append("| Nivel | Puertos | % |")
    L.append("|---|---|---|")
    total = max(inf["cobertura"]["procesados"], 1)
    for nivel, n in inf["riesgo"].items():
        L.append(f"| {nivel} | {n} | {n / total * 100:.1f} % |")
    L.append("")

    L.append("**Procedencia del volumen**")
    L.append("")
    L.append("| Origen | Puertos | % |")
    L.append("|---|---|---|")
    ETIQUETAS = {"portwatch_diario": "Medido (FMI Daily_Ports_Data, toneladas)",
                 "estimado_por_escalas": "Estimado por recuento de escalas"}
    for origen, n in inf["origen_volumen"].items():
        L.append(f"| {ETIQUETAS.get(origen, origen)} | {n} | {n / total * 100:.1f} % |")
    L.append("")
    L.append("### 2.1 Distribución por escala\n")
    L.append("| Estadístico | I_EL comparable (medido) | I_EL estimado |")
    L.append("|---|---|---|")
    d_comp = inf["distribuciones"]["indice_estres_comparable"]
    d_est = inf["distribuciones"]["indice_estres_estimado"]
    for clave in ("n", "min", "p25", "mediana", "p75", "max", "media", "desviacion"):
        L.append(f"| {clave} | {d_comp.get(clave, '—')} | {d_est.get(clave, '—')} |")
    L.append("")

    L.append("### 2.2 Composición del índice\n")
    L.append("| Estadístico | Saturación [0-1] | Vulnerabilidad [0-1] |")
    L.append("|---|---|---|")
    d_sat = inf["distribuciones"]["saturacion"]
    d_vul = inf["distribuciones"]["vulnerabilidad"]
    for clave in ("n", "min", "p25", "mediana", "p75", "max", "media", "desviacion"):
        L.append(f"| {clave} | {d_sat.get(clave, '—')} | {d_vul.get(clave, '—')} |")
    L.append("")
    if inf.get("origen_puertas"):
        L.append("**Método de detección de las puertas del puerto**")
        L.append("")
        L.append("| Origen | Puertos |")
        L.append("|---|---|")
        for origen, n in inf["origen_puertas"].items():
            L.append(f"| `{origen}` | {n} |")
        L.append("")
        L.append("> Con `nodo_artificial` todo el flujo sale de un único punto sintético y el "
                 "término de vulnerabilidad no refleja la red viaria real.")
        L.append("")

    L.append("## 3. Puertos con mayor estrés logístico\n")
    L.append("### 3.1 Volumen medido (escala comparable)\n")
    L.extend(_tabla_ranking(inf["top_estres_comparable"]))
    L.append("")
    L.append("### 3.2 Volumen estimado por escalas (escala no comparable con 3.1)\n")
    L.extend(_tabla_ranking(inf["top_estres_estimado"]))
    L.append("")

    if inf["por_pais"]:
        L.append("## 4. Agregado por país\n")
        L.append("| País | Puertos | I_EL medio | TEU/día total |")
        L.append("|---|---|---|---|")
        for pais, d in inf["por_pais"][:20]:
            L.append(f"| {pais} | {d['puertos']} | {d['iel_medio']} | {d['teus']} |")
        L.append("")

    c = inf["calidad"]
    L.append("## 5. Calidad de los datos\n")
    L.append("| Métrica | Valor |")
    L.append("|---|---|")
    L.append(f"| Vías recibidas de Overture | {c['totales'].get('vias_recibidas', 0):,} |")
    L.append(f"| Vías descartadas | {c['vias_descartadas']:,} ({c['vias_descartadas_pct']} %) |")
    L.append(f"| — por geometría inválida | {c['totales'].get('vias_geometria_invalida', 0):,} |")
    L.append(f"| — sin aristas utilizables | {c['totales'].get('vias_sin_aristas', 0):,} |")
    L.append(f"| Industrias recibidas | {c['totales'].get('industrias_recibidas', 0):,} |")
    L.append(f"| Teselas DEM inaccesibles | {c['totales'].get('tiles_dem_fallidos', 0):,} |")
    L.append(f"| Teselas HRSL inaccesibles | {c['totales'].get('tiles_pop_fallidos', 0):,} |")
    L.append("")

    if inf["sectores"]:
        L.append("## 6. Reparto sectorial medio (UN Comtrade)\n")
        L.append("| Sector | Cuota media |")
        L.append("|---|---|")
        for sector, cuota in inf["sectores"].items():
            L.append(f"| {sector} | {cuota * 100:.1f} % |")
        L.append("")

    L.append("---\n")
    L.append(f"Datos por puerto en `resultados.csv` ({len(f)} filas).\n")
    return "\n".join(L)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Genera el capítulo de resultados desde S3")
    ap.add_argument("--salida", default="docs/resultados")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    import boto3

    s3 = boto3.client("s3", region_name=AWS_REGION)

    print(f"Leyendo resultados de s3://{S3_BUCKET} ...", flush=True)
    detalles = leer_json_bajo(s3, PREFIX_DETALLES)
    basicos = leer_json_bajo(s3, PREFIX_BASICOS)
    fallidos = leer_json_bajo(s3, PREFIX_FALLIDOS)
    print(f"   {len(detalles)} detalles, {len(basicos)} básicos, {len(fallidos)} fallidos",
          flush=True)

    if not detalles:
        print("No hay resultados en S3. Ejecuta antes el ETL.")
        sys.exit(1)

    detalles_por_puerto = {os.path.basename(k)[:-5]: v for k, v in detalles}
    basicos_por_puerto = {os.path.basename(k)[len("basico_"):-5]: v for k, v in basicos}
    docs_detalle = list(detalles_por_puerto.values())

    filas = construir_filas(detalles_por_puerto, basicos_por_puerto)

    por_pais = defaultdict(lambda: {"puertos": 0, "iel": [], "teus": 0})
    for fila in filas:
        d = por_pais[fila["pais"] or "desconocido"]
        d["puertos"] += 1
        if isinstance(fila["indice_estres"], (int, float)):
            d["iel"].append(fila["indice_estres"])
        if isinstance(fila["volumen_diario"], (int, float)):
            d["teus"] += fila["volumen_diario"]
    resumen_pais = sorted(
        ((p, {"puertos": d["puertos"],
              "iel_medio": round(statistics.fmean(d["iel"]), 2) if d["iel"] else None,
              "teus": round(d["teus"])}) for p, d in por_pais.items()),
        key=lambda x: -x[1]["puertos"])

    n_proc, n_fall = len(filas), len(fallidos)
    informe = {
        "fecha": time.strftime("%Y-%m-%d"),
        "bucket": S3_BUCKET,
        "cobertura": {
            "procesados": n_proc,
            "fallidos": n_fall,
            "tasa_exito_pct": round(n_proc / (n_proc + n_fall) * 100.0, 1) if (n_proc + n_fall) else 0.0,
            "paises": len({f["pais"] for f in filas if f["pais"]}),
            "motivos_fallo": dict(Counter(v.get("motivo", "desconocido") for _, v in fallidos)),
        },
        "distribuciones": {
            "indice_estres": describir_distribucion([f["indice_estres"] for f in filas]),
            "indice_estres_comparable": describir_distribucion(
                [f["indice_estres"] for f in filas if f.get("indice_comparable")]),
            "indice_estres_estimado": describir_distribucion(
                [f["indice_estres"] for f in filas if not f.get("indice_comparable")]),
            "saturacion": describir_distribucion([f.get("saturacion") for f in filas]),
            "vulnerabilidad": describir_distribucion([f.get("vulnerabilidad") for f in filas]),
            "riesgo_macroeconomico": describir_distribucion([f["riesgo_macroeconomico"] for f in filas]),
            "volumen_diario": describir_distribucion([f["volumen_diario"] for f in filas]),
        },
        "riesgo": dict(Counter(f["riesgo_cuello_botella"] or "desconocido" for f in filas)),
        "origen_volumen": dict(Counter(f["origen_volumen"] for f in filas)),
        "origen_puertas": dict(Counter(
            f.get("origen_puertas") or "desconocido" for f in filas)),
        "top_estres": _ranking(filas, args.top),
        "top_estres_comparable": _ranking(
            [f for f in filas if f.get("indice_comparable")], args.top),
        "top_estres_estimado": _ranking(
            [f for f in filas if not f.get("indice_comparable")], args.top),
        "por_pais": resumen_pais,
        "calidad": agregar_calidad(docs_detalle),
        "sectores": agregar_sectores(docs_detalle),
        "filas": filas,
    }

    os.makedirs(args.salida, exist_ok=True)
    with open(os.path.join(args.salida, "resultados.json"), "w", encoding="utf-8") as f:
        json.dump(informe, f, indent=2, ensure_ascii=False)
    with open(os.path.join(args.salida, "resultados.md"), "w", encoding="utf-8") as f:
        f.write(render_markdown(informe))
    if filas:
        with open(os.path.join(args.salida, "resultados.csv"), "w", encoding="utf-8", newline="") as f:
            escritor = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
            escritor.writeheader()
            escritor.writerows(filas)

    print(f"\nInforme escrito en {args.salida}/resultados.md")
    print(f"   {n_proc} puertos procesados, {n_fall} fallidos "
          f"({informe['cobertura']['tasa_exito_pct']:.1f} % de éxito)")
    d = informe["distribuciones"]["indice_estres"]
    if d.get("n"):
        print(f"   I_EL: mediana {d['mediana']}, media {d['media']}, rango [{d['min']}, {d['max']}]")


if __name__ == "__main__":
    main()
