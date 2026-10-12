import os
import asyncio
from fastapi import FastAPI, HTTPException, Header, WebSocket, WebSocketDisconnect
from fastapi.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.gzip import GZipMiddleware
from starlette.websockets import WebSocketState
import boto3
import json
import firebase_admin
from firebase_admin import auth
import google.generativeai as genai
from pydantic import BaseModel, Field
from shapely.geometry import LineString
import networkx as nx
import gc
import copy
import math
import threading
import requests
import time
import traceback
from collections import defaultdict, deque

from config_aws import S3_BUCKET, AWS_REGION
from grafos import (arbol_de_caminos, reconstruir_camino,
                    coste_servicio_hinterland, coste_medio_servicio)
from calculos import (proyectar_local, indice_compuesto,
                      saturacion_con_shock, estres_con_aislamiento,
                      vulnerabilidad_normalizada, percentil_trafico,
                      intensidad_visual)
from reconstruccion import (construir_grafo_desde_geojson, podar_componente_principal,
                            TIPO_FERROVIARIO)
import copiloto

firebase_admin.initialize_app()

app = FastAPI()

app.add_middleware(GZipMiddleware, minimum_size=1024)

PREFIX_API = "resultados_web/api/"
PREFIX_INDUSTRIA = "resultados_web/nodos_industriales/"

MAPEO_SECTORES_SIMULADOR = {
    "automocion_transporte": ["car_factory", "automotive_repair", "automotive_parts", "vehicle", "car_dealer", "car_rental", "gas_station", "truck_stop"],
    "tecnologia_maquinaria": ["electronics", "technology", "semiconductor", "computer", "telecommunications", "machinery", "appliance", "electronics_store"],
    "quimica_pharma": ["pharmaceutical", "chemical_plant", "laboratory", "medical_supply", "cosmetics", "refinery", "pharmacy", "hospital"],
    "agroalimentario": ["food_processing", "agricultural_facility", "farm", "brewery", "winery", "distillery", "bakery", "cold_storage", "supermarket", "grocery_store", "restaurant"],
    "textil_moda": ["clothing_store", "textile_mill", "apparel_manufacturing", "shoes", "boutique", "department_store"],
    "materiales_construccion": ["hardware_store", "construction", "building_materials", "lumber_yard", "mining", "metal_fabrication", "contractor"],
    "energia_combustibles": ["power_plant", "oil_and_gas", "energy", "fuel_supplier"],
    "generico_logistica": ["logistics", "warehouse", "distribution_center", "industrial_park", "industrial", "manufacturing", "factory", "port", "freight", "commercial", "retail", "shop", "supermarket", "market", "hardware_store"]
}

s3_client = boto3.client('s3', region_name=AWS_REGION)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse("static/index.html")


@app.get("/api/config")
async def get_config():
    return {
        "url_pmtiles": (
            f"pmtiles://https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com"
            "/resultados_web/mapa_global/global_hinterland.pmtiles?v=3"
        )
    }

VENTANA_LATENCIAS = 1000
LATENCIAS = defaultdict(lambda: deque(maxlen=VENTANA_LATENCIAS))


def registrar_latencia(operacion: str, segundos: float):
    LATENCIAS[operacion].append(segundos)


def _percentil(ordenados, q):
    if not ordenados:
        return None
    k = (len(ordenados) - 1) * q
    inferior = int(k)
    superior = min(inferior + 1, len(ordenados) - 1)
    if inferior == superior:
        return ordenados[inferior]
    return ordenados[inferior] + (ordenados[superior] - ordenados[inferior]) * (k - inferior)


def resumen_latencias():
    resumen = {}
    for operacion, muestras in LATENCIAS.items():
        if not muestras:
            continue
        ordenados = sorted(muestras)
        resumen[operacion] = {
            "n": len(ordenados),
            "p50_ms": round(_percentil(ordenados, 0.50) * 1000, 1),
            "p95_ms": round(_percentil(ordenados, 0.95) * 1000, 1),
            "p99_ms": round(_percentil(ordenados, 0.99) * 1000, 1),
            "max_ms": round(ordenados[-1] * 1000, 1),
        }
    return resumen


@app.get("/api/metricas")
async def get_metricas():
    return {
        "ventana_muestras": VENTANA_LATENCIAS,
        "latencias": resumen_latencias(),
    }


@app.get("/api/mapa-basico")
async def get_mapa_basico():
    try:
        print("Fusionando mapa básico desde archivos fragmentados...")
        mapa_unificado = []

        paginador = s3_client.get_paginator('list_objects_v2')
        paginas = paginador.paginate(Bucket=S3_BUCKET, Prefix=PREFIX_API + "basicos/basico_")

        for pagina in paginas:
            for item in pagina.get('Contents', []):
                try:
                    obj = s3_client.get_object(Bucket=S3_BUCKET, Key=item['Key'])
                    datos_puerto = json.loads(obj['Body'].read().decode('utf-8'))
                    mapa_unificado.append(datos_puerto)
                except Exception as e:
                    print(f"Error leyendo fragmento {item['Key']}: {e}")
                    continue

        return mapa_unificado

    except Exception as e:
        print(f"Error crítico leyendo mapa_basico de S3: {e}")
        return []

