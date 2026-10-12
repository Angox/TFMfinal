import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

ORG = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"
CABECERAS = {"User-Agent": "TFM-Hinterland/1.0"}

LOTE = 100


def consultar(servicio, params, reintentos=3):
    url = f"{ORG}/{servicio}/FeatureServer/0/query?" + urllib.parse.urlencode(params)
    ultimo = None
    for intento in range(1, reintentos + 1):
        try:
            peticion = urllib.request.Request(url, headers=CABECERAS)
            with urllib.request.urlopen(peticion, timeout=120) as respuesta:
                return json.loads(respuesta.read().decode("utf-8"))
        except Exception as e:
            ultimo = e
            print(f"      reintento {intento}/{reintentos} tras: {e}", flush=True)
            time.sleep(5 * intento)
    raise ultimo


def cargar_catalogo_completo():
    puertos, desplazamiento = [], 0
    while True:
        datos = consultar("PortWatch_ports_database", {
            "where": "1=1",
            "outFields": "portid,portname,country,continent,vessel_count_total",
            "f": "json",
            "resultRecordCount": 1000,
            "resultOffset": desplazamiento,
            "orderByFields": "portid ASC",
        })
        lote = [f["attributes"] for f in datos.get("features", [])]
        puertos.extend(lote)
        if not lote or not datos.get("exceededTransferLimit"):
            break
        desplazamiento += len(lote)
    return puertos


def cargar_muestra_de_s3():
    import boto3
    from config_aws import AWS_REGION, S3_BUCKET

    s3 = boto3.client("s3", region_name=AWS_REGION)
    puertos = []
    for talla in ("S", "M", "L"):
        clave = f"fuentes_externas/fmi_ports/puertos_{talla}.json"
        try:
            cuerpo = s3.get_object(Bucket=S3_BUCKET, Key=clave)["Body"].read()
        except Exception as e:
            print(f"   no se pudo leer {clave}: {e}", flush=True)
            continue
        for p in json.loads(cuerpo.decode("utf-8")):
            p["talla"] = talla
            puertos.append(p)
    return puertos


def dias_por_puerto(portids):
    cobertura = {}
    total_lotes = (len(portids) + LOTE - 1) // LOTE
    for i in range(0, len(portids), LOTE):
        lote = [p for p in portids[i:i + LOTE] if p]
        if not lote:
            continue
        lista = ",".join(f"'{p}'" for p in lote)
        estadisticos = [{"statisticType": "count", "onStatisticField": "portid",
                         "outStatisticFieldName": "n_dias"}]
        t0 = time.time()
        datos = consultar("Daily_Ports_Data", {
            "where": f"portid IN ({lista})",
            "outStatistics": json.dumps(estadisticos),
            "groupByFieldsForStatistics": "portid",
            "f": "json",
            "resultRecordCount": 1000,
        })
        for f in datos.get("features", []):
            a = f["attributes"]
            cobertura[a["portid"]] = a["n_dias"]
        print(f"   lote {i // LOTE + 1}/{total_lotes}: {len(lote)} puertos, "
              f"{len(datos.get('features', []))} con datos ({time.time() - t0:.1f}s)", flush=True)
    return cobertura


def escalas(puerto):
    try:
        return float(puerto.get("vessel_count_total") or 0)
    except (TypeError, ValueError):
        return 0.0


def es_terminal_offshore(puerto):
    return str(puerto.get("portid") or "").startswith("fso")


