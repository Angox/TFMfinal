import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from catalogo_precios import (
    PENDIENTE, PreciosAWS, PreciosAzure, PreciosGCP,
    cargar_precios_manuales, hoy, precio_manual,
)
from perfil_carga import UNIDADES, PerfilCarga

EQUIVALENCIAS = {
    "computo_lote_vcpu_h": ("AWS Batch sobre Fargate Spot", "Cloud Run Jobs", "Container Apps Jobs"),
    "computo_lote_gb_h": ("AWS Batch sobre Fargate Spot", "Cloud Run Jobs", "Container Apps Jobs"),
    "computo_web_vcpu_h": ("ECS Fargate", "Cloud Run", "Container Apps"),
    "computo_web_gb_h": ("ECS Fargate", "Cloud Run", "Container Apps"),
    "almacenamiento_gb_mes": ("S3 Standard", "Cloud Storage Standard", "Blob Storage Hot"),
    "salida_internet_gb": ("S3 Data Transfer Out", "Network Egress", "Bandwidth Data Transfer Out"),
    "peticiones_escritura_millar": ("S3 PUT", "Cloud Storage Class A", "Blob Write Operations"),
    "peticiones_lectura_millar": ("S3 GET", "Cloud Storage Class B", "Blob Read Operations"),
    "registro_contenedores_gb_mes": ("ECR", "Artifact Registry", "Container Registry"),
    "logs_gb": ("CloudWatch Logs", "Cloud Logging", "Azure Monitor Logs"),
    "llm_tokens_entrada_millon": ("Bedrock · Nova Lite", "Gemini API · gemini-2.5-flash-lite", "Foundry Models · gpt-4.1-nano"),
    "llm_tokens_salida_millon": ("Bedrock · Nova Lite", "Gemini API · gemini-2.5-flash-lite", "Foundry Models · gpt-4.1-nano"),
}


def precios_aws(region):
    p = PreciosAWS(region)
    return {
        "computo_lote_vcpu_h": p.buscar("AmazonECS", {"usagetype": "Fargate-vCPU-Hours:perCPU"}, "vCPU·h"),
        "computo_lote_gb_h": p.buscar("AmazonECS", {"usagetype": "Fargate-GB-Hours"}, "GB·h"),
        "computo_web_vcpu_h": p.buscar("AmazonECS", {"usagetype": "Fargate-vCPU-Hours:perCPU"}, "vCPU·h"),
        "computo_web_gb_h": p.buscar("AmazonECS", {"usagetype": "Fargate-GB-Hours"}, "GB·h"),
        "almacenamiento_gb_mes": p.buscar("AmazonS3", {"usagetype": "TimedStorage-ByteHrs",
                                                      "storageClass": "General Purpose"}, "GB·mes"),
        "salida_internet_gb": p.buscar(
            "AWSDataTransfer",
            {"transferType": "AWS Outbound", "toLocation": "External"}, "GB",
            excluye=["accelerated"]),
        "peticiones_escritura_millar": p.buscar("AmazonS3", {"usagetype": "Requests-Tier1"}, "millar",
                                                excluye=["Table Bucket", "MRAP", "Multi-Region"]),
        "peticiones_lectura_millar": p.buscar("AmazonS3", {"usagetype": "Requests-Tier2"}, "millar",
                                              excluye=["Table Bucket", "MRAP", "Multi-Region"]),
        "registro_contenedores_gb_mes": p.buscar("AmazonECR", {"usagetype": "TimedStorage-ByteHrs"}, "GB·mes"),
        "logs_gb": p.buscar("AmazonCloudWatch", {"usagetype": "DataProcessing-Bytes"}, "GB"),
        "llm_tokens_entrada_millon": p.buscar(
            "AmazonBedrock",
            {"model": "Nova Lite", "inferenceType": "Input tokens",
             "feature": "On-demand Inference"}, "millón de tokens"),
        "llm_tokens_salida_millon": p.buscar(
            "AmazonBedrock",
            {"model": "Nova Lite", "inferenceType": "Output tokens",
             "feature": "On-demand Inference"}, "millón de tokens"),
    }


