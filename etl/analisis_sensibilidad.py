import argparse
import copy
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import etl_procesamiento as motor
from muestreo import reparto_proporcional

DELTA = 0.30

PARAMETROS_SENSIBLES = [
    "friccion_rail",
    "friccion_autopista",
    "friccion_primaria",
    "friccion_secundaria",
    "friccion_ultima_milla",
    "penalizacion_tonelaje_limitado",
    "penalizacion_sin_pavimentar",
    "factor_pendiente_camion",
    "factor_pendiente_tren",
    "pendiente_maxima_camion",
    "divisor_poblacion",
    "cuota_tren",
    "masa_puerto_seco",
    "capacidad_fallback_por_puerta",
    "percentil_capacidad",
    "dias_ventana_carga",
    "peso_saturacion",
    "peso_cuello_botella",
    "teus_por_buque_container",
    "teus_por_buque_roro",
    "beta_disuasion",
    "lambda_vulnerabilidad",
    "radio_buffer_puertas_km",
]

ABLACIONES = {
    "completo": {},
    "sin_topografia": {
        "factor_pendiente_camion": 0.0,
        "factor_pendiente_tren": 0.0,
    },
    "sin_friccion_urbana": {
        "divisor_poblacion": float("inf"),
    },
    "sin_ferrocarril": {
        "cuota_tren": 0.0,
    },
    "sin_restricciones_viarias": {
        "penalizacion_tonelaje_limitado": 1.0,
        "penalizacion_sin_pavimentar": 1.0,
        "penalizacion_hgv_restringido": 1.0,
    },
    "sin_jerarquia_viaria": {
        "friccion_autopista": 1.0,
        "friccion_primaria": 1.0,
        "friccion_secundaria": 1.0,
        "friccion_rail": 1.0,
        "friccion_otras": 1.0,
    },
    "sin_disuasion_espacial": {
        "beta_disuasion": 0.0,
    },
    "gravedad_potencia_inversa": {
        "funcion_disuasion": "potencia",
    },
    "baseline_distancia_pura": {
        "factor_pendiente_camion": 0.0,
        "factor_pendiente_tren": 0.0,
        "divisor_poblacion": float("inf"),
        "penalizacion_tonelaje_limitado": 1.0,
        "penalizacion_sin_pavimentar": 1.0,
        "penalizacion_hgv_restringido": 1.0,
        "friccion_autopista": 1.0,
        "friccion_primaria": 1.0,
        "friccion_secundaria": 1.0,
        "friccion_rail": 1.0,
        "friccion_otras": 1.0,
        "cuota_tren": 0.0,
    },
}


PERTURBACIONES_EXPLICITAS = {
    "percentil_capacidad": (0.90, 0.99),
}

LIMITES = {
    "percentil_capacidad": (0.50, 0.999),
    "cuota_tren": (0.0, 0.95),
    "pendiente_maxima_camion": (0.01, 0.60),
    "pendiente_maxima_tren": (0.005, 0.30),
}


def perturbaciones(parametro, valor_base):
    if parametro in PERTURBACIONES_EXPLICITAS:
        return PERTURBACIONES_EXPLICITAS[parametro]

    bajo = valor_base * (1 - DELTA)
    alto = valor_base * (1 + DELTA)

    minimo, maximo = LIMITES.get(parametro, (None, None))
    if minimo is not None:
        bajo = min(max(bajo, minimo), maximo)
        alto = min(max(alto, minimo), maximo)
    return bajo, alto