def cobertura_por_cuartil(puertos, cobertura):
    ordenados = sorted(puertos, key=escalas, reverse=True)
    n = len(ordenados)
    if n < 4:
        return []
    etiquetas = ["Q1 (mayores)", "Q2", "Q3", "Q4 (menores)"]
    filas = []
    for i, etiqueta in enumerate(etiquetas):
        tramo = ordenados[i * n // 4:(i + 1) * n // 4]
        if not tramo:
            continue
        cubiertos = sum(1 for p in tramo if cobertura.get(p.get("portid")))
        filas.append({
            "cuartil": etiqueta,
            "total": len(tramo),
            "cubiertos": cubiertos,
            "pct": cubiertos / len(tramo) * 100.0,
            "escalas_max": int(escalas(tramo[0])),
            "escalas_min": int(escalas(tramo[-1])),
        })
    return filas


def render_markdown(inf):
    L = ["# Cobertura del dataset diario del FMI\n"]
    L.append(f"Medido el {inf['fecha']} sobre **{inf['fuente']}**.\n")

    c = inf["resumen"]
    L.append("| Métrica | Valor |")
    L.append("|---|---|")
    L.append(f"| Puertos analizados | {c['total']} |")
    L.append(f"| Con volumen **medido** (`Daily_Ports_Data`) | {c['cubiertos']} ({c['cobertura_pct']:.1f} %) |")
    L.append(f"| Con volumen **estimado** (recuento de escalas) | {c['sin_cubrir']} ({100 - c['cobertura_pct']:.1f} %) |")
    L.append(f"| Días de serie por puerto (mediana) | {c['dias_mediana']} |")
    L.append("")

    if inf["por_talla"]:
        L.append("## Cobertura por talla\n")
        L.append("| Talla | Puertos | Medidos | % |")
        L.append("|---|---|---|---|")
        for talla, d in sorted(inf["por_talla"].items()):
            L.append(f"| {talla} | {d['total']} | {d['cubiertos']} | {d['pct']:.1f} % |")
        L.append("")

    if inf.get("por_cuartil"):
        L.append("## Cobertura por tamaño de puerto\n")
        L.append("Cuartiles según el número de escalas anuales del puerto.\n")
        L.append("| Cuartil | Puertos | Medidos | % | Escalas/año |")
        L.append("|---|---|---|---|---|")
        for f in inf["por_cuartil"]:
            L.append(f"| {f['cuartil']} | {f['total']} | {f['cubiertos']} | {f['pct']:.1f} % | "
                     f"{f['escalas_max']:,} – {f['escalas_min']:,} |")
        L.append("")

    if inf.get("offshore_excluidos"):
        L.append(f"> Se excluyen {inf['offshore_excluidos']} terminales offshore (`fso*`): "
                 "plataformas flotantes sin red viaria asociada y sin registros en el "
                 "dataset diario.\n")

    if inf["por_continente"]:
        L.append("## Cobertura por continente\n")
        L.append("| Continente | Puertos | Medidos | % |")
        L.append("|---|---|---|---|")
        for cont, d in sorted(inf["por_continente"].items(), key=lambda x: -x[1]["total"]):
            L.append(f"| {cont} | {d['total']} | {d['cubiertos']} | {d['pct']:.1f} % |")
        L.append("")

    if inf["sin_cubrir"]:
        L.append(f"## Puertos sin volumen medido ({len(inf['sin_cubrir'])})\n")
        L.append("Para estos puertos el volumen se estima a partir del recuento de escalas.\n")
        L.append("| Puerto | País | Escalas/año |")
        L.append("|---|---|---|")
        for p in inf["sin_cubrir"][:60]:
            L.append(f"| {p['portname']} | {p.get('country', '—')} | {p.get('vessel_count_total', '—')} |")
        if len(inf["sin_cubrir"]) > 60:
            L.append(f"| … y {len(inf['sin_cubrir']) - 60} más | | |")
        L.append("")

    return "\n".join(L)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Cobertura de Daily_Ports_Data")
    ap.add_argument("--catalogo", action="store_true",
                    help="usa el catálogo completo del FMI en vez de la muestra en S3")
    ap.add_argument("--limite", type=int, default=0, help="analiza solo los N primeros")
    ap.add_argument("--incluir-offshore", action="store_true",
                    help="no excluye las terminales offshore fso* (por defecto se excluyen)")
    ap.add_argument("--salida", default="docs/cobertura")
    args = ap.parse_args()

    if args.catalogo:
        print("Descargando el catálogo completo de PortWatch...", flush=True)
        puertos = cargar_catalogo_completo()
        fuente = "catálogo completo de PortWatch"
    else:
        print("Leyendo la muestra clasificada en S3...", flush=True)
        puertos = cargar_muestra_de_s3()
        fuente = "muestra clasificada en S3"

    offshore = [p for p in puertos if es_terminal_offshore(p)]
    if offshore and not args.incluir_offshore:
        puertos = [p for p in puertos if not es_terminal_offshore(p)]
        print(f"   {len(offshore)} terminales offshore (fso*) excluidas: no tienen hinterland")

    if args.limite:
        puertos = puertos[:args.limite]
    if not puertos:
        print("No hay puertos que analizar.")
        sys.exit(1)
    print(f"   {len(puertos)} puertos\n")

    print("Comprobando presencia en Daily_Ports_Data...", flush=True)
    cobertura = dias_por_puerto([p.get("portid") for p in puertos])

    cubiertos = [p for p in puertos if cobertura.get(p.get("portid"))]
    sin_cubrir = [p for p in puertos if not cobertura.get(p.get("portid"))]
    dias = sorted(cobertura.values())

    def agrupar(campo):
        grupos = {}
        for p in puertos:
            clave = str(p.get(campo) or "desconocido")
            g = grupos.setdefault(clave, {"total": 0, "cubiertos": 0})
            g["total"] += 1
            if cobertura.get(p.get("portid")):
                g["cubiertos"] += 1
        for g in grupos.values():
            g["pct"] = g["cubiertos"] / g["total"] * 100.0 if g["total"] else 0.0
        return grupos

    informe = {
        "fecha": time.strftime("%Y-%m-%d"),
        "fuente": fuente,
        "resumen": {
            "total": len(puertos),
            "cubiertos": len(cubiertos),
            "sin_cubrir": len(sin_cubrir),
            "cobertura_pct": len(cubiertos) / len(puertos) * 100.0,
            "dias_mediana": dias[len(dias) // 2] if dias else 0,
            "dias_min": dias[0] if dias else 0,
            "dias_max": dias[-1] if dias else 0,
        },
        "offshore_excluidos": len(offshore) if not args.incluir_offshore else 0,
        "por_cuartil": cobertura_por_cuartil(puertos, cobertura),
        "por_talla": agrupar("talla") if any("talla" in p for p in puertos) else {},
        "por_continente": agrupar("continent") if any(p.get("continent") for p in puertos) else {},
        "sin_cubrir": [{"portid": p.get("portid"), "portname": p.get("portname"),
                        "country": p.get("country"),
                        "vessel_count_total": p.get("vessel_count_total")} for p in sin_cubrir],
        "dias_por_puerto": cobertura,
    }

    os.makedirs(args.salida, exist_ok=True)
    with open(os.path.join(args.salida, "cobertura.json"), "w", encoding="utf-8") as f:
        json.dump(informe, f, indent=2, ensure_ascii=False)
    with open(os.path.join(args.salida, "cobertura.md"), "w", encoding="utf-8") as f:
        f.write(render_markdown(informe))

    r = informe["resumen"]
    print(f"\nInforme en {args.salida}/cobertura.md")
    print(f"   {r['cubiertos']}/{r['total']} puertos con volumen MEDIDO "
          f"({r['cobertura_pct']:.1f} %)")
    print(f"   {r['sin_cubrir']} usarán la estimación por escalas")
    if informe["por_continente"]:
        peor = min(informe["por_continente"].items(), key=lambda x: x[1]["pct"])
        print(f"   Peor continente: {peor[0]} ({peor[1]['pct']:.1f} %)")


if __name__ == "__main__":
    main()