def precios_azure(region):
    p = PreciosAzure(region)
    apps = "serviceName eq 'Azure Container Apps' and armRegionName eq '{region}'"
    blob = "serviceName eq 'Storage' and armRegionName eq '{region}'"
    return {
        "computo_lote_vcpu_h": p.buscar(apps, "vCPU·h", contiene=["vcpu"]),
        "computo_lote_gb_h": p.buscar(apps, "GB·h", contiene=["memory"]),
        "computo_web_vcpu_h": p.buscar(apps, "vCPU·h", contiene=["vcpu"]),
        "computo_web_gb_h": p.buscar(apps, "GB·h", contiene=["memory"]),
        "almacenamiento_gb_mes": p.buscar(blob, "GB·mes", contiene=["blob storage", "hot lrs", "data stored"],
                                          excluye=["premium", "archive", "cool", "data lake"]),
        "salida_internet_gb": p.buscar(
            "serviceName eq 'Bandwidth' and armRegionName eq '{region}'", "GB",
            contiene=["data transfer out"], excluye=["intra", "zone", "express"]),
        "peticiones_escritura_millar": p.buscar(
            blob, "millar", contiene=["blob storage", "hot lrs write operations"],
            excluye=["premium", "archive", "cool", "cold", "data lake", "iterative",
                     "zrs", "grs", "ra-"]),
        "peticiones_lectura_millar": p.buscar(
            blob, "millar", contiene=["blob storage", "hot read operations"],
            excluye=["premium", "archive", "cool", "cold", "data lake", "iterative",
                     "zrs", "grs", "ra-"]),
        "registro_contenedores_gb_mes": p.buscar(
            "serviceName eq 'Container Registry' and armRegionName eq '{region}'",
            "GB·mes", contiene=["data stored"], excluye=["replication"]),
        "logs_gb": p.buscar(
            "serviceName eq 'Log Analytics' and armRegionName eq '{region}'",
            "GB", contiene=["analytics logs data ingestion"],
            excluye=["basic", "auxiliary", "free", "retention", "analyzed"]),
        "llm_tokens_entrada_millon": p.buscar(
            "serviceName eq 'Foundry Models' and armRegionName eq '{region}'",
            "millón de tokens", contiene=["azure openai", "gpt 4.1 nano inp glbl"],
            excluye=["batch", "cached", "cchd", "-ft", " ft "]),
        "llm_tokens_salida_millon": p.buscar(
            "serviceName eq 'Foundry Models' and armRegionName eq '{region}'",
            "millón de tokens", contiene=["azure openai", "gpt 4.1 nano outp glbl"],
            excluye=["batch", "cached", "cchd", "-ft", " ft "]),
    }


def precios_gcp(region):
    p = PreciosGCP(region)
    RUN = "Cloud Run"
    ALMACEN = "Cloud Storage"
    FUERA_CLASE = ["nearline", "coldline", "archive", "durable reduced", "autoclass",
                   "dual-region", "multi-region", "early delete", "hns", "tagging"]
    return {
        "computo_lote_vcpu_h": p.buscar(RUN, ["jobs cpu"], "vCPU·h", excluye=["delayed"]),
        "computo_lote_gb_h": p.buscar(RUN, ["jobs memory"], "GB·h", excluye=["delayed"]),
        "computo_web_vcpu_h": p.buscar(RUN, ["services cpu", "request-based"], "vCPU·h"),
        "computo_web_gb_h": p.buscar(RUN, ["services memory", "request-based"], "GB·h"),
        "almacenamiento_gb_mes": p.buscar(ALMACEN, ["standard storage"], "GB·mes",
                                          excluye=FUERA_CLASE),
        "salida_internet_gb": p.buscar(ALMACEN, ["worldwide destinations"], "GB"),
        "peticiones_escritura_millar": p.buscar(ALMACEN, ["regional standard class a"], "millar"),
        "peticiones_lectura_millar": p.buscar(ALMACEN, ["regional standard class b"], "millar"),
        "registro_contenedores_gb_mes": p.buscar("Artifact Registry",
                                                 ["artifact registry storage"], "GB·mes"),
        "logs_gb": p.buscar(("Cloud Logging", "Stackdriver Logging"),
                            ["log storage cost"], "GB"),
        "llm_tokens_entrada_millon": PENDIENTE(
            "millón de tokens",
            "anota en precios_manuales.json el precio de entrada de "
            "gemini-2.5-flash-lite (https://ai.google.dev/pricing)"),
        "llm_tokens_salida_millon": PENDIENTE(
            "millón de tokens",
            "anota en precios_manuales.json el precio de salida de "
            "gemini-2.5-flash-lite (https://ai.google.dev/pricing)"),
    }


def completar_con_manuales(precios, manuales, proveedor):
    for concepto, precio in precios.items():
        if precio.origen == "pendiente":
            precios[concepto] = precio_manual(manuales, proveedor, concepto,
                                              UNIDADES[concepto], precio)
    return precios


