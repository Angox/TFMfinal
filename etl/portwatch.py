import json
import urllib.parse
import urllib.request

BASE = ("https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"
        "/Daily_Ports_Data/FeatureServer/0/query")
CABECERAS = {"User-Agent": "TFM-Hinterland/1.0"}

SEGMENTOS_MOVIBLES = ("container", "roro", "general_cargo")
SEGMENTOS_DIRECTOS = ("dry_bulk", "tanker")

CAMPOS = ["date", "year"]
for _s in SEGMENTOS_MOVIBLES + SEGMENTOS_DIRECTOS:
    CAMPOS += [f"import_{_s}", f"export_{_s}"]

PAGINA = 1000


def _consultar(params, timeout=90):
    url = BASE + "?" + urllib.parse.urlencode(params)
    peticion = urllib.request.Request(url, headers=CABECERAS)
    with urllib.request.urlopen(peticion, timeout=timeout) as respuesta:
        return json.loads(respuesta.read().decode("utf-8"))


def descargar_serie_diaria(portid, desde_anio=None, limite_paginas=10):
    where = f"portid='{portid}'"
    if desde_anio:
        where += f" AND year >= {desde_anio}"

    filas, desplazamiento = [], 0
    for _ in range(limite_paginas):
        datos = _consultar({
            "where": where,
            "outFields": ",".join(CAMPOS),
            "f": "json",
            "resultRecordCount": PAGINA,
            "resultOffset": desplazamiento,
            "orderByFields": "date ASC",
        })
        lote = [f["attributes"] for f in datos.get("features", [])]
        filas.extend(lote)
        if not lote or not datos.get("exceededTransferLimit"):
            break
        desplazamiento += len(lote)
    return filas


def _suma(fila, segmentos):
    total = 0.0
    for segmento in segmentos:
        for sentido in ("import", "export"):
            valor = fila.get(f"{sentido}_{segmento}")
            if isinstance(valor, (int, float)):
                total += valor
    return total


def percentil(valores, q):
    if not valores:
        return None
    q = min(max(float(q), 0.0), 1.0)
    ordenados = sorted(valores)
    k = (len(ordenados) - 1) * q
    bajo = int(k)
    alto = min(bajo + 1, len(ordenados) - 1)
    if bajo == alto:
        return ordenados[bajo]
    return ordenados[bajo] + (ordenados[alto] - ordenados[bajo]) * (k - bajo)


def resumir_serie(filas, dias_ventana=365, percentil_capacidad=0.95,
                  min_dias_base=180):
    if not filas:
        return None

    if dias_ventana:
        dias_ventana = max(int(dias_ventana), 1)
    if min_dias_base:
        min_dias_base = max(int(min_dias_base), 0)

    movibles = [_suma(f, SEGMENTOS_MOVIBLES) for f in filas]
    directos = [_suma(f, SEGMENTOS_DIRECTOS) for f in filas]

    activos = [v for v in movibles if v > 0]
    if not activos:
        return None

    if dias_ventana and len(movibles) > dias_ventana:
        corte = len(movibles) - dias_ventana
    else:
        corte = 0

    base_activos = [v for v in movibles[:corte] if v > 0]
    ventana_activos = [v for v in movibles[corte:] if v > 0]
    if not ventana_activos:
        ventana_activos = activos

    autoreferente = len(base_activos) < min_dias_base
    referencia = activos if autoreferente else base_activos

    capacidad = percentil(referencia, percentil_capacidad)
    p95_ventana = percentil(ventana_activos, 0.95)

    excedidos = sum(1 for v in ventana_activos if v > capacidad)
    frecuencia = excedidos / len(ventana_activos)

    def media_activa(serie):
        recorte = serie[-dias_ventana:] if dias_ventana else serie
        con_actividad = [v for v in recorte if v > 0]
        if not con_actividad:
            con_actividad = [v for v in serie if v > 0]
        return round(sum(con_actividad) / len(con_actividad), 1) if con_actividad else 0.0

    return {
        "n_dias": len(filas),
        "n_dias_activos": len(activos),
        "n_dias_base": len(base_activos),
        "n_dias_ventana": len(ventana_activos),
        "carga_movible": media_activa(movibles),
        "carga_directa": media_activa(directos),
        "capacidad_movible": round(capacidad, 1),
        "capacidad_autoreferente": autoreferente,
        "frecuencia_excedencia": round(frecuencia, 4),
        "dias_excedidos": excedidos,
        "ratio_p95": round(p95_ventana / capacidad, 4) if capacidad else None,
        "mediana_movible": round(percentil(activos, 0.5), 1),
        "maximo_movible": round(max(activos), 1),
        "primer_dia": filas[0].get("date"),
        "ultimo_dia": filas[-1].get("date"),
        "unidad": "toneladas/dia",
        "fuente": "FMI PortWatch Daily_Ports_Data",
    }


def obtener_perfil_volumen(portid, dias_ventana=365, percentil_capacidad=0.95,
                           min_dias_base=180):
    try:
        filas = descargar_serie_diaria(portid)
    except Exception as e:
        print(f"No se pudo consultar PortWatch para {portid}: {e}", flush=True)
        return None
    return resumir_serie(filas, dias_ventana, percentil_capacidad, min_dias_base)