def ejecutar_escenario(entradas, sobrescrituras):
    motor.aplicar_parametros(sobrescrituras)
    motor.reiniciar_metricas()

    vias = copy.deepcopy(entradas["vias_limpias"])
    industrias = copy.deepcopy(entradas["industrias_limpias"])
    poligono = entradas["poligono"]

    cache_alturas = dict(entradas["cache_alturas"])
    cache_poblacion = dict(entradas["cache_poblacion"])

    volumenes = motor.calcular_volumenes(
        entradas["datos_puerto"], serie_diaria=entradas.get("serie_diaria"))

    t0 = time.perf_counter()
    resumen, geojson, top_calles, industrias_geojson, _perfil, puertas = motor.calcular_estres_logistico(
        vias, industrias, poligono, cache_alturas, cache_poblacion,
        volumenes["volumen_diario_movible"], entradas["lon"], entradas["lat"],
        entradas["matriz_comtrade"], capacidad_diaria=volumenes.get("capacidad_diaria"),
        saturacion_medida=volumenes.get("saturacion"),
    )
    duracion = time.perf_counter() - t0

    traficos = [f["properties"]["trafico"] for f in geojson]
    return {
        "indice_estres": resumen["indice_estres"],
        "saturacion": resumen["saturacion"],
        "vulnerabilidad": resumen["vulnerabilidad"],
        "incremento_interdiccion": resumen["incremento_interdiccion"],
        "origen_puertas": resumen["origen_puertas"],
        "puertas_viales": resumen["puertas_viales"],
        "volumen_movible": volumenes["volumen_diario_movible"],
        "n_vias_geojson": len(geojson),
        "n_industrias_con_demanda": len(industrias_geojson),
        "n_puertas": len(puertas),
        "trafico_medio": round(sum(traficos) / len(traficos), 4) if traficos else 0.0,
        "trafico_maximo": round(max(traficos), 4) if traficos else 0.0,
        "top_calles": top_calles,
        "segundos": round(duracion, 2),
    }


def preparar_puerto(con, datos_puerto, matriz_comtrade):
    nombre = datos_puerto.get("portname", "Desconocido")
    lat = motor.safe_float(datos_puerto.get("lat"))
    lon = motor.safe_float(datos_puerto.get("lon"))

    print(f"\n[{nombre}] Extrayendo entorno de Overture...", flush=True)
    vias, industrias, poligono = motor.extraer_entorno_overture(
        con, lon, lat, radio_km=motor.PARAMETROS["radio_extraccion_km"])
    if not vias:
        print(f"   Sin vías en Overture para {nombre}: se omite.", flush=True)
        return None

    serie_diaria = None
    portid = datos_puerto.get("portid")
    if portid:
        try:
            serie_diaria = motor.portwatch.descargar_serie_diaria(portid)
        except Exception as e:
            print(f"   Sin serie diaria para {portid}: {e}", flush=True)

    volumenes = motor.calcular_volumenes(datos_puerto, serie_diaria=serie_diaria)
    print(f"   Volumen: {volumenes['volumen_diario_movible']:,} "
          f"({volumenes.get('unidad_volumen')}, origen={volumenes.get('origen_volumen')}, "
          f"serie={len(serie_diaria) if serie_diaria else 0} días)", flush=True)

    cache_alturas, cache_poblacion = motor.cargar_caches_puerto(nombre)

    print(f"   Calentando cachés topográficas ({len(vias)} vías)...", flush=True)
    motor.reiniciar_metricas()
    iso3 = motor.obtener_iso3(lat, lon)
    motor.precalcular_caches_en_bloque(copy.deepcopy(vias), cache_alturas, cache_poblacion, iso3)
    motor.guardar_caches_puerto(nombre, cache_alturas, cache_poblacion)

    return {
        "nombre": nombre, "lat": lat, "lon": lon,
        "datos_puerto": datos_puerto,
        "vias_limpias": vias, "industrias_limpias": industrias, "poligono": poligono,
        "cache_alturas": cache_alturas, "cache_poblacion": cache_poblacion,
        "matriz_comtrade": matriz_comtrade, "volumenes": volumenes,
        "datos_puerto": datos_puerto, "serie_diaria": serie_diaria,
    }