def calcular(perfil, precios, nube):
    consumos = perfil.consumos()
    filas, total, pendientes = [], 0.0, 0
    descuento = DESCUENTO_INTERRUMPIBLE.get(nube, 0.0)
    for concepto, cantidad in consumos.items():
        precio = precios.get(concepto)
        if precio is None or precio.valor is None:
            filas.append({"concepto": concepto, "cantidad": cantidad,
                          "unidad": UNIDADES[concepto], "precio_unitario": None,
                          "coste": None, "origen": "pendiente",
                          "nota": precio.nota if precio else "sin consulta definida"})
            pendientes += 1
            continue
        factor = 1.0
        if concepto.startswith("computo_lote") and perfil.fraccion_interrumpible > 0:
            factor = 1 - perfil.fraccion_interrumpible * descuento
        precio_efectivo = precio.valor * factor
        coste = cantidad * precio_efectivo
        total += coste
        filas.append({"concepto": concepto, "cantidad": round(cantidad, 2),
                      "unidad": UNIDADES[concepto],
                      "precio_lista": precio.valor,
                      "precio_unitario": precio_efectivo,
                      "descuento_aplicado": round(1 - factor, 4),
                      "coste": round(coste, 4), "origen": precio.origen,
                      "referencia": precio.referencia, "nota": precio.nota})
    return {"filas": filas, "total_usd": round(total, 2), "conceptos_pendientes": pendientes}


DESCUENTO_INTERRUMPIBLE = {
    "aws": 0.70,
    "gcp": 0.0,
    "azure": 0.0,
}


ARQUITECTURA_NO_COMPARABLE = [
    ("azure", "registro_contenedores_gb_mes",
     "Azure Container Registry cobra una cuota fija por registro y día además del "
     "$/GB·mes de la tabla: 0,1666 $/día en Basic (~5,07 $/mes), 0,6666 en Standard y "
     "1,6666 en Premium. La cuota incluye 10 GB de almacenamiento en Basic, por lo que con "
     "los 6 GB de este perfil solo se paga la cuota fija. ECR y Artifact Registry cobran "
     "únicamente por GB·mes, de modo que el registro cuesta ~5,07 $/mes en Azure frente a "
     "0,60 $/mes en AWS y GCP."),
]


