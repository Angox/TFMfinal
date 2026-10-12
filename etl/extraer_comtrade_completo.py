import os
import requests
import boto3
import json
import time
import pycountry

from config_aws import S3_BUCKET, AWS_REGION
from calculos import clasificar_por_codigo_hs
S3_KEY_PUERTOS = "fuentes_externas/fmi_ports/puertos.json"
S3_KEY_COMTRADE = "fuentes_externas/comtrade/perfiles.json"
API_KEY = os.getenv("COMTRADE_API_KEY")

MAPEO_SECTORES = {
    "automocion_transporte": ["87", "86", "88", "89"],
    "tecnologia_maquinaria": ["84", "85"],
    "quimica_pharma": ["30", "28", "29", "31", "38"],
    "agroalimentario": [str(i).zfill(2) for i in range(1, 25)],
    "textil_moda": [str(i).zfill(2) for i in range(50, 64)],
    "materiales_construccion": ["25", "44", "68", "72", "73", "74", "76"],
    "energia_combustibles": ["27"],
}

s3_client = boto3.client('s3', region_name=AWS_REGION)

def cargar_cache_existente():
    try:
        obj = s3_client.get_object(Bucket=S3_BUCKET, Key=S3_KEY_COMTRADE)
        print("Caché detectada en S3. Cargando datos previos...")
        return json.loads(obj['Body'].read().decode('utf-8'))
    except Exception:
        print("No hay caché previa en S3 (o hubo un error). Se extraerá todo desde cero.")
        return {}

def extraer_paises_unicos_de_s3():
    try:
        obj = s3_client.get_object(Bucket=S3_BUCKET, Key=S3_KEY_PUERTOS)
        contenido = obj['Body'].read().decode('utf-8')
        puertos = [json.loads(linea) for linea in contenido.strip().split('\n') if linea.strip()]

        paises_iso3 = set()
        for p in puertos:
            pais_nombre = p.get('country')
            if pais_nombre:
                try: paises_iso3.add(pycountry.countries.search_fuzzy(pais_nombre)[0].alpha_3)
                except LookupError: pass
        return list(paises_iso3)
    except Exception as e:
        print(f"Error leyendo puertos del FMI: {e}")
        return []

def _cantidad(item):
    for campo in ("netWgt", "netWeight", "qty"):
        try:
            peso = float(item.get(campo) or 0)
        except (TypeError, ValueError):
            continue
        if peso > 0:
            return peso
    try:
        return float(item.get('primaryValue', 0) or 0)
    except (TypeError, ValueError):
        return 0.0


def consultar_comtrade_bulk(iso3_lista):
    if not API_KEY: raise ValueError("COMTRADE_API_KEY no encontrada")

    codigos_numericos = []
    mapa_inverso = {}

    for iso3 in iso3_lista:
        pais_obj = pycountry.countries.get(alpha_3=iso3)
        if pais_obj:
            codigos_numericos.append(pais_obj.numeric)
            mapa_inverso[int(pais_obj.numeric)] = iso3

    if not codigos_numericos: return {}

    resultados_bulk = {}
    paises_fallidos = []
    batch_size = 20

    for i in range(0, len(codigos_numericos), batch_size):
        lote = codigos_numericos[i:i+batch_size]
        reporters_str = ",".join(lote)

        url = f"https://comtradeapi.un.org/data/v1/get/C/A/HS?reporterCode={reporters_str}&partnerCode=0&flowCode=M,X&cmdCode=AG2&period=2024"
        headers = {"Ocp-Apim-Subscription-Key": API_KEY}

        print(f"   Consultando Lote {i//batch_size + 1}/{(len(codigos_numericos)//batch_size)+1} ({len(lote)} países)...")

        try:
            resp = None
            for intento in range(1, 4):
                resp = requests.get(url, headers=headers, timeout=30)
                if resp.status_code < 400:
                    break
                if resp.status_code == 429 or resp.status_code >= 500:
                    espera = 10 * intento
                    print(f"   HTTP {resp.status_code} (intento {intento}/3). Esperando {espera}s...")
                    time.sleep(espera)
                    continue
                break

            resp.raise_for_status()
            data = resp.json().get('data', [])

            data_por_pais = {}
            for item in data:
                rep_code = int(item.get('reporterCode'))
                if rep_code not in data_por_pais: data_por_pais[rep_code] = []
                data_por_pais[rep_code].append(item)

            for rep_code, items in data_por_pais.items():
                iso3 = mapa_inverso.get(rep_code)
                if not iso3: continue

                importes_por_sector = {k: 0.0 for k in list(MAPEO_SECTORES.keys()) + ["generico_logistica"]}
                total_comercio = 0.0

                for item in items:
                    cmd_code = item.get('cmdCode')
                    valor = _cantidad(item)
                    if valor <= 0:
                        continue

                    total_comercio += valor
                    sector_asignado = clasificar_por_codigo_hs(cmd_code, MAPEO_SECTORES)
                    importes_por_sector[sector_asignado] += valor

                if total_comercio > 0:
                    resultados_bulk[iso3] = {k: v / total_comercio for k, v in importes_por_sector.items() if v > 0}
                else:
                    resultados_bulk[iso3] = {"generico_logistica": 1.0}

        except Exception as e:
            print(f"   Fallo en el lote: {e}. Se reintentará en la próxima ejecución.")
            for num in lote:
                iso3 = mapa_inverso.get(int(num))
                if iso3: paises_fallidos.append(iso3)

        time.sleep(2)

    if paises_fallidos:
        print(f"{len(paises_fallidos)} países sin perfil por fallos de la API: "
              f"{', '.join(sorted(paises_fallidos))}")

    return resultados_bulk

def generar_diccionario_global():
    print("Iniciando Motor de Extracción Comtrade Optimizado...")

    perfiles_globales = cargar_cache_existente()
    paises_totales = extraer_paises_unicos_de_s3()

    paises_faltantes = [iso for iso in paises_totales if iso not in perfiles_globales]

    print(f"Países totales detectados: {len(paises_totales)}")
    print(f"Países ya en caché: {len(paises_totales) - len(paises_faltantes)}")
    print(f"Países a descargar ahora: {len(paises_faltantes)}")

    if paises_faltantes:
        nuevos_perfiles = consultar_comtrade_bulk(paises_faltantes)
        perfiles_globales.update(nuevos_perfiles)

        print(f"Actualizando y Subiendo matriz a s3://{S3_BUCKET}/{S3_KEY_COMTRADE}")
        s3_client.put_object(
            Bucket=S3_BUCKET, Key=S3_KEY_COMTRADE,
            Body=json.dumps(perfiles_globales), ContentType='application/json'
        )
        print("¡Matriz económica de UN Comtrade subida con éxito!")
    else:
        print("No hay países nuevos. Saltando extracción de API. ¡Coste Cero!")

if __name__ == "__main__":
    generar_diccionario_global()