def analizar_puerto(entradas):
    resultados = {"puerto": entradas["nombre"], "ablaciones": {}, "sensibilidad": {}}

    print(f"   → Ablaciones ({len(ABLACIONES)} escenarios)", flush=True)
    for nombre, sobrescrituras in ABLACIONES.items():
        res = ejecutar_escenario(entradas, sobrescrituras)
        resultados["ablaciones"][nombre] = res
        print(f"      {nombre:28s} I_EL={res['indice_estres']:6.2f}  "
              f"tráfico medio={res['trafico_medio']:8.3f}  ({res['segundos']}s)", flush=True)

    base = resultados["ablaciones"]["completo"]["indice_estres"]

    print(f"   → Sensibilidad OAT ±{DELTA:.0%} ({len(PARAMETROS_SENSIBLES)} parámetros)", flush=True)
    for parametro in PARAMETROS_SENSIBLES:
        valor_base = motor.PARAMETROS_BASE[parametro]
        valor_bajo, valor_alto = perturbaciones(parametro, valor_base)

        bajo = ejecutar_escenario(entradas, {parametro: valor_bajo})
        alto = ejecutar_escenario(entradas, {parametro: valor_alto})

        variacion_relativa = ((valor_alto - valor_bajo) / valor_base) if valor_base else 0.0
        if base and variacion_relativa:
            elasticidad = ((alto["indice_estres"] - bajo["indice_estres"]) / base) / variacion_relativa
        else:
            elasticidad = 0.0

        resultados["sensibilidad"][parametro] = {
            "valor_base": valor_base,
            "valor_menos": valor_bajo,
            "valor_mas": valor_alto,
            "variacion_relativa": round(variacion_relativa, 4),
            "i_el_menos": bajo["indice_estres"],
            "i_el_base": base,
            "i_el_mas": alto["indice_estres"],
            "elasticidad": round(elasticidad, 4),
        }
        print(f"      {parametro:32s} {bajo['indice_estres']:6.2f} | {base:6.2f} | "
              f"{alto['indice_estres']:6.2f}   elasticidad={elasticidad:+.3f}", flush=True)

    motor.aplicar_parametros()
    return resultados


def render_markdown(resultados, delta):
    L = ["# Análisis de sensibilidad y ablación del I_EL\n"]
    L.append(f"Puertos analizados: **{len(resultados)}**. "
             f"Perturbación OAT: **±{delta:.0%}**.\n")

    L.append("## 1. Ablaciones de la fricción multidimensional\n")
    L.append("Cada columna desactiva un componente del modelo. En `baseline_distancia_pura` "
             "el coste de una arista es únicamente su distancia.\n")
    nombres = list(ABLACIONES)
    L.append("| Puerto | " + " | ".join(f"`{n}`" for n in nombres) + " |")
    L.append("|---" * (len(nombres) + 1) + "|")
    for r in resultados:
        celdas = [f"{r['ablaciones'][n]['indice_estres']:.2f}" for n in nombres]
        L.append(f"| {r['puerto']} | " + " | ".join(celdas) + " |")
    L.append("")

    L.append("### 1.1 Desglose por componente\n")
    L.append("| Puerto | Escenario | Saturacion | Vulnerabilidad | Incremento interdiccion | Puertas |")
    L.append("|---|---|---|---|---|---|")
    for r in resultados:
        for n in nombres:
            a = r["ablaciones"][n]
            L.append(f"| {r['puerto']} | `{n}` | {a.get('saturacion', 0):.3f} | "
                     f"{a.get('vulnerabilidad', 0):.3f} | "
                     f"{a.get('incremento_interdiccion', 0):.4f} | "
                     f"{a.get('puertas_viales', 0)} ({a.get('origen_puertas', '?')}) |")
    L.append("")
    L.append("| Puerto | Δ I_EL completo vs. distancia pura | Δ relativa |")
    L.append("|---|---|---|")
    for r in resultados:
        completo = r["ablaciones"]["completo"]["indice_estres"]
        plano = r["ablaciones"]["baseline_distancia_pura"]["indice_estres"]
        rel = ((completo - plano) / plano * 100.0) if plano else float("nan")
        L.append(f"| {r['puerto']} | {completo - plano:+.2f} | {rel:+.1f}% |")
    L.append("")

    L.append(f"## 2. Sensibilidad de un factor cada vez (±{delta:.0%})\n")
    L.append("La elasticidad es la variación relativa del I_EL por unidad de variación "
             "relativa del parámetro. Un valor próximo a 0 indica que el resultado es "
             "poco sensible a ese parámetro.\n")
    L.append("| Parámetro | Valor base | Rango ensayado | Elasticidad media | |Elasticidad| |")
    L.append("|---|---|---|---|---|")
    agregado = {}
    for r in resultados:
        for p, d in r["sensibilidad"].items():
            agregado.setdefault(p, []).append(d["elasticidad"])
    filas = []
    for p, valores in agregado.items():
        media = sum(valores) / len(valores)
        filas.append((abs(media), p, media))
    for absmedia, p, media in sorted(filas, reverse=True):
        d = resultados[0]["sensibilidad"][p]
        base_val = d["valor_base"]
        rango = f"{d.get('valor_menos', '?')} → {d.get('valor_mas', '?')}"
        filas_txt = f"| `{p}` | {base_val} | {rango} | {media:+.4f} | {absmedia:.4f} |"
        L.append(filas_txt)
    L.append("")
    L.append("> Una elasticidad nula no implica necesariamente robustez: también puede indicar "
             "que el término no interviene en el resultado con la configuración por defecto.\n")
    return "\n".join(L)