def render_markdown(perfil, resultados, region_por_nube):
    L = []
    L.append("# Estudio comparativo de costes: AWS vs GCP vs Azure\n")
    L.append(f"_Generado el {hoy()}._\n")
    L.append("## Metodología\n")
    L.append("Comparación modelada: se aplican las listas de precios públicas de cada "
             "proveedor a un perfil de carga común. Complementa al coste medido en AWS Cost "
             "Explorer y en la facturación de GCP, y estima el coste que habría tenido el "
             "despliegue en otra nube. En cada desglose, coste = cantidad × precio efectivo.\n")
    L.append("### Capacidad interrumpible\n")
    L.append("El descuento por capacidad interrumpible solo se aplica donde el proveedor "
             "lo ofrece para el servicio utilizado:\n")
    L.append("| Proveedor | Descuento aplicado | Motivo |")
    L.append("|---|---|---|")
    L.append(f"| AWS | {DESCUENTO_INTERRUMPIBLE['aws']:.0%} | Fargate Spot, configuración "
             "desplegada. Porcentaje estimado. |")
    L.append(f"| GCP | {DESCUENTO_INTERRUMPIBLE['gcp']:.0%} | Ninguno de los 703 SKU de Cloud Run "
             "es spot o preemptible. Precio de lista. |")
    L.append(f"| Azure | {DESCUENTO_INTERRUMPIBLE['azure']:.0%} | Container Apps no publica tarifa "
             "spot ni low-priority en esta región. Precio de lista. |")
    L.append("")

    if ARQUITECTURA_NO_COMPARABLE:
        L.append("### Partidas con modelo de precios no equivalente\n")
        L.append("Diferencias en el modelo de precios que no se reflejan en el precio "
                 "unitario de la tabla:\n")
        for nube, concepto, texto in ARQUITECTURA_NO_COMPARABLE:
            L.append(f"- **{nube.upper()} · `{concepto}`** — {texto}\n")

    L.append("## Perfil de carga\n")
    L.append("| Magnitud | Valor |")
    L.append("|---|---|")
    for k, v in perfil.describir().items():
        L.append(f"| {k} | {v} |")
    L.append("")

    L.append("## Equivalencia de servicios\n")
    L.append("| Concepto | AWS | GCP | Azure |")
    L.append("|---|---|---|---|")
    for concepto, (a, g, z) in EQUIVALENCIAS.items():
        L.append(f"| `{concepto}` | {a} | {g} | {z} |")
    L.append("")

    L.append("## Coste mensual estimado\n")
    L.append("| Proveedor | Región | Coste mensual (USD) | Coste por puerto (USD) | Conceptos sin precio |")
    L.append("|---|---|---|---|---|")
    puertos = max(perfil.total_puertos() * perfil.ejecuciones_etl_mes, 1)
    for nube, res in resultados.items():
        por_puerto = round(res["total_usd"] / puertos, 4)
        aviso = "—" if res["conceptos_pendientes"] == 0 else f"{res['conceptos_pendientes']}"
        L.append(f"| {nube.upper()} | {region_por_nube[nube]} | {res['total_usd']:.2f} | "
                 f"{por_puerto:.4f} | {aviso} |")
    L.append("")
    if any(res["conceptos_pendientes"] for res in resultados.values()):
        L.append("> Los totales con conceptos sin precio están incompletos.\n")

    for nube, res in resultados.items():
        L.append(f"## Desglose · {nube.upper()}\n")
        L.append("| Concepto | Cantidad | Unidad | Precio lista (USD) | Dto. | Precio efectivo (USD) | Coste (USD) | Origen | Referencia |")
        L.append("|---|---|---|---|---|---|---|---|---|")
        for f in res["filas"]:
            pl = "—" if f.get("precio_lista") is None else f"{f['precio_lista']:.6f}"
            pu = "—" if f["precio_unitario"] is None else f"{f['precio_unitario']:.6f}"
            dto = f"{f.get('descuento_aplicado', 0):.0%}" if f.get("precio_lista") is not None else "—"
            co = "PENDIENTE" if f["coste"] is None else f"{f['coste']:.4f}"
            L.append(f"| `{f['concepto']}` | {f['cantidad']} | {f['unidad']} | {pl} | {dto} | "
                     f"{pu} | {co} | {f['origen']} | {f.get('referencia', '')} |")
        L.append("")
    return "\n".join(L)


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Estudio comparativo de costes multi-nube")
    ap.add_argument("--salida", default="docs/costes", help="carpeta donde escribir el informe")
    ap.add_argument("--region-aws", default="us-west-2")
    ap.add_argument("--region-gcp", default="europe-southwest1")
    ap.add_argument("--region-azure", default="westeurope")
    ap.add_argument("--puertos", type=int, default=None,
                    help="nº total de puertos al mes (reparte 75/20/5 entre tallas S/M/L)")
    args = ap.parse_args()

    perfil = PerfilCarga()
    if args.puertos:
        perfil.puertos_por_talla = {
            "S": int(args.puertos * 0.75),
            "M": int(args.puertos * 0.20),
            "L": max(args.puertos - int(args.puertos * 0.75) - int(args.puertos * 0.20), 0),
        }

    manuales = cargar_precios_manuales()
    region_por_nube = {"aws": args.region_aws, "gcp": args.region_gcp, "azure": args.region_azure}

    print("Consultando listas de precios...", flush=True)
    catalogos = {}
    for nube, obtener, region in (
        ("aws", precios_aws, args.region_aws),
        ("gcp", precios_gcp, args.region_gcp),
        ("azure", precios_azure, args.region_azure),
    ):
        print(f"   -> {nube.upper()} ({region})", flush=True)
        try:
            catalogos[nube] = completar_con_manuales(obtener(region), manuales, nube)
        except Exception as e:
            print(f"      fallo consultando {nube}: {e}", flush=True)
            catalogos[nube] = completar_con_manuales(
                {c: None for c in UNIDADES}, manuales, nube)

    resultados = {nube: calcular(perfil, cat, nube) for nube, cat in catalogos.items()}

    os.makedirs(args.salida, exist_ok=True)
    ruta_md = os.path.join(args.salida, "estudio_costes.md")
    ruta_json = os.path.join(args.salida, "estudio_costes.json")

    with open(ruta_md, "w", encoding="utf-8") as f:
        f.write(render_markdown(perfil, resultados, region_por_nube))
    with open(ruta_json, "w", encoding="utf-8") as f:
        json.dump({
            "fecha": hoy(),
            "descuento_interrumpible": DESCUENTO_INTERRUMPIBLE,
            "regiones": region_por_nube,
            "perfil": perfil.describir(),
            "consumos": perfil.consumos(),
            "resultados": resultados,
            "precios": {n: {c: (p.a_dict() if p else None) for c, p in cat.items()}
                        for n, cat in catalogos.items()},
        }, f, indent=2, ensure_ascii=False)

    print(f"\nInforme escrito en {ruta_md}")
    for nube, res in resultados.items():
        aviso = "" if res["conceptos_pendientes"] == 0 else f"  {res['conceptos_pendientes']} sin precio"
        print(f"   {nube.upper():6s} {res['total_usd']:8.2f} USD/mes{aviso}")


if __name__ == "__main__":
    main()
