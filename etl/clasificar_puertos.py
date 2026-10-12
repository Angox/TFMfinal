import json
import os
from random import Random

import boto3

from muestreo import (anadir_puertos_fijos, muestra_repartida_por_paises,
                      reparto_proporcional)

from config_aws import S3_BUCKET, AWS_REGION
S3_KEY_PUERTOS = "fuentes_externas/fmi_ports/puertos.json"

TAMANO_MUESTRA = int(os.getenv("N_PUERTOS_MUESTRA", "0"))
SEMILLA_MUESTREO = int(os.getenv("SEMILLA_MUESTREO", "42"))

EXCLUIR_OFFSHORE = os.getenv("EXCLUIR_OFFSHORE", "1") not in ("0", "false", "False")

PUERTOS_FIJOS = {p.strip() for p in os.getenv("PUERTOS_FIJOS", "").replace(";", ",").split(",") if p.strip()}


def clasificar_tallas():
    print("Iniciando Right-Sizing Dinámico de puertos...")
    s3 = boto3.client('s3', region_name=AWS_REGION)

    obj = s3.get_object(Bucket=S3_BUCKET, Key=S3_KEY_PUERTOS)
    puertos = [json.loads(linea) for linea in obj['Body'].read().decode('utf-8').strip().split('\n') if linea.strip()]

    if not puertos:
        print("El archivo de puertos en S3 está vacío. Cancelando clasificación.")
        with open("tamaños.env", "w") as f:
            f.write("SIZE_L=0\nSIZE_M=0\nSIZE_S=0\n")
        return

    if EXCLUIR_OFFSHORE:
        antes = len(puertos)
        puertos = [p for p in puertos if not str(p.get("portid") or "").startswith("fso")]
        descartados = antes - len(puertos)
        if descartados:
            print(f"{descartados} terminales offshore (fso*) excluidas: "
                  f"sin red viaria ni hinterland que analizar.")

    talla_s, talla_m, talla_l = [], [], []

    for p in puertos:
        vessel_count = sum([
            float(p.get('vessel_count_container') or 0),
            float(p.get('vessel_count_dry_bulk') or 0),
            float(p.get('vessel_count_general_cargo') or 0),
            float(p.get('vessel_count_RoRo') or 0),
            float(p.get('vessel_count_tanker') or 0),
        ])

        if vessel_count > 3000:
            talla_l.append(p)
        elif vessel_count > 800:
            talla_m.append(p)
        else:
            talla_s.append(p)

    poblacion = {"S": len(talla_s), "M": len(talla_m), "L": len(talla_l)}
    catalogo = {"S": talla_s, "M": talla_m, "L": talla_l}
    seleccion = dict(catalogo)

    if TAMANO_MUESTRA > 0:
        rng = Random(SEMILLA_MUESTREO)
        cuota = reparto_proporcional(poblacion, TAMANO_MUESTRA)
        for talla in ("S", "M", "L"):
            seleccion[talla] = muestra_repartida_por_paises(catalogo[talla], cuota[talla], rng)
        print(f"Muestreo estratificado (n={TAMANO_MUESTRA}, semilla={SEMILLA_MUESTREO}):")
        for talla in ("S", "M", "L"):
            n_pob = poblacion[talla]
            elegidos = seleccion[talla]
            pct = (len(elegidos) / n_pob * 100.0) if n_pob else 0.0
            paises = len({str(p.get('country', '?')) for p in elegidos})
            print(f"   Talla {talla}: {len(elegidos)}/{n_pob} puertos "
                  f"({pct:.1f}% del estrato, {paises} países)")
    else:
        print(f"Procesando el catálogo completo: {sum(poblacion.values())} puertos.")

    if PUERTOS_FIJOS:
        forzados = set()
        for talla in ("S", "M", "L"):
            seleccion[talla], anadidos = anadir_puertos_fijos(
                seleccion[talla], catalogo[talla], PUERTOS_FIJOS)
            forzados |= anadidos
            for p in seleccion[talla]:
                if str(p.get("portid") or "") in PUERTOS_FIJOS:
                    marca = "añadido" if str(p.get("portid")) in anadidos else "ya sorteado"
                    print(f"   {p.get('portname')} ({p.get('country')}) "
                          f"→ talla {talla} [{marca}]")
        encontrados = {str(p.get('portid') or '')
                       for talla in ("S", "M", "L") for p in seleccion[talla]} & PUERTOS_FIJOS
        print(f"Casos de estudio: {len(encontrados)}/{len(PUERTOS_FIJOS)} localizados, "
              f"{len(forzados)} añadidos al sorteo.")
        ausentes = PUERTOS_FIJOS - encontrados
        if ausentes:
            print(f"portid inexistentes en el catálogo (¿errata?): {', '.join(sorted(ausentes))}")

    talla_s, talla_m, talla_l = seleccion["S"], seleccion["M"], seleccion["L"]

    s3.put_object(Bucket=S3_BUCKET, Key="fuentes_externas/fmi_ports/puertos_L.json", Body=json.dumps(talla_l))
    s3.put_object(Bucket=S3_BUCKET, Key="fuentes_externas/fmi_ports/puertos_M.json", Body=json.dumps(talla_m))
    s3.put_object(Bucket=S3_BUCKET, Key="fuentes_externas/fmi_ports/puertos_S.json", Body=json.dumps(talla_s))

    with open("tamaños.env", "w") as f:
        f.write(f"SIZE_L={len(talla_l)}\n")
        f.write(f"SIZE_M={len(talla_m)}\n")
        f.write(f"SIZE_S={len(talla_s)}\n")

    print(f"Clasificación FinOps completada: {len(talla_s)} Small, {len(talla_m)} Medium, {len(talla_l)} Large.")

if __name__ == "__main__":
    clasificar_tallas()