def resolver_lista(tallas, n_puertos, log=print):
    catalogos = {}
    for talla in tallas:
        try:
            obj = motor.s3_client.get_object(
                Bucket=motor.S3_BUCKET,
                Key=f"fuentes_externas/fmi_ports/puertos_{talla}.json")
            catalogos[talla] = json.loads(obj["Body"].read().decode("utf-8"))
        except Exception as e:
            log(f"   Talla {talla} no disponible: {e}")
            catalogos[talla] = []

    cuota = reparto_proporcional({t: len(c) for t, c in catalogos.items()}, n_puertos)
    lista = []
    for talla in tallas:
        elegidos = catalogos[talla][:cuota.get(talla, 0)]
        for p in elegidos:
            p["_talla"] = talla
        lista.extend(elegidos)
        log(f"   Talla {talla}: {len(elegidos)}/{len(catalogos[talla])} puertos")
    return lista


def escribir_informe(resultados, salida):
    os.makedirs(salida, exist_ok=True)
    with open(os.path.join(salida, "sensibilidad.json"), "w", encoding="utf-8") as f:
        json.dump({"delta": DELTA, "ablaciones": {k: v for k, v in ABLACIONES.items()},
                   "resultados": resultados}, f, indent=2, ensure_ascii=False, default=str)
    with open(os.path.join(salida, "sensibilidad.md"), "w", encoding="utf-8") as f:
        f.write(render_markdown(resultados, DELTA))
    print(f"\nInforme escrito en {salida}/sensibilidad.md")