@app.get("/api/detalle-avanzado/{puerto_id}")
async def get_detalle_avanzado(puerto_id: str, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token ausente o mal formado")

    token = authorization.split(" ")[1]

    try:
        decoded_token = await run_in_threadpool(auth.verify_id_token, token)
        user_email = decoded_token.get('email', 'Usuario anónimo')
        print(f"Acceso concedido a: {user_email} para el puerto {puerto_id}")
    except Exception as e:
        print(f"Intento de acceso denegado (Token inválido): {e}")
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    try:
        obj = s3_client.get_object(Bucket=S3_BUCKET, Key=f"{PREFIX_API}detalles/{puerto_id}.json")
        return json.loads(obj['Body'].read().decode('utf-8'))
    except s3_client.exceptions.NoSuchKey:
        raise HTTPException(status_code=404, detail="Datos avanzados no encontrados para este puerto")
    except Exception as e:
        raise HTTPException(status_code=500, detail="Error interno obteniendo los datos logísticos")

def _distancia2_proyectada(nodo, objetivo, lon_ref, lat_ref):
    x, y = proyectar_local(nodo[0], nodo[1], lon_ref, lat_ref)
    return (x - objetivo[0]) ** 2 + (y - objetivo[1]) ** 2


LADO_CELDA = 0.01
KM_POR_GRADO_LAT = proyectar_local(0.0, 1.0, 0.0, 0.0)[1]
RADIO_CERCANO = 8


def construir_rejilla(nodos, lon_ref, lat_ref):
    celdas = {}
    for n in nodos:
        clave = (int(math.floor(n[0] / LADO_CELDA)), int(math.floor(n[1] / LADO_CELDA)))
        celdas.setdefault(clave, []).append(n)

    cajas = []
    for (i, j) in celdas:
        x0, y0 = proyectar_local(i * LADO_CELDA, j * LADO_CELDA, lon_ref, lat_ref)
        x1, y1 = proyectar_local((i + 1) * LADO_CELDA, (j + 1) * LADO_CELDA,
                                 lon_ref, lat_ref)
        cajas.append((x0, y0, x1, y1, (i, j)))

    return {"celdas": celdas, "cajas": cajas, "lon_ref": lon_ref, "lat_ref": lat_ref}


def _barrido_ordenado(rejilla, objetivo):
    lon_ref, lat_ref = rejilla["lon_ref"], rejilla["lat_ref"]
    ox, oy = objetivo
    candidatas = []
    for x0, y0, x1, y1, clave in rejilla["cajas"]:
        dx = x0 - ox if ox < x0 else (ox - x1 if ox > x1 else 0.0)
        dy = y0 - oy if oy < y0 else (oy - y1 if oy > y1 else 0.0)
        candidatas.append((dx * dx + dy * dy, clave))
    candidatas.sort(key=lambda c: c[0])

    celdas = rejilla["celdas"]
    mejor, mejor_d2 = None, float("inf")
    for cota, clave in candidatas:
        if cota >= mejor_d2:
            break
        for n in celdas[clave]:
            d2 = _distancia2_proyectada(n, objetivo, lon_ref, lat_ref)
            if d2 < mejor_d2:
                mejor, mejor_d2 = n, d2
    return mejor


def nodo_mas_cercano(rejilla, lon, lat):
    if not rejilla:
        return None
    celdas = rejilla["celdas"]
    if not celdas:
        return None
    lon_ref, lat_ref = rejilla["lon_ref"], rejilla["lat_ref"]
    objetivo = proyectar_local(lon, lat, lon_ref, lat_ref)

    cx = int(math.floor(lon / LADO_CELDA))
    cy = int(math.floor(lat / LADO_CELDA))

    mejor, mejor_d2 = None, float("inf")
    for radio in range(RADIO_CERCANO + 1):
        if radio == 0:
            vecinas = [(cx, cy)]
        else:
            vecinas = [(i, cy - radio) for i in range(cx - radio, cx + radio + 1)]
            vecinas += [(i, cy + radio) for i in range(cx - radio, cx + radio + 1)]
            vecinas += [(cx - radio, j) for j in range(cy - radio + 1, cy + radio)]
            vecinas += [(cx + radio, j) for j in range(cy - radio + 1, cy + radio)]
        for clave in vecinas:
            for n in celdas.get(clave, ()):
                d2 = _distancia2_proyectada(n, objetivo, lon_ref, lat_ref)
                if d2 < mejor_d2:
                    mejor, mejor_d2 = n, d2

        if mejor is not None:
            km_grado = KM_POR_GRADO_LAT * min(
                1.0, max(math.cos(math.radians(lat_ref)), 0.01))
            radio_seguro = int(math.ceil(
                (math.sqrt(mejor_d2) / km_grado) / LADO_CELDA)) + 1
            if radio >= radio_seguro:
                return mejor
            break

    return _barrido_ordenado(rejilla, objetivo)


MEMORIA_APP = {"puerto_id": None, "datos": None}

CERROJO_MOTOR = threading.RLock()


class CalculoAbandonado(Exception):
    pass


def _sigue_haciendo_falta(sigue_interesando):
    if sigue_interesando is not None and not sigue_interesando():
        raise CalculoAbandonado(
            "el cliente que pidió este cálculo ya no está conectado")


def obtener_datos_puerto_memoria(puerto_id: str):
    global MEMORIA_APP

    if MEMORIA_APP["puerto_id"] == puerto_id and MEMORIA_APP["datos"] is not None:
        return MEMORIA_APP["datos"]

    with CERROJO_MOTOR:
        return _cargar_puerto_en_memoria(puerto_id)


def _cargar_puerto_en_memoria(puerto_id: str):
    global MEMORIA_APP

    if MEMORIA_APP["puerto_id"] == puerto_id and MEMORIA_APP["datos"] is not None:
        return MEMORIA_APP["datos"]

    MEMORIA_APP["datos"] = None
    MEMORIA_APP["puerto_id"] = None
    COSTE_INTACTO.clear()
    REPARTO_INTACTO.clear()
    gc.collect()

    t_carga = time.perf_counter()
    print(f"[{puerto_id}] Descargando y construyendo Grafo base en RAM...")

    obj_rutas = s3_client.get_object(Bucket=S3_BUCKET, Key=f"{PREFIX_API}rutas/{puerto_id}.json")
    rutas_puerto = json.loads(obj_rutas['Body'].read().decode('utf-8'))

    obj_detalles = s3_client.get_object(Bucket=S3_BUCKET, Key=f"{PREFIX_API}detalles/{puerto_id}.json")
    detalle_puerto = json.loads(obj_detalles['Body'].read().decode('utf-8'))

    obj_ind = s3_client.get_object(Bucket=S3_BUCKET, Key=f"{PREFIX_INDUSTRIA}{puerto_id}.json")
    industrias_puerto = json.loads(obj_ind['Body'].read().decode('utf-8'))

    obj_mapa = s3_client.get_object(Bucket=S3_BUCKET, Key=f"{PREFIX_API}basicos/basico_{puerto_id}.json")
    puerto_base = json.loads(obj_mapa['Body'].read().decode('utf-8'))

    G_base, geometrias_vias, nodos_coords = construir_grafo_desde_geojson(
        rutas_puerto.get("features", []))
    G_base, nodos_coords = podar_componente_principal(G_base)

    nodos_lista = list(nodos_coords)
    industrias_mapeadas = []
    rejilla = None
    if nodos_lista:
        lat_ref = float(puerto_base.get('lat', 0) or 0)
        lon_ref = float(puerto_base.get('lng', 0) or 0)
        rejilla = construir_rejilla(nodos_lista, lon_ref, lat_ref)

        for ind in industrias_puerto.get("features", []):
            coords = ind["geometry"]["coordinates"]
            industrias_mapeadas.append(
                nodo_mas_cercano(rejilla, coords[0], coords[1]))

    p_lat = float(puerto_base.get('lat', 0))
    p_lon = float(puerto_base.get('lng', 0))
    puerto_node = None
    if nodos_lista:
        puerto_node = nodo_mas_cercano(rejilla, p_lon, p_lat)

    MEMORIA_APP["datos"] = (rutas_puerto, detalle_puerto, industrias_puerto, puerto_base, G_base, industrias_mapeadas, puerto_node, geometrias_vias)
    MEMORIA_APP["puerto_id"] = puerto_id

    duracion = time.perf_counter() - t_carga
    registrar_latencia("carga_puerto", duracion)
    print(f"⏱️ [{puerto_id}] Grafo listo en {duracion:.2f} s "
          f"({len(G_base.nodes)} nodos, {len(G_base.edges)} aristas)", flush=True)

    return MEMORIA_APP["datos"]

def responder_json_de_s3(clave, vacio_por_defecto):
    try:
        obj = s3_client.get_object(Bucket=S3_BUCKET, Key=clave)
    except s3_client.exceptions.NoSuchKey:
        return vacio_por_defecto
    return StreamingResponse(
        obj["Body"].iter_chunks(chunk_size=256 * 1024),
        media_type="application/json",
    )


@app.get("/api/rutas-mapa/{puerto_id}")
async def get_rutas_mapa(puerto_id: str, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token ausente o mal formado")

    token = authorization.split(" ")[1]
    try:
        decoded_token = await run_in_threadpool(auth.verify_id_token, token)
        user_email = decoded_token.get('email', 'Usuario anónimo')
        print(f"Acceso a rutas concedido a: {user_email} para el puerto {puerto_id}")
    except Exception as e:
        print(f"Intento de acceso a rutas denegado (Token inválido): {e}")
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    try:
        return responder_json_de_s3(f"{PREFIX_API}rutas/{puerto_id}.json",
                                    {"type": "FeatureCollection", "features": []})
    except Exception as e:
        print(f"Error obteniendo rutas de {puerto_id}: {e}", flush=True)
        raise HTTPException(status_code=500, detail="Error interno obteniendo las rutas logísticas")

@app.get("/api/industrias-mapa/{puerto_id}")
async def get_industrias_mapa(puerto_id: str, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token ausente o mal formado")

    token = authorization.split(" ")[1]
    try:
        await run_in_threadpool(auth.verify_id_token, token)
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")

    try:
        return responder_json_de_s3(f"{PREFIX_INDUSTRIA}{puerto_id}.json",
                                    {"type": "FeatureCollection", "features": []})
    except Exception as e:
        print(f"Error obteniendo industrias de {puerto_id}: {e}", flush=True)
        raise HTTPException(status_code=500, detail="Error interno obteniendo las industrias")

class ChatRequest(BaseModel):
    mensaje: str = Field(min_length=1, max_length=copiloto.MAX_LONGITUD_PREGUNTA)


MODELO_GEMINI = "gemini-2.5-flash-lite"

api_key_gemini = os.getenv("GEMINI_API_KEY")

if not api_key_gemini:
    print("ADVERTENCIA: La variable GEMINI_API_KEY no está configurada")
else:
    genai.configure(api_key=api_key_gemini)

CONFIGURACION_GENERACION = {
    "temperature": 0.2,
    "top_p": 0.9,
    "candidate_count": 1,
    "max_output_tokens": 400,
}

modelo_ia = genai.GenerativeModel(
    MODELO_GEMINI,
    system_instruction=copiloto.INSTRUCCION_SISTEMA,
    generation_config=CONFIGURACION_GENERACION,
)


async def responder_copiloto(puerto_id, datos_puerto, escenario, pregunta,
                             historial=None):
    pregunta = copiloto.sanear_pregunta(pregunta)
    turno = copiloto.construir_turno(puerto_id, datos_puerto, escenario, pregunta)

    conversacion = copiloto.recortar_historial(historial)
    contenidos = conversacion + [{"role": "user", "parts": [turno]}]

    respuesta = await modelo_ia.generate_content_async(contenidos)

    try:
        texto = (respuesta.text or "").strip()
    except Exception as e:
        motivo = getattr(getattr(respuesta, "prompt_feedback", None), "block_reason", None)
        print(f"[{puerto_id}] el modelo no devolvió texto "
              f"(motivo={motivo or 'desconocido'}): {e}", flush=True)
        raise RuntimeError("El modelo no ha devuelto una respuesta utilizable.")

    if not texto:
        raise RuntimeError("El modelo ha devuelto una respuesta vacía.")

    uso = getattr(respuesta, "usage_metadata", None)
    if uso is not None:
        print(f"[{puerto_id}] copiloto: "
              f"{getattr(uso, 'prompt_token_count', '?')} tokens de entrada, "
              f"{getattr(uso, 'candidates_token_count', '?')} de salida", flush=True)

    nuevo_historial = conversacion + [
        {"role": "user", "parts": [copiloto.envolver_pregunta(pregunta)]},
        {"role": "model", "parts": [texto]},
    ]
    return texto, copiloto.recortar_historial(nuevo_historial)

LIMITE_SHOCK = 10.0

PESO_SATURACION = 5.0
PESO_CUELLO_BOTELLA = 5.0

CAPACIDAD_FALLBACK_POR_PUERTA = 8000.0

PENALIZACION_CLIMA = {
    "nieve": (2.0, 3.5),
    "lluvia_torrencial": (1.3, 1.8),
}
PENALIZACION_CLIMA_VIAS_PRINCIPALES = frozenset((
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
))


def estres_con_shock(detalle_puerto: dict, multiplicador: float) -> float:
    saturacion = detalle_puerto.get("saturacion")
    vulnerabilidad = detalle_puerto.get("vulnerabilidad")

    if saturacion is None:
        capacidad = float(detalle_puerto.get("capacidad_diaria") or 0.0)
        volumen = float(detalle_puerto.get("volumen_diario_movible")
                        or detalle_puerto.get("volumen_teus") or 0.0)
        if capacidad > 0 and volumen > 0:
            saturacion = min(volumen / capacidad, 1.0)
        else:
            base = float(detalle_puerto.get("indice_estres") or 0.0)
            return min(max(base * multiplicador, 0.0), 10.0)

    if vulnerabilidad is None:
        base = float(detalle_puerto.get("indice_estres") or 0.0)
        vulnerabilidad = max((base - float(saturacion) * PESO_SATURACION)
                             / PESO_CUELLO_BOTELLA, 0.0)

    return indice_compuesto(saturacion_con_shock(saturacion, multiplicador),
                            vulnerabilidad, PESO_SATURACION, PESO_CUELLO_BOTELLA)


def sanear_shock(valor, por_defecto: float = 1.0) -> float:
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return por_defecto
    if not (0.0 < v <= LIMITE_SHOCK):
        return por_defecto
    return v


def sanear_lineas_corte(valor) -> list:
    if not isinstance(valor, (list, tuple)):
        return []

    lineas = []
    for linea in valor:
        if not isinstance(linea, (list, tuple)) or len(linea) < 2:
            continue
        puntos = []
        for punto in linea:
            if not isinstance(punto, (list, tuple)) or len(punto) < 2:
                continue
            try:
                puntos.append([float(punto[0]), float(punto[1])])
            except (TypeError, ValueError):
                continue
        if len(puntos) >= 2:
            lineas.append(puntos)
    return lineas


class SimularRequest(BaseModel):
    shock_multiplier: float = Field(gt=0, le=LIMITE_SHOCK)

@app.post("/api/simular/{puerto_id}")
async def simular_escenario(puerto_id: str, request: SimularRequest, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token ausente o mal formado")
    try:
        await run_in_threadpool(auth.verify_id_token, authorization.split(" ")[1])
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    try:
        obj_rutas = s3_client.get_object(Bucket=S3_BUCKET, Key=f"{PREFIX_API}rutas/{puerto_id}.json")
        rutas_puerto = json.loads(obj_rutas['Body'].read().decode('utf-8'))

        obj_detalles = s3_client.get_object(Bucket=S3_BUCKET, Key=f"{PREFIX_API}detalles/{puerto_id}.json")
        detalle_puerto = json.loads(obj_detalles['Body'].read().decode('utf-8'))
    except s3_client.exceptions.NoSuchKey:
        raise HTTPException(status_code=404, detail="No hay datos base para simular este puerto")

    ranking_calles = {}
    for feature in rutas_puerto["features"]:
        trafico_base = feature["properties"].get("trafico", 0)
        nombre_via = feature["properties"].get("nombre_via", "Desconocida")
        if nombre_via != "Desconocida":
            ranking_calles.setdefault(nombre_via, []).append(trafico_base)

    top_calles_str = "Ninguna identificada"
    if ranking_calles:
        calles_max_trafico = {k: max(v) for k, v in ranking_calles.items()}
        calles_ordenadas = sorted(calles_max_trafico.items(), key=lambda x: x[1], reverse=True)[:3]
        top_calles_str = ", ".join([calle[0] for calle in calles_ordenadas])

    nuevo_estres = estres_con_shock(detalle_puerto, request.shock_multiplier)

    detalle_puerto["indice_estres"] = round(nuevo_estres, 2)
    detalle_puerto["volumen_teus"] = round(detalle_puerto.get("volumen_teus", 0) * request.shock_multiplier, 0)
    detalle_puerto["volumen_diario_movible"] = round(
        (detalle_puerto.get("volumen_diario_movible") or 0) * request.shock_multiplier, 0)
    detalle_puerto["riesgo_cuello_botella"] = "ALTO (COLAPSO)" if nuevo_estres > 7 else ("MODERADO" if nuevo_estres > 4 else "BAJO")
    detalle_puerto["top_calles_colapsadas"] = top_calles_str

    return {
        "detalle_simulado": detalle_puerto,
        "rutas_simuladas": rutas_puerto
    }

@app.post("/api/chat/{puerto_id}")
async def chat_asistente_logistico(puerto_id: str, request: ChatRequest, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token ausente o mal formado")

    try:
        await run_in_threadpool(auth.verify_id_token, authorization.split(" ")[1])
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    try:
        obj_detalles = s3_client.get_object(Bucket=S3_BUCKET, Key=f"{PREFIX_API}detalles/{puerto_id}.json")
        datos_puerto = json.loads(obj_detalles['Body'].read().decode('utf-8'))
    except s3_client.exceptions.NoSuchKey:
        raise HTTPException(status_code=404, detail="No hay datos para este puerto.")
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error S3: {e}")
        raise HTTPException(status_code=500, detail="Error recuperando datos de S3 para la IA.")

    try:
        respuesta, _ = await responder_copiloto(puerto_id, datos_puerto,
                                                escenario=None,
                                                pregunta=request.mensaje)
        return {"respuesta": respuesta}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        print(f"Error llamando a Gemini: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Fallo en Gemini: {str(e)}")

class CorteRequest(BaseModel):
    linea_corte: list[list[float]]

LAMBDA_VULNERABILIDAD = 3.0

COSTE_INTACTO = {}


def coste_medio_hinterland_intacto(puerto_id, clima, grafo_base, puerto_node,
                                   detalle_puerto, destinos_demanda):
    clave = (puerto_id, clima)
    if clave in COSTE_INTACTO:
        return COSTE_INTACTO[clave]

    origenes = [tuple(p) for p in (detalle_puerto.get("puertas_reales") or [])
                if tuple(p) in grafo_base.nodes]
    if not origenes and puerto_node is not None:
        origenes = [puerto_node]
    if not origenes:
        COSTE_INTACTO[clave] = None
        return None

    resumen = coste_servicio_hinterland(
        grafo_base, origenes, destinos_demanda, 'weight_dinamico')
    COSTE_INTACTO[clave] = coste_medio_servicio(resumen)
    return COSTE_INTACTO[clave]


def aplicar_clima(grafo, clima):
    principal, secundaria = PENALIZACION_CLIMA.get(clima, (1.0, 1.0))
    for u, v, data in grafo.edges(data=True):
        es_principal = data.get('tipo_via') in PENALIZACION_CLIMA_VIAS_PRINCIPALES
        data['weight_dinamico'] = data['weight'] * (principal if es_principal else secundaria)


REPARTO_INTACTO = {}

UMBRAL_DESVIO = 0.05


def trafico_por_via(grafo, origenes, destinos_demanda):
    trafico_aristas = {}
    por_via = {}
    if not origenes or not destinos_demanda:
        return trafico_aristas, por_via

    distancias, predecesores = arbol_de_caminos(grafo, origenes, 'weight_dinamico')
    for nodo, demanda in destinos_demanda:
        if nodo not in distancias:
            continue
        camino = reconstruir_camino(nodo, predecesores)
        for i in range(len(camino) - 1):
            arista = (camino[i], camino[i + 1])
            if grafo.has_edge(*arista):
                trafico_aristas[arista] = trafico_aristas.get(arista, 0.0) + demanda

    for (u, v), trafico in trafico_aristas.items():
        idx = grafo[u][v].get('feature_idx')
        if idx is not None and trafico > por_via.get(idx, 0.0):
            por_via[idx] = trafico
    return trafico_aristas, por_via


def _referencia(trafico_aristas, por_via, shock_multiplier):
    escala = shock_multiplier if shock_multiplier > 0 else 1.0
    return {"p95": percentil_trafico(trafico_aristas.values()) / escala,
            "por_via": {idx: t / escala for idx, t in por_via.items()}}


def reparto_intacto(puerto_id, clima, grafo_base, origenes, destinos_demanda,
                    shock_multiplier, propio=None):
    clave = (puerto_id, clima)
    if propio is not None:
        REPARTO_INTACTO[clave] = _referencia(propio[0], propio[1], shock_multiplier)
    elif clave not in REPARTO_INTACTO:
        trafico_aristas, por_via = trafico_por_via(grafo_base, origenes, destinos_demanda)
        REPARTO_INTACTO[clave] = _referencia(trafico_aristas, por_via, shock_multiplier)
    return REPARTO_INTACTO[clave]


def desvio_de_la_via(trafico_ahora, trafico_antes):
    if trafico_ahora <= 0:
        return None
    if trafico_antes <= 0:
        return float('inf')
    incremento = trafico_ahora / trafico_antes - 1.0
    return incremento if incremento >= UMBRAL_DESVIO else None


def diagnostico_del_corte(vias_eliminadas, aristas_eliminadas, sobrecoste,
                          fraccion_aislada, vias_desviadas=0):
    if not vias_eliminadas:
        return ("El trazo no cruzó ninguna vía. Dibuja la línea encima de una "
                "carretera, atravesándola de lado a lado.")

    cabecera = (f"{len(vias_eliminadas)} vías seccionadas "
                f"({aristas_eliminadas} tramos fuera de servicio)")

    desvio = (f" El desvío se reparte por {vias_desviadas} vías, dibujadas más "
              f"gruesas en el mapa." if vias_desviadas else "")

    if fraccion_aislada >= 0.999:
        return f"{cabecera}: el hinterland queda TOTALMENTE incomunicado."
    if fraccion_aislada > 0:
        return (f"{cabecera}: deja sin servicio al {fraccion_aislada:.1%} de la "
                f"demanda industrial.{desvio}")
    if sobrecoste >= 0.25:
        return f"{cabecera}: el desvío encarece el reparto un {sobrecoste:.0%}.{desvio}"
    if sobrecoste >= 0.02:
        return f"{cabecera}: el desvío encarece el reparto un {sobrecoste:.1%}.{desvio}"
    return (f"{cabecera}: la red absorbe el corte y el desvío solo encarece "
            f"el reparto un {sobrecoste:.2%}.{desvio}")


def calcular_impacto_dinamico(puerto_id: str, lineas_corte: list, clima: str,
                              cached_data: tuple, shock_multiplier: float = 1.0,
                              incluir_geojson: bool = True,
                              sigue_interesando=None):
    with CERROJO_MOTOR:
        _sigue_haciendo_falta(sigue_interesando)
        return _calcular_impacto_dinamico(
            puerto_id, lineas_corte, clima, cached_data, shock_multiplier,
            incluir_geojson, sigue_interesando)


def _calcular_impacto_dinamico(puerto_id, lineas_corte, clima, cached_data,
                               shock_multiplier, incluir_geojson, sigue_interesando):
    rutas_originales = cached_data[0]
    detalle_puerto = copy.deepcopy(cached_data[1])
    industrias_puerto = cached_data[2]
    G_base = cached_data[4]
    industrias_mapeadas = cached_data[5]
    puerto_node = cached_data[6]
    geometrias_vias = cached_data[7]


    vias_eliminadas = set()
    if lineas_corte:
        for linea_corte in lineas_corte:
            if linea_corte and len(linea_corte) > 1:
                linea_2d = [[pt[0], pt[1]] for pt in linea_corte]
                linea_limpia = []
                for p in linea_2d:
                    if not linea_limpia or linea_limpia[-1] != p: linea_limpia.append(p)

                if len(linea_limpia) >= 2:
                    linea_usuario = LineString(linea_limpia).simplify(0.0005)
                    if not linea_usuario.is_empty and linea_usuario.geom_type == 'LineString':
                        minx, miny, maxx, maxy = linea_usuario.bounds
                        for i, geom in enumerate(geometrias_vias):
                            if geom is None or geom.is_empty: continue
                            g_minx, g_miny, g_maxx, g_maxy = geom.bounds
                            if not (maxx < g_minx or minx > g_maxx or maxy < g_miny or miny > g_maxy):
                                if geom.intersects(linea_usuario):
                                    vias_eliminadas.add(i)

    def filter_edge(u, v):
        return G_base[u][v].get('feature_idx') not in vias_eliminadas

    _sigue_haciendo_falta(sigue_interesando)
    aplicar_clima(G_base, clima)

    G_cut = (nx.subgraph_view(G_base, filter_edge=filter_edge).copy()
             if vias_eliminadas else G_base)
    aristas_eliminadas = G_base.number_of_edges() - G_cut.number_of_edges()

    volumen_carga = float(detalle_puerto.get("volumen_diario_movible")
                          or detalle_puerto.get("volumen_teus", 1000) or 1000.0)
    if volumen_carga <= 0:
        volumen_carga = 1000.0

    volumen_base_sin_shock = volumen_carga
    volumen_carga = volumen_carga * shock_multiplier

    trafico_aristas = {}
    industrias_aisladas = 0
    max_cuello_botella = 0

    demanda_total = 0.0
    for _idx, _ind in enumerate(industrias_puerto.get("features", [])):
        if _idx >= len(industrias_mapeadas):
            continue
        demanda_total += max(float(_ind["properties"].get("demanda_teus", 0.0)), 0.0) * shock_multiplier
    demanda_aislada = 0.0
    coste_cortado = 0.0
    demanda_servida = 0.0
    destinos_demanda = []

    puertas_reales_coords = detalle_puerto.get("puertas_reales", [])

    origenes_dijkstra = [tuple(p) for p in puertas_reales_coords if tuple(p) in G_cut.nodes]
    if not origenes_dijkstra:
        origenes_dijkstra = [puerto_node]

    _sigue_haciendo_falta(sigue_interesando)
    if origenes_dijkstra and len(G_cut.nodes) > 0:
        try:
            longitudes_rutas, predecesores = arbol_de_caminos(
                G_cut, origenes_dijkstra, 'weight_dinamico')

            for idx, ind in enumerate(industrias_puerto.get("features", [])):
                if idx >= len(industrias_mapeadas): continue

                ind_node = industrias_mapeadas[idx]

                demanda_fija = float(ind["properties"].get("demanda_teus", 0.0)) * shock_multiplier

                if demanda_fija <= 0: continue

                destinos_demanda.append((ind_node, demanda_fija))

                if ind_node in longitudes_rutas:
                    coste_cortado += demanda_fija * longitudes_rutas[ind_node]
                    demanda_servida += demanda_fija
                    camino = reconstruir_camino(ind_node, predecesores)
                    for i in range(len(camino) - 1):
                        arista = (camino[i], camino[i + 1])
                        trafico_aristas[arista] = trafico_aristas.get(arista, 0.0) + demanda_fija
                else:
                    industrias_aisladas += 1
                    demanda_aislada += demanda_fija

        except Exception as e:
            print(f"Error en Dijkstra Dinámico: {e}")
            industrias_aisladas += len(industrias_puerto.get("features", []))
            demanda_aislada = demanda_total

    _sigue_haciendo_falta(sigue_interesando)
    sobrecoste_corte = 0.0
    coste_medio_cortado = (coste_cortado / demanda_servida) if demanda_servida > 0 else None
    if vias_eliminadas and coste_medio_cortado is not None and destinos_demanda:
        coste_medio_intacto = coste_medio_hinterland_intacto(
            puerto_id, clima, G_base, puerto_node, detalle_puerto, destinos_demanda)
        if coste_medio_intacto and coste_medio_intacto > 0:
            sobrecoste_corte = max(coste_medio_cortado / coste_medio_intacto - 1.0, 0.0)

    vulnerabilidad_corte = vulnerabilidad_normalizada(sobrecoste_corte, LAMBDA_VULNERABILIDAD)

    max_cuello_botella = max(trafico_aristas.values()) if trafico_aristas else 0

    cargas_por_feature = {}
    for (u_n, v_n), trafico in trafico_aristas.items():
        edge_data = G_cut.get_edge_data(u_n, v_n)
        if edge_data is not None:
            idx = edge_data.get("feature_idx")
            if idx is not None:
                cargas_por_feature.setdefault(idx, []).append(trafico)
    crudo_por_via = {idx: max(cargas) for idx, cargas in cargas_por_feature.items()}

    referencia = reparto_intacto(
        puerto_id, clima, G_base, origenes_dijkstra, destinos_demanda,
        shock_multiplier,
        propio=None if vias_eliminadas else (trafico_aristas, crudo_por_via))

    denominador_visual = referencia["p95"] * shock_multiplier
    if denominador_visual <= 0:
        denominador_visual = max_cuello_botella if max_cuello_botella > 0 else 1.0

    trafico_por_feature = {i: 0.0 for i in range(len(rutas_originales["features"]))}
    for idx, crudo in crudo_por_via.items():
        trafico_por_feature[idx] = intensidad_visual([crudo], denominador_visual)

    desvio_por_via = {}
    if vias_eliminadas:
        for idx, crudo in crudo_por_via.items():
            if idx in vias_eliminadas:
                continue
            antes = referencia["por_via"].get(idx, 0.0) * shock_multiplier
            desvio = desvio_de_la_via(crudo, antes)
            if desvio is not None:
                desvio_por_via[idx] = desvio

    vias_vivas_features = [] if incluir_geojson else None
    delta_rutas = {}

    for i, feature in enumerate(rutas_originales["features"]):
        propiedades = feature.get("properties", {}) or {}
        es_ferroviario = propiedades.get("tipo_via") == TIPO_FERROVIARIO

        delta_props = {}
        desvio_json = None
        hay_desvio = False
        trafico = 0.0
        esta_cortada = i in vias_eliminadas

        if esta_cortada:
            delta_props["cortada"] = True
            if not es_ferroviario:
                delta_props["trafico"] = 0.0
        elif not es_ferroviario:
            trafico = min(trafico_por_feature.get(i, 0.0), 100.0)
            desvio = desvio_por_via.get(i)
            hay_desvio = desvio is not None
            if hay_desvio:
                desvio_json = (None if desvio == float('inf')
                               else round(min(desvio, 99.0), 3))

            if trafico > 0 or hay_desvio:
                delta_props["trafico"] = round(trafico, 2)
                if hay_desvio:
                    delta_props["desvio"] = desvio_json

        if delta_props:
            delta_rutas[str(i)] = delta_props

        if not incluir_geojson:
            continue

        props = propiedades.copy()
        if not es_ferroviario:
            props["trafico"] = trafico
        if esta_cortada:
            props["cortada"] = True
        elif hay_desvio:
            props["desvio"] = desvio_json

        vias_vivas_features.append({
            "type": feature.get("type", "Feature"),
            "geometry": feature["geometry"],
            "properties": props
        })

    saturacion_base = detalle_puerto.get("saturacion")
    if saturacion_base is None:
        capacidad_base_red = float(detalle_puerto.get("capacidad_diaria") or 0.0)
        if capacidad_base_red <= 0:
            puertas_activas = len(origenes_dijkstra) if len(origenes_dijkstra) > 0 else 1
            capacidad_base_red = puertas_activas * CAPACIDAD_FALLBACK_POR_PUERTA
        saturacion_base = (min(volumen_base_sin_shock / capacidad_base_red, 1.0)
                           if capacidad_base_red > 0 else 0.0)

    saturacion = saturacion_con_shock(saturacion_base, shock_multiplier)
    vulnerabilidad_base = min(max(float(detalle_puerto.get("vulnerabilidad") or 0.0), 0.0), 1.0)
    vulnerabilidad = vulnerabilidad_base + vulnerabilidad_corte * (1.0 - vulnerabilidad_base)

    estres_final_red = indice_compuesto(saturacion, vulnerabilidad,
                                        PESO_SATURACION, PESO_CUELLO_BOTELLA)

    fraccion_aislada = (demanda_aislada / demanda_total) if demanda_total > 0 else 0.0
    fraccion_aislada = min(max(fraccion_aislada, 0.0), 1.0)
    nuevo_estres = estres_con_aislamiento(estres_final_red, fraccion_aislada)

    resultado = {
        "vias_afectadas": len(vias_eliminadas),
        "aristas_eliminadas": aristas_eliminadas,
        "vias_desviadas": len(desvio_por_via),
        "diagnostico": diagnostico_del_corte(
            vias_eliminadas, aristas_eliminadas, sobrecoste_corte, fraccion_aislada,
            len(desvio_por_via)),
        "industrias_aisladas": industrias_aisladas,
        "fraccion_demanda_aislada": round(fraccion_aislada, 4),
        "saturacion": round(saturacion, 4),
        "vulnerabilidad": round(vulnerabilidad, 4),
        "vulnerabilidad_base": round(vulnerabilidad_base, 4),
        "vulnerabilidad_corte": round(vulnerabilidad_corte, 4),
        "sobrecoste_corte": round(sobrecoste_corte, 4),
        "max_trafico_arista": round(max_cuello_botella, 2),
        "nuevo_estres": round(nuevo_estres, 2),
        "delta_rutas": delta_rutas
    }
    if incluir_geojson:
        resultado["rutas_simuladas"] = {"type": "FeatureCollection",
                                        "features": vias_vivas_features}
    return resultado

def obtener_clima_real(lat: float, lon: float) -> str:
    try:
        url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=weather_code"
        respuesta = requests.get(url, timeout=3)
        if respuesta.status_code == 200:
            datos = respuesta.json()
            codigo_wmo = datos.get("current", {}).get("weather_code", 0)

            if codigo_wmo in [71, 73, 75, 77, 85, 86]:
                return "nieve"
            elif codigo_wmo in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99]:
                return "lluvia_torrencial"
            else:
                return "despejado"
    except Exception as e:
        print(f"Error al obtener clima en vivo: {e}")

    return "despejado"

@app.post("/api/simular-corte/{puerto_id}")
async def simular_corte(puerto_id: str, request: CorteRequest, authorization: str = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token ausente")
    try:
        await run_in_threadpool(auth.verify_id_token, authorization.split(" ")[1])
    except Exception:
        raise HTTPException(status_code=401, detail="Token inválido")

    try:
        cached_data = await run_in_threadpool(obtener_datos_puerto_memoria, puerto_id)
        t_calculo = time.perf_counter()
        resultado = await run_in_threadpool(calcular_impacto_dinamico, puerto_id, [request.linea_corte], "despejado", cached_data)
        registrar_latencia("simulacion_rest", time.perf_counter() - t_calculo)
        return resultado
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Error en simulación: {str(e)}")


INTERVALO_LATIDO_WS = 15


async def calcular_con_latido(websocket: WebSocket, texto_fase: str, funcion, *args, **kwargs):
    tarea = asyncio.create_task(run_in_threadpool(funcion, *args, **kwargs))
    try:
        while True:
            try:
                return await asyncio.wait_for(asyncio.shield(tarea),
                                              timeout=INTERVALO_LATIDO_WS)
            except asyncio.TimeoutError:
                await websocket.send_json({"status": "processing", "fase": texto_fase})
    except BaseException:
        tarea.cancel()
        raise


@app.websocket("/api/ws/simular-corte/{puerto_id}")
async def websocket_simulador(websocket: WebSocket, puerto_id: str):
    await websocket.accept()
    autenticado = False
    session_lineas_corte = []
    session_clima = "auto"
    session_shock = 1.0
    clima_real_actual = "despejado"
    cached_data = None

    session_ultimo_resultado = None
    session_historial_chat = []

    sesion_viva = {"ok": True}
    def hace_falta_todavia():
        return sesion_viva["ok"]

    try:
        while True:
            datos_recibidos = await websocket.receive_json()
            tipo_evento = datos_recibidos.get("tipo_evento")

            if autenticado and tipo_evento == "ping":
                await websocket.send_json({"status": "pong"})
                continue

            if not autenticado:
                token = datos_recibidos.get("token")
                if not token:
                    await websocket.close()
                    return

                await run_in_threadpool(auth.verify_id_token, token)
                autenticado = True
                await websocket.send_json({"status": "auth_ok"})

                cached_data = await calcular_con_latido(
                    websocket, "Cargando la red viaria del puerto...",
                    obtener_datos_puerto_memoria, puerto_id)
                puerto_base = cached_data[3]
                lat, lon = float(puerto_base.get('lat', 0)), float(puerto_base.get('lng', 0))

                clima_real_actual = await run_in_threadpool(obtener_clima_real, lat, lon)
                await websocket.send_json({"status": "clima_detectado", "clima_real": clima_real_actual})
                session_clima = clima_real_actual

                if datos_recibidos.get("cortes_pendientes"):
                    print(f"[{puerto_id}] Reconexión con cortes pendientes: "
                          f"se omite el reparto base", flush=True)
                    continue

                fase_base = "Calculando el reparto base..."
                await websocket.send_json({"status": "processing", "fase": fase_base})
                try:
                    base_intacta = await calcular_con_latido(
                        websocket, fase_base,
                        calcular_impacto_dinamico, puerto_id, [], session_clima,
                        cached_data, session_shock, incluir_geojson=False,
                        sigue_interesando=hace_falta_todavia)
                    session_ultimo_resultado = base_intacta
                    await websocket.send_json({"status": "success", "data": base_intacta})
                except Exception as e:
                    print(f"No se pudo calcular el reparto base de {puerto_id}: {e}", flush=True)
                    traceback.print_exc()
                    await websocket.send_json({
                        "status": "aviso",
                        "message": ("No se pudo calcular el reparto base. El mapa "
                                    "muestra el coloreado del ETL, que usa otra escala.")})
                continue

            else:
                if tipo_evento == "corte":
                    nueva_linea = datos_recibidos.get("linea_corte", [])
                    if nueva_linea: session_lineas_corte.append(nueva_linea)
                elif tipo_evento == "clima":
                    seleccion_usuario = datos_recibidos.get("clima", "auto")
                    session_clima = clima_real_actual if seleccion_usuario == "auto" else seleccion_usuario
                elif tipo_evento == "shock":
                    session_shock = sanear_shock(datos_recibidos.get("shock_multiplier", 1.0))
                elif tipo_evento == "reset_cortes":
                    session_lineas_corte = []
                    session_shock = 1.0
                    session_clima = clima_real_actual
                elif tipo_evento == "restaurar_cortes":
                    session_lineas_corte = sanear_lineas_corte(
                        datos_recibidos.get("lineas_corte", []))

                elif tipo_evento == "chat":
                    pregunta = datos_recibidos.get("mensaje", "")
                    try:
                        escenario = copiloto.escenario_de_sesion(
                            cached_data[1] if cached_data else None,
                            session_ultimo_resultado,
                            len(session_lineas_corte), session_clima, session_shock)

                        respuesta, session_historial_chat = await responder_copiloto(
                            puerto_id,
                            cached_data[1] if cached_data else {},
                            escenario, pregunta, session_historial_chat)

                        await websocket.send_json({"status": "chat",
                                                   "respuesta": respuesta})
                    except ValueError as e:
                        await websocket.send_json({"status": "chat_error",
                                                   "message": str(e)})
                    except Exception as e:
                        print(f"Error del copiloto en {puerto_id}: {e}", flush=True)
                        traceback.print_exc()
                        await websocket.send_json({
                            "status": "chat_error",
                            "message": "El copiloto no está disponible ahora mismo."})
                    continue

            if tipo_evento in ["corte", "clima", "shock", "reset_cortes",
                               "restaurar_cortes"]:
                if tipo_evento == "corte": texto_fase = "Cortando red y recalculando..."
                elif tipo_evento == "restaurar_cortes": texto_fase = "Recuperando los cortes de la sesión..."
                elif tipo_evento == "reset_cortes": texto_fase = "Restaurando topología original..."
                elif tipo_evento == "shock": texto_fase = "Inyectando sobrecarga de demanda..."
                else: texto_fase = f"Aplicando clima ({session_clima.upper()})..."

                await websocket.send_json({"status": "processing", "fase": texto_fase})

                try:
                    t_calculo = time.perf_counter()
                    resultado = await calcular_con_latido(
                        websocket, texto_fase,
                        calcular_impacto_dinamico, puerto_id, session_lineas_corte,
                        session_clima, cached_data, session_shock,
                        incluir_geojson=False,
                        sigue_interesando=hace_falta_todavia
                    )

                    duracion = time.perf_counter() - t_calculo
                    registrar_latencia("simulacion", duracion)
                    registrar_latencia(f"simulacion_{tipo_evento}", duracion)
                    print(f"⏱️ [{puerto_id}] {tipo_evento} recalculado en "
                          f"{duracion * 1000:.0f} ms ({len(session_lineas_corte)} cortes, "
                          f"clima={session_clima}, shock={session_shock})", flush=True)
                    session_ultimo_resultado = resultado
                    await websocket.send_json({"status": "success", "data": resultado})
                except CalculoAbandonado:
                    print(f"[{puerto_id}] cálculo abandonado ({tipo_evento})", flush=True)
                    raise
                except Exception as e:
                    print(f"Error calculando el impacto de {puerto_id} "
                          f"(evento '{tipo_evento}', {len(session_lineas_corte)} cortes): {e}", flush=True)
                    traceback.print_exc()
                    if tipo_evento == "corte" and session_lineas_corte:
                        session_lineas_corte.pop()
                    await websocket.send_json({
                        "status": "error",
                        "message": f"No se pudo calcular el impacto de ese corte: {e}",
                        "evento": tipo_evento,
                    })

    except WebSocketDisconnect:
        print(f"Cliente desconectado WS: {puerto_id}")
    except CalculoAbandonado:
        print(f"[{puerto_id}] sesión cerrada durante el cálculo", flush=True)
    except Exception as e:
        print(f"Error interno WS protegido: {str(e)}", flush=True)
        traceback.print_exc()
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.send_json({"status": "error", "message": str(e)})
    finally:
        sesion_viva["ok"] = False