def combinar_parciales(directorio, salida):
    import glob
    rutas = sorted(glob.glob(os.path.join(directorio, "**", "puerto_*.json"),
                             recursive=True))
    if not rutas:
        print(f"No hay parciales que combinar en {directorio}.")
        sys.exit(1)

    parciales, omitidos = [], []
    for ruta in rutas:
        with open(ruta, encoding="utf-8") as f:
            p = json.load(f)
        if p.get("omitido"):
            omitidos.append(p.get("puerto", ruta))
        else:
            parciales.append(p)

    parciales.sort(key=lambda p: p.get("_indice", 0))
    resultados = [p["resultado"] for p in parciales]

    print(f"{len(resultados)} puertos combinados de {len(rutas)} parciales.")
    if omitidos:
        print(f"   Omitidos por falta de datos: "
              f"{', '.join(str(o) for o in omitidos)}")
    if not resultados:
        print("Ningún puerto pudo analizarse.")
        sys.exit(1)

    escribir_informe(resultados, salida)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Sensibilidad y ablación del I_EL")
    ap.add_argument("--puertos", type=int, default=12,
                    help="nº de puertos a analizar (repartidos entre las tallas)")
    ap.add_argument("--tallas", default="S,M,L",
                    help="tallas de las que tomar los puertos, separadas por comas")
    ap.add_argument("--salida", default="docs/sensibilidad")
    ap.add_argument("--plan", action="store_true",
                    help="calcula el reparto de puertos y sale, sin analizar nada.")
    ap.add_argument("--fichero-plan", default=None,
                    help="con --plan, escribe el JSON del reparto en esta ruta")
    ap.add_argument("--indice", type=int, default=None,
                    help="analiza solo el puerto que ocupa esa posición en el plan y "
                         "deja su parcial en {salida}/puerto_NNN.json")
    ap.add_argument("--combinar", default=None,
                    help="directorio con los parciales; los combina y escribe el "
                         "informe final en --salida")
    args = ap.parse_args()

    if args.combinar:
        combinar_parciales(args.combinar, args.salida)
        return

    log = (lambda *a, **k: print(*a, file=sys.stderr, **k)) if args.plan else print

    log("Cargando catálogo y matriz económica...", flush=True)
    tallas = [t.strip().upper() for t in args.tallas.split(",") if t.strip()]

    lista = resolver_lista(tallas, args.puertos, log=log)

    if not lista:
        log("No hay puertos en esas tallas. Ejecuta antes clasificar_puertos.py.")
        sys.exit(1)

    if args.plan:
        plan_json = json.dumps([
            {"indice": i,
             "nombre": p.get("portname", "Desconocido"),
             "portid": p.get("portid", ""),
             "talla": p.get("_talla", "?")}
            for i, p in enumerate(lista)
        ], ensure_ascii=False)

        if args.fichero_plan:
            directorio = os.path.dirname(os.path.abspath(args.fichero_plan))
            os.makedirs(directorio, exist_ok=True)
            with open(args.fichero_plan, "w", encoding="utf-8") as f:
                f.write(plan_json)
            log(f"Reparto escrito en {args.fichero_plan} ({len(lista)} puertos)")

        print(plan_json)
        return

    if args.indice is not None:
        if not (0 <= args.indice < len(lista)):
            print(f"Índice {args.indice} fuera del plan "
                  f"(0..{len(lista) - 1}).")
            sys.exit(1)
        seleccion = [(args.indice, lista[args.indice])]
    else:
        seleccion = list(enumerate(lista))

    matriz = motor.cargar_perfiles_comtrade_s3()
    con = motor.inicializar_duckdb()

    resultados = []
    for indice, datos_puerto in seleccion:
        entradas = preparar_puerto(con, datos_puerto, matriz)
        resultado = analizar_puerto(entradas) if entradas else None

        if args.indice is not None:
            os.makedirs(args.salida, exist_ok=True)
            parcial = {"_indice": indice,
                       "puerto": datos_puerto.get("portname", "Desconocido"),
                       "omitido": resultado is None,
                       "resultado": resultado}
            destino = os.path.join(args.salida, f"puerto_{indice:03d}.json")
            with open(destino, "w", encoding="utf-8") as f:
                json.dump(parcial, f, indent=2, ensure_ascii=False, default=str)
            print(f"\nParcial escrito en {destino}"
                  f"{' (puerto omitido)' if resultado is None else ''}")
        elif resultado:
            resultados.append(resultado)
    con.close()

    if args.indice is not None:
        return

    if not resultados:
        print("Ningún puerto pudo analizarse.")
        sys.exit(1)

    escribir_informe(resultados, args.salida)


if __name__ == "__main__":
    main()
