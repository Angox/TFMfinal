import boto3
import json
import math
import networkx as nx
import numpy as np
import os
import rasterio
from rasterio.session import AWSSession
from rasterio.windows import from_bounds
from rasterio.transform import rowcol
import pycountry
import reverse_geocoder as rg
import shapely.geometry
import sys
import traceback
import requests
from datetime import datetime, timezone
from scipy.spatial import cKDTree
import duckdb

from config_aws import S3_BUCKET, AWS_REGION
from calculos import (
    safe_float,
    ruta_tesela_dem,
    calcular_distancia_haversine,
    clasificar_por_categoria_overture,
    normalizar_tonelaje,
    pendiente_entre_nodos,
    penalizacion_topografica,
    proyectar_local,
    vulnerabilidad_normalizada,
    indice_compuesto,
    fuerza_gravitatoria,
    percentil_trafico,
    intensidad_visual,
)
import portwatch
from grafos import (arbol_de_caminos, reconstruir_camino,
                    coste_servicio_hinterland)
PREFIX_INPUT = "resultados_web/redes_hinterland/"
PREFIX_INDUSTRIA = "resultados_web/nodos_industriales/"
PREFIX_OUTPUT = "resultados_web/api/"
PREFIX_CACHES = "resultados_web/api/caches/"
PREFIX_FALLIDOS = "resultados_web/api/fallidos/"

PARAMETROS = {
    "friccion_rail": 0.1,
    "friccion_autopista": 0.4,
    "friccion_primaria": 0.7,
    "friccion_secundaria": 2.5,
    "friccion_otras": 2.5,
    "friccion_ultima_milla": 2.5,

    "penalizacion_tonelaje_limitado": 50.0,
    "umbral_tonelaje_t": 40.0,
    "penalizacion_sin_pavimentar": 3.5,
    "penalizacion_hgv_restringido": 999999.0,

    "factor_pendiente_camion": 10.0,
    "factor_pendiente_tren": 50.0,
    "pendiente_maxima_camion": 0.15,
    "pendiente_maxima_tren": 0.04,
    "divisor_poblacion": 10000.0,
    "ventana_poblacion_px": 5,

    "cuota_tren": 0.20,
    "min_aristas_ferro": 50,
    "umbral_borde_puerto_seco_grados": 0.05,
    "masa_puerto_seco": 50000.0,

    "radio_buffer_puertas_km": 3.0,
    "max_puertas_respaldo": 6,

    "percentil_capacidad": 0.95,
    "dias_ventana_carga": 365,
    "min_dias_base_capacidad": 180,
    "capacidad_fallback_por_puerta": 8000.0,
    "n_aristas_criticas": 12,
    "lambda_vulnerabilidad": 3.0,
    "penalizacion_desconexion": 10.0,
    "peso_saturacion": 5.0,
    "peso_cuello_botella": 5.0,

    "funcion_disuasion": "exponencial",
    "beta_disuasion": 0.03,
    "exponente_gravedad": 2.0,

    "teus_por_buque_container": 2.0,
    "teus_por_buque_roro": 2.5,
    "teus_por_buque_general": 1.0,
    "teus_por_buque_bulk": 0.3,
    "teus_por_buque_tanker": 0.1,

    "region_dem": "eu-central-1",
    "altitud_minima_valida": -500.0,
    "url_hrsl": ("https://dataforgood-fb-data.s3.us-east-1.amazonaws.com"
                 "/hrsl-cogs/hrsl_general/hrsl_general-latest.vrt"),
    "decimales_cache_raster": 4,

    "radio_extraccion_km": 50,
    "confianza_minima_overture": 0.50,
    "incluir_comercio_minorista": False,
}

PARAMETROS_BASE = dict(PARAMETROS)


def aplicar_parametros(sobrescrituras=None):
    PARAMETROS.clear()
    PARAMETROS.update(PARAMETROS_BASE)
    if sobrescrituras:
        desconocidos = set(sobrescrituras) - set(PARAMETROS_BASE)
        if desconocidos:
            raise KeyError(f"parámetros desconocidos: {sorted(desconocidos)}")
        PARAMETROS.update(sobrescrituras)
    return PARAMETROS


def recuento_buques(datos_puerto):
    return {
        "container": safe_float(datos_puerto.get("vessel_count_container")),
        "roro": safe_float(datos_puerto.get("vessel_count_RoRo")),
        "general": safe_float(datos_puerto.get("vessel_count_general_cargo")),
        "bulk": safe_float(datos_puerto.get("vessel_count_dry_bulk")),
        "tanker": safe_float(datos_puerto.get("vessel_count_tanker")),
    }


def calcular_volumenes(datos_puerto, usar_portwatch=True, serie_diaria=None):
    portid = datos_puerto.get("portid")
    if usar_portwatch and portid:
        if serie_diaria is not None:
            perfil = portwatch.resumir_serie(
                serie_diaria,
                dias_ventana=PARAMETROS["dias_ventana_carga"],
                percentil_capacidad=PARAMETROS["percentil_capacidad"],
                min_dias_base=PARAMETROS["min_dias_base_capacidad"],
            )
        else:
            perfil = portwatch.obtener_perfil_volumen(
                portid,
                dias_ventana=PARAMETROS["dias_ventana_carga"],
                percentil_capacidad=PARAMETROS["percentil_capacidad"],
                min_dias_base=PARAMETROS["min_dias_base_capacidad"],
            )
        if perfil and perfil.get("capacidad_movible", 0) > 0:
            buques = recuento_buques(datos_puerto)
            return {
                "buques": buques,
                "total_barcos": sum(buques.values()) or 1.0,
                "volumen_diario_movible": int(perfil["carga_movible"]),
                "volumen_diario_directo": int(perfil["carga_directa"]),
                "capacidad_diaria": float(perfil["capacidad_movible"]),
                "saturacion": float(perfil["frecuencia_excedencia"]),
                "origen_saturacion": ("frecuencia_excedencia_autoreferente"
                                      if perfil.get("capacidad_autoreferente")
                                      else "frecuencia_excedencia"),
                "indice_comparable": not perfil.get("capacidad_autoreferente", False),
                "unidad_volumen": "toneladas/dia",
                "origen_volumen": "portwatch_diario",
                "perfil_portwatch": perfil,
            }

    return _volumenes_por_escalas(datos_puerto)


def _volumenes_por_escalas(datos_puerto):
    b = recuento_buques(datos_puerto)
    total_barcos = sum(b.values()) or 1.0

    teus = {k: b[k] * PARAMETROS[f"teus_por_buque_{k}"] for k in b}
    carga_directa = teus["bulk"] + teus["tanker"]
    carga_movible = teus["container"] + teus["roro"] + teus["general"]

    movible = int((carga_movible / 365.0) * 1000)
    return {
        "buques": b,
        "total_barcos": total_barcos,
        "volumen_diario_movible": movible,
        "volumen_diario_directo": int((carga_directa / 365.0) * 1000),
        "capacidad_diaria": None,
        "saturacion": None,
        "origen_saturacion": "cociente_capacidad_constante",
        "indice_comparable": False,
        "unidad_volumen": "TEU-equivalente/dia (estimado)",
        "origen_volumen": "estimado_por_escalas",
        "perfil_portwatch": None,
    }


MAPEO_SECTORES = {
    "automocion_transporte": {
        "hs_codes": ["87", "86", "88", "89"],
        "overture_cats": ["car_factory", "automotive_repair", "automotive_parts", "vehicle", "car_dealer", "car_rental", "gas_station", "truck_stop"]
    },
    "tecnologia_maquinaria": {
        "hs_codes": ["84", "85"],
        "overture_cats": ["electronics", "technology", "semiconductor", "computer", "telecommunications", "machinery", "appliance", "electronics_store"]
    },
    "quimica_pharma": {
        "hs_codes": ["30", "28", "29", "31", "38"],
        "overture_cats": ["pharmaceutical", "chemical_plant", "laboratory", "medical_supply", "cosmetics", "refinery", "pharmacy", "hospital"]
    },
    "agroalimentario": {
        "hs_codes": [str(i).zfill(2) for i in range(1, 25)],
        "overture_cats": ["food_processing", "agricultural_facility", "farm", "brewery", "winery", "distillery", "bakery", "cold_storage", "supermarket", "grocery_store", "restaurant"]
    },
    "textil_moda": {
        "hs_codes": [str(i).zfill(2) for i in range(50, 64)],
        "overture_cats": ["clothing_store", "textile_mill", "apparel_manufacturing", "shoes", "boutique", "department_store"]
    },
    "materiales_construccion": {
        "hs_codes": ["25", "44", "68", "72", "73", "74", "76"],
        "overture_cats": ["hardware_store", "construction", "building_materials", "lumber_yard", "mining", "metal_fabrication", "contractor"]
    },
    "energia_combustibles": {
        "hs_codes": ["27"],
        "overture_cats": ["power_plant", "oil_and_gas", "energy", "fuel_supplier"]
    },
    "generico_logistica": {
        "hs_codes": [],
        "overture_cats": [
            "logistics", "warehouse", "distribution_center", "industrial_park",
            "industrial", "manufacturing", "factory", "port", "freight"
        ]
    }
}

def cargar_perfiles_comtrade_s3():
    print("Descargando matriz económica Comtrade desde S3...", flush=True)
    try:
        obj = s3_client.get_object(Bucket=S3_BUCKET, Key="fuentes_externas/comtrade/perfiles.json")
        return json.loads(obj['Body'].read().decode('utf-8'))
    except Exception as e:
        print(f"Aviso: No se encontró perfiles.json en S3. Usando genérico. Error: {e}", flush=True)
        return {}


def obtener_ultima_version_overture():
    try:
        print("Consultando STAC de Overture Maps para obtener la última versión...", flush=True)
        resp = requests.get("https://stac.overturemaps.org/catalog.json", timeout=5)
        latest = resp.json()["latest"]
        print(f"Overture Release detectada: {latest}", flush=True)
        return latest
    except Exception as e:
        print(f"Fallo al consultar STAC. Usando versión de respaldo. Error: {e}", flush=True)
        return "2026-07-22.0"

OVERTURE_RELEASE = obtener_ultima_version_overture()


s3_client = boto3.client('s3', region_name=AWS_REGION)
s3_raster_connections = {}

METRICAS = {}


def reiniciar_metricas():
    METRICAS.clear()
    METRICAS.update({
        "vias_recibidas": 0,
        "industrias_recibidas": 0,
        "vias_geometria_invalida": 0,
        "vias_sin_aristas": 0,
        "vias_descartadas_geojson": 0,
        "coords_dem_solicitadas": 0,
        "coords_dem_fuera_de_ventana": 0,
        "coords_pop_solicitadas": 0,
        "coords_pop_fuera_de_ventana": 0,
        "tiles_dem_fallidos": 0,
        "tiles_pop_fallidos": 0,
        "cache_elevaciones_reutilizada": 0,
        "cache_poblacion_reutilizada": 0,
    })


def contar(clave, n=1):
    METRICAS[clave] = METRICAS.get(clave, 0) + n


def resumen_calidad():
    recibidas = METRICAS.get("vias_recibidas", 0)
    descartadas = (METRICAS.get("vias_geometria_invalida", 0)
                   + METRICAS.get("vias_sin_aristas", 0))
    resumen = dict(METRICAS)
    resumen["vias_descartadas"] = descartadas
    resumen["vias_descartadas_pct"] = round(descartadas / recibidas * 100.0, 2) if recibidas else 0.0
    return resumen


def log_calidad(nombre_puerto):
    r = resumen_calidad()
    print(
        f"CALIDAD [{nombre_puerto}] "
        f"{r['vias_recibidas']} vías recibidas, "
        f"{r['vias_descartadas']} descartadas ({r['vias_descartadas_pct']}%): "
        f"{r['vias_geometria_invalida']} geometría inválida, "
        f"{r['vias_sin_aristas']} sin aristas utilizables | "
        f"topografía: {r['tiles_dem_fallidos']} teselas DEM fallidas, "
        f"{r['coords_dem_fuera_de_ventana']} coords fuera de ventana | "
        f"población: {r['tiles_pop_fallidos']} teselas HRSL fallidas",
        flush=True,
    )
    return r

def sufijo_cache():
    return f"d{int(PARAMETROS['decimales_cache_raster'])}"


def cargar_caches_puerto(puerto_id):
    print(f"[cache] Buscando caches locales para el puerto: {puerto_id}...")
    cache_alturas = {}
    cache_poblacion = {}

    puerto_seguro = clave_segura(puerto_id)
    sufijo = sufijo_cache()

    try:
        obj_alturas = s3_client.get_object(
            Bucket=S3_BUCKET,
            Key=f"{PREFIX_CACHES}{puerto_seguro}_elevaciones_{sufijo}.json")
        cache_alturas = json.loads(obj_alturas['Body'].read().decode('utf-8'))
        contar("cache_elevaciones_reutilizada", len(cache_alturas))
    except Exception:
        pass

    try:
        obj_pob = s3_client.get_object(
            Bucket=S3_BUCKET,
            Key=f"{PREFIX_CACHES}{puerto_seguro}_poblacion_{sufijo}.json")
        cache_poblacion = json.loads(obj_pob['Body'].read().decode('utf-8'))
        contar("cache_poblacion_reutilizada", len(cache_poblacion))
    except Exception:
        pass

    return cache_alturas, cache_poblacion


def guardar_caches_puerto(puerto_id, cache_alturas, cache_poblacion):
    puerto_seguro = clave_segura(puerto_id)
    sufijo = sufijo_cache()

    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=f"{PREFIX_CACHES}{puerto_seguro}_elevaciones_{sufijo}.json",
        Body=json.dumps(cache_alturas),
        ContentType="application/json"
    )
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=f"{PREFIX_CACHES}{puerto_seguro}_poblacion_{sufijo}.json",
        Body=json.dumps(cache_poblacion),
        ContentType="application/json"
    )


def cargar_puertos_fmi():
    print("Descargando catálogo de puertos FMI desde S3...", flush=True)
    obj = s3_client.get_object(Bucket=S3_BUCKET, Key="fuentes_externas/fmi_ports/puertos.json")
    contenido = obj['Body'].read().decode('utf-8')
    puertos = [json.loads(linea) for linea in contenido.strip().split('\n') if linea.strip()]
    return puertos

def inicializar_duckdb():
    print("Iniciando motor DuckDB Serverless...", flush=True)
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute(f"SET s3_region='{AWS_REGION}';")
    return con

CATEGORIAS_CARGA = [
    'logistics', 'warehouse', 'manufacturing', 'industrial', 'factory',
    'industrial_park', 'car_factory', 'electronics', 'chemical_plant',
    'power_plant', 'food_processing', 'pharmaceutical',
]
CATEGORIAS_COMERCIO = [
    'commercial', 'retail', 'shop', 'supermarket', 'market', 'hardware_store',
    'shopping_mall', 'store', 'grocery', 'office', 'business', 'trade',
]
PATRONES_CARGA = ['%industrial%', '%manufacturing%', '%logistic%', '%warehouse%']
PATRONES_COMERCIO = ['%commercial%', '%retail%', '%business%', '%shop%']


def columnas_disponibles(con, ruta_parquet):
    try:
        filas = con.execute(
            f"DESCRIBE SELECT * FROM read_parquet('{ruta_parquet}') LIMIT 0").fetchall()
        return {str(f[0]) for f in filas}
    except Exception as e:
        print(f"[aviso] No se pudo describir {ruta_parquet}: {e}", flush=True)
        return set()


def extraer_entorno_overture(con, lon_p, lat_p, radio_km=100):
    confianza_min = PARAMETROS["confianza_minima_overture"]

    coseno = math.cos(math.radians(lat_p))
    if abs(coseno) < 1e-6:
        coseno = 1e-6
    offset_lat = radio_km / 111.0
    offset_lon = radio_km / (111.0 * coseno)

    min_lon, max_lon = lon_p - offset_lon, lon_p + offset_lon
    min_lat, max_lat = lat_p - offset_lat, lat_p + offset_lat

    ruta_segmentos = (f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"
                      f"/theme=transportation/type=segment/*")
    ruta_lugares = (f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"
                    f"/theme=places/type=place/*")
    ruta_edificios = (f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"
                      f"/theme=buildings/type=building/*")
    ruta_uso_suelo = (f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"
                      f"/theme=base/type=land_use/*")

    columnas_segmento = columnas_disponibles(con, ruta_segmentos)
    hay_carriles = "lanes" in columnas_segmento
    expr_carriles = ("COALESCE(CAST(length(lanes) AS VARCHAR), '0')"
                     if hay_carriles else "'0'")
    if not hay_carriles:
        print("[info] La release de Overture no expone `lanes`: se usan los "
              "carriles por defecto de cada clase y queda en calidad_datos.",
              flush=True)

    query_vias = f"""
    SELECT
        id,
        CASE WHEN subtype = 'rail' THEN 'rail' ELSE class END AS tipo_via,
        ST_AsGeoJSON(geometry) AS geometria_geojson,
        names.primary AS nombre_via,
        {expr_carriles} AS carriles,
        CAST(speed_limits[1].max_speed.value AS VARCHAR) AS maxspeed,
        REGEXP_EXTRACT(CAST(access_restrictions AS VARCHAR), '(?i)weight[^}}]*?value[^0-9]*([0-9.]+)', 1) AS maxweight,
        REGEXP_EXTRACT(CAST(access_restrictions AS VARCHAR), '(?i)weight[^}}]*?unit[^a-zA-Z]*([a-zA-Z_]+)', 1) AS maxweight_unidad,
        CAST(road_surface AS VARCHAR) AS tipo_superficie,
        CASE
            WHEN CAST(access_restrictions AS VARCHAR) ILIKE '%hgv%no%'
              OR CAST(access_restrictions AS VARCHAR) ILIKE '%hgv%denied%'
            THEN 'yes'
            ELSE 'no'
        END AS hgv_restringido,
        CASE WHEN CAST(road_flags AS VARCHAR) LIKE '%is_toll%' THEN 'yes' ELSE 'no' END AS peaje,
        CASE WHEN CAST(road_flags AS VARCHAR) LIKE '%is_oneway%' THEN 'yes' ELSE 'no' END AS oneway,
        CASE WHEN CAST(road_flags AS VARCHAR) LIKE '%is_bridge%' THEN '1' ELSE '0' END AS layer
    FROM read_parquet('{ruta_segmentos}', filename=true, hive_partitioning=1)
    WHERE bbox.xmax >= {min_lon} AND bbox.xmin <= {max_lon}
      AND bbox.ymax >= {min_lat} AND bbox.ymin <= {max_lat}
      AND (
          (subtype = 'road' AND class IN ('motorway', 'motorway_link', 'trunk', 'trunk_link', 'primary', 'primary_link', 'secondary', 'tertiary'))
          OR
          (subtype = 'rail' AND class IN ('standard_gauge', 'narrow_gauge', 'unknown'))
      )
    """

    categorias = list(CATEGORIAS_CARGA)
    patrones = list(PATRONES_CARGA)
    if PARAMETROS["incluir_comercio_minorista"]:
        categorias += CATEGORIAS_COMERCIO
        patrones += PATRONES_COMERCIO
    lista_categorias = ", ".join(f"'{c}'" for c in categorias)
    lista_patrones = " OR ".join(
        f"CAST(basic_category AS VARCHAR) LIKE '{p}'" for p in patrones)

    query_industrias = f"""
    WITH zonas_industriales AS (
        SELECT
            id,
            names.primary AS nombre_zona,
            CAST(basic_category AS VARCHAR) AS categoria,
            confidence,
            geometry AS geom_lugar,
            (bbox.xmin + bbox.xmax)/2 AS centroide_lon,
            (bbox.ymin + bbox.ymax)/2 AS centroide_lat
        FROM read_parquet('{ruta_lugares}', filename=true, hive_partitioning=1)
        WHERE bbox.xmax >= {min_lon} AND bbox.xmin <= {max_lon}
          AND bbox.ymax >= {min_lat} AND bbox.ymin <= {max_lat}
          AND confidence >= {confianza_min}
          AND (CAST(basic_category AS VARCHAR) IN ({lista_categorias})
               OR {lista_patrones})
    )
    SELECT
        z.id,
        z.nombre_zona,
        z.categoria,
        z.centroide_lon,
        z.centroide_lat,
        COALESCE(
            SUM(ST_Area(b.geometry) * 111320 * 111320 * COS(RADIANS(z.centroide_lat))),
            2000.0
        ) AS masa_atraccion
    FROM zonas_industriales z
    LEFT JOIN read_parquet('{ruta_edificios}', filename=true, hive_partitioning=1) b
      ON b.bbox.xmax >= {min_lon} AND b.bbox.xmin <= {max_lon}
      AND b.bbox.ymax >= {min_lat} AND b.bbox.ymin <= {max_lat}
      AND ST_Intersects(z.geom_lugar, b.geometry)
    GROUP BY z.id, z.nombre_zona, z.categoria, z.centroide_lon, z.centroide_lat, z.confidence
    """

    query_poligono_puerto = f"""
    SELECT
        ST_AsGeoJSON(geometry) AS geometria_geojson
    FROM read_parquet('{ruta_uso_suelo}', filename=true, hive_partitioning=1)
    WHERE bbox.xmax >= {lon_p} AND bbox.xmin <= {lon_p}
      AND bbox.ymax >= {lat_p} AND bbox.ymin <= {lat_p}
      AND class = 'port'
      AND ST_Contains(geometry, ST_Point({lon_p}, {lat_p}))
    LIMIT 1
    """

    try:
        vias = con.execute(query_vias).pl().to_dicts()
        industrias = con.execute(query_industrias).pl().to_dicts()
        poligono_puerto = con.execute(query_poligono_puerto).pl().to_dicts()

        contar("vias_con_carriles_declarados",
               sum(1 for v in vias if safe_float(v.get("carriles")) > 0))
        if not hay_carriles:
            contar("release_sin_columna_lanes", 1)

        return vias, industrias, poligono_puerto
    except Exception as e:
        print(f"[aviso] Error consultando Overture para BBox {min_lon},{min_lat}: {e}")
        return [], [], []

def obtener_iso3(lat, lon):
    resultado = rg.search((lat, lon), verbose=False)[0]
    pais_iso2 = resultado['cc']
    pais = pycountry.countries.get(alpha_2=pais_iso2)
    if pais is None:
        print(f"País ISO-2 '{pais_iso2}' desconocido para pycountry. Se usa perfil genérico.", flush=True)
        return "XXX"
    return pais.alpha_3

def clave_raster(lat, lon):
    d = int(PARAMETROS["decimales_cache_raster"])
    return f"{round(lat, d)}_{round(lon, d)}"


def _area_pixel_km2(src_raster, lat):
    try:
        transform = src_raster.transform
        dx, dy = abs(transform.a), abs(transform.e)
        geografico = True
        if src_raster.crs is not None:
            geografico = bool(src_raster.crs.is_geographic)
        if geografico:
            ancho_km = dx * 111.32 * max(math.cos(math.radians(lat)), 1e-6)
            alto_km = dy * 110.57
        else:
            ancho_km, alto_km = dx / 1000.0, dy / 1000.0
        area = ancho_km * alto_km
        return area if area > 0 else None
    except Exception:
        return None


def _media_ventana(data, fila, columna, lado):
    radio = max(int(lado) // 2, 0)
    f0, f1 = max(fila - radio, 0), min(fila + radio + 1, data.shape[0])
    c0, c1 = max(columna - radio, 0), min(columna + radio + 1, data.shape[1])
    if f0 >= f1 or c0 >= c1:
        return None
    bloque = data[f0:f1, c0:c1]
    validos = bloque[~np.isnan(bloque)] if bloque.dtype.kind == "f" else bloque
    if validos.size == 0:
        return None
    return float(validos.mean())


def precalcular_caches_en_bloque(vias, cache_alturas, cache_poblacion, iso3_puerto=None):
    print("[fase 1] Recolectando coordenadas unicas (cache en RAM)...")
    pendientes_dem = {}
    pendientes_pop = {}

    coordenadas_vistas_dem = set()
    coordenadas_vistas_pop = set()

    for via in vias:
        try:
            geom_dict = json.loads(via['geometria_geojson'])
            geom_original = shapely.geometry.shape(geom_dict)
            via['geom_original'] = geom_original

            via['geom_simplificada'] = geom_original

            lineas = []
            if geom_original.geom_type == 'LineString':
                lineas.append(list(geom_original.coords))
            elif geom_original.geom_type == 'MultiLineString':
                for l in geom_original.geoms:
                    lineas.append(list(l.coords))
            elif geom_original.geom_type == 'Polygon':
                lineas.append(list(geom_original.exterior.coords))

            for coords in lineas:
                for lon, lat in coords:
                    coord_str = clave_raster(lat, lon)

                    if coord_str not in cache_alturas and coord_str not in coordenadas_vistas_dem:
                        coordenadas_vistas_dem.add(coord_str)
                        tile_dem = ruta_tesela_dem(lat, lon)
                        if tile_dem not in pendientes_dem:
                            pendientes_dem[tile_dem] = []
                        pendientes_dem[tile_dem].append((lon, lat, coord_str))

                    if coord_str not in cache_poblacion and coord_str not in coordenadas_vistas_pop:
                        coordenadas_vistas_pop.add(coord_str)
                        tile_pop = PARAMETROS["url_hrsl"]
                        if tile_pop not in pendientes_pop:
                            pendientes_pop[tile_pop] = []
                        pendientes_pop[tile_pop].append((lon, lat, coord_str))
        except Exception:
            contar("vias_geometria_invalida")

    contar("coords_dem_solicitadas", len(coordenadas_vistas_dem))
    contar("coords_pop_solicitadas", len(coordenadas_vistas_pop))
    print(f"[fase 1] {len(coordenadas_vistas_dem)} peticiones logicas a Copernicus "
          f"agrupadas en {len(pendientes_dem)} teselas.")

    aws_session = AWSSession(aws_unsigned=True)
    altitud_minima = float(PARAMETROS["altitud_minima_valida"])

    with rasterio.Env(aws_session, AWS_REGION=PARAMETROS["region_dem"]):
        for path, puntos in pendientes_dem.items():
            print(f"   -> Matriz topografica de {len(puntos)} puntos en 1 peticion HTTP...", flush=True)
            try:
                lons, lats = [p[0] for p in puntos], [p[1] for p in puntos]
                min_lon, max_lon = min(lons) - 0.01, max(lons) + 0.01
                min_lat, max_lat = min(lats) - 0.01, max(lats) + 0.01

                with rasterio.open(path) as src_r:
                    window = from_bounds(min_lon, min_lat, max_lon, max_lat, src_r.transform)
                    window = window.intersection(rasterio.windows.Window(0, 0, src_r.width, src_r.height))
                    data = src_r.read(1, window=window).astype("float64")
                    win_transform = src_r.window_transform(window)
                    nodata = src_r.nodata

                    for p in puntos:
                        lon, lat, coord_str = p[0], p[1], p[2]
                        row, col = rowcol(win_transform, lon, lat)
                        if not (0 <= row < data.shape[0] and 0 <= col < data.shape[1]):
                            cache_alturas[coord_str] = None
                            contar("coords_dem_fuera_de_ventana")
                            continue
                        val = float(data[row, col])
                        if (math.isnan(val)
                                or (nodata is not None and val == float(nodata))
                                or val < altitud_minima):
                            cache_alturas[coord_str] = None
                            contar("coords_dem_sin_dato")
                        else:
                            cache_alturas[coord_str] = val
            except Exception as e:
                contar("tiles_dem_fallidos")
                contar("coords_dem_fuera_de_ventana", len(puntos))
                print(f"   [aviso] Tesela DEM inaccesible ({len(puntos)} puntos sin dato): {e}", flush=True)
                for p in puntos:
                    cache_alturas[p[2]] = None

    lado_ventana = int(PARAMETROS["ventana_poblacion_px"])
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                      CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".vrt,.tif"):
        for path, puntos in pendientes_pop.items():
            print(f"   -> Matriz de poblacion de {len(puntos)} puntos en 1 peticion HTTP...", flush=True)
            try:
                lons, lats = [p[0] for p in puntos], [p[1] for p in puntos]
                min_lon, max_lon = min(lons) - 0.01, max(lons) + 0.01
                min_lat, max_lat = min(lats) - 0.01, max(lats) + 0.01

                with rasterio.open(path) as src_r:
                    window = from_bounds(min_lon, min_lat, max_lon, max_lat, src_r.transform)
                    window = window.intersection(rasterio.windows.Window(0, 0, src_r.width, src_r.height))
                    data = src_r.read(1, window=window).astype("float64")
                    win_transform = src_r.window_transform(window)
                    nodata = src_r.nodata
                    if nodata is not None:
                        data[data == float(nodata)] = np.nan

                    lat_media = (min_lat + max_lat) / 2.0
                    area_px = _area_pixel_km2(src_r, lat_media)

                    for p in puntos:
                        lon, lat, coord_str = p[0], p[1], p[2]
                        row, col = rowcol(win_transform, lon, lat)
                        if not (0 <= row < data.shape[0] and 0 <= col < data.shape[1]):
                            cache_poblacion[coord_str] = 0.0
                            contar("coords_pop_fuera_de_ventana")
                            continue
                        media = _media_ventana(data, row, col, lado_ventana)
                        if media is None:
                            cache_poblacion[coord_str] = 0.0
                            contar("coords_pop_sin_dato")
                            continue
                        densidad = media / area_px if area_px else media
                        cache_poblacion[coord_str] = max(0.0, float(densidad))
            except Exception as e:
                contar("tiles_pop_fallidos")
                contar("coords_pop_fuera_de_ventana", len(puntos))
                print(f"   [aviso] Tesela HRSL inaccesible ({len(puntos)} puntos a 0 hab/km2): {e}", flush=True)
                for p in puntos:
                    cache_poblacion[p[2]] = 0.0


CLASES_PUERTA = ('motorway', 'trunk', 'primary', 'secondary',
                 'motorway_link', 'trunk_link', 'primary_link',
                 'tertiary', 'unclassified')


CLASES_PUERTA_FERRO = ('rail',)


def _prioridad_clase(tipo_via, clases):
    try:
        return clases.index(tipo_via)
    except ValueError:
        return len(clases)


def puertas_por_proximidad(grafo, lon_p, lat_p, radio_km, max_puertas,
                           clases=CLASES_PUERTA):
    if not grafo.nodes:
        return []

    candidatos = {}
    for u, v, datos in grafo.edges(data=True):
        tipo = datos.get('tipo_via')
        if tipo not in clases:
            continue
        nombre = datos.get('nombre_via') or datos.get('tipo_via') or 'sin_nombre'
        for nodo in (u, v):
            distancia = calcular_distancia_haversine(
                float(lon_p), float(lat_p), nodo[0], nodo[1])
            if distancia > radio_km:
                continue
            clave = (tipo, nombre)
            actual = candidatos.get(clave)
            if actual is None or distancia < actual[0]:
                candidatos[clave] = (distancia, nodo)

    ordenados = sorted(
        ((dist, _prioridad_clase(tipo, clases), nodo)
         for (tipo, _nombre), (dist, nodo) in candidatos.items()),
        key=lambda t: (t[1], t[0]))

    puertas, vistos = [], set()
    for _dist, _prio, nodo in ordenados:
        if nodo in vistos:
            continue
        vistos.add(nodo)
        puertas.append(nodo)
        if len(puertas) >= max_puertas:
            break
    return puertas


def vulnerabilidad_por_interdiccion(grafo, origenes, destinos_demanda,
                                    trafico_aristas, n_candidatas,
                                    penalizacion_desconexion, peso='weight'):
    if n_candidatas <= 0 or not destinos_demanda or not origenes:
        return 0.0, {}

    base = coste_servicio_hinterland(grafo, origenes, destinos_demanda, peso)
    if base["total"] <= 0 or base["coste"] <= 0 or base["servida"] <= 0:
        return 0.0, {}

    coste_medio = base["coste"] / base["servida"]
    coste_referencia = base["coste"] + base["desconectada"] * penalizacion_desconexion * coste_medio

    candidatas = sorted(
        (a for a in trafico_aristas.items() if a[1] > 0 and grafo.has_edge(*a[0])),
        key=lambda kv: kv[1], reverse=True)[:int(n_candidatas)]
    if not candidatas:
        return 0.0, {}

    mejor_incremento = 0.0
    mejor_arista = None
    mejor_desconexion = 0.0

    for (u, v), _carga in candidatas:
        arcos = []
        for a, b in ((u, v), (v, u)):
            if grafo.has_edge(a, b):
                arcos.append((a, b, dict(grafo[a][b])))
        if not arcos:
            continue
        grafo.remove_edges_from([(a, b) for a, b, _d in arcos])
        try:
            corte = coste_servicio_hinterland(grafo, origenes, destinos_demanda, peso)
            coste_corte = (corte["coste"]
                           + corte["desconectada"] * penalizacion_desconexion * coste_medio)
            incremento = (coste_corte - coste_referencia) / coste_referencia
            if incremento > mejor_incremento:
                mejor_incremento = incremento
                mejor_arista = (u, v)
                mejor_desconexion = ((corte["desconectada"] - base["desconectada"])
                                     / base["total"] if base["total"] else 0.0)
        finally:
            for a, b, datos in arcos:
                grafo.add_edge(a, b, **datos)

    detalle = {
        "arista_critica": [list(mejor_arista[0]), list(mejor_arista[1])] if mejor_arista else None,
        "candidatas_evaluadas": len(candidatas),
        "fraccion_demanda_desconectada": round(mejor_desconexion, 4),
        "coste_base": round(base["coste"], 3),
        "coste_medio_unitario": round(coste_medio, 4),
    }
    return mejor_incremento, detalle


def calcular_estres_logistico(vias, industrias_locales, poligono_puerto_data,
                              cache_alturas, cache_poblacion, volumen_carga,
                              lon_p, lat_p, matriz_comtrade,
                              capacidad_diaria=None, saturacion_medida=None):
    print("[motor] Grafo intermodal (carretera y ferrocarril)...", flush=True)

    iso3_puerto = obtener_iso3(lat_p, lon_p)
    precalcular_caches_en_bloque(vias, cache_alturas, cache_poblacion, iso3_puerto)

    G_vial = nx.DiGraph()
    G_ferro = nx.DiGraph()
    nodos_puertas_viales = set()
    nodos_puertas_ferro = set()

    perimetro_puerto = None
    if poligono_puerto_data:
        try:
            geom_dict = json.loads(poligono_puerto_data[0]['geometria_geojson'])
            perimetro_puerto = shapely.geometry.shape(geom_dict).boundary
        except Exception as e:
            print(f"[aviso] No se pudo procesar el perimetro del puerto: {e}")

    n_sentido_unico = sum(1 for v in vias
                          if str(v.get('oneway', '')).lower() in ('yes', 'true', '1'))
    sentido_unico_disponible = n_sentido_unico > 0
    contar("vias_sentido_unico", n_sentido_unico)
    if not sentido_unico_disponible:
        contar("sentido_unico_no_disponible", 1)

    factor_pend_camion = PARAMETROS["factor_pendiente_camion"]
    factor_pend_tren = PARAMETROS["factor_pendiente_tren"]
    pend_max_camion = PARAMETROS["pendiente_maxima_camion"]
    pend_max_tren = PARAMETROS["pendiente_maxima_tren"]
    divisor_pob = PARAMETROS["divisor_poblacion"]
    umbral_t = PARAMETROS["umbral_tonelaje_t"]

    for via in vias:
        try:
            geom_simplificada = via.get('geom_simplificada')
            if not geom_simplificada:
                continue

            tipo_via = via.get('tipo_via', 'unclassified')
            nombre_via = via.get('ref_via') or via.get('nombre_via') or 'Desconocida'

            es_puerta_oficial = False
            if perimetro_puerto and via.get('geom_original'):
                if via['geom_original'].intersects(perimetro_puerto):
                    if tipo_via in CLASES_PUERTA or tipo_via == 'rail':
                        es_puerta_oficial = True

            peaje = via.get('peaje')
            oneway_tag = str(via.get('oneway', '')).lower()
            layer_tag = via.get('layer', '0')
            if not layer_tag:
                layer_tag = '0'

            peso_maximo_via = normalizar_tonelaje(
                via.get('maxweight'), via.get('maxweight_unidad'))

            penalizacion_peso = 1.0
            friccion_vial_base = PARAMETROS["friccion_otras"]
            es_sentido_inverso = False

            if tipo_via == 'rail':
                friccion_vial_base = PARAMETROS["friccion_rail"]
                carriles = 1
                es_doble_sentido = True
            else:
                if via.get('hgv_restringido') == 'yes' and \
                        PARAMETROS["penalizacion_hgv_restringido"] > 1.0:
                    contar("vias_prohibidas_hgv")
                    continue

                if peso_maximo_via is not None and peso_maximo_via < umbral_t:
                    penalizacion_peso *= PARAMETROS["penalizacion_tonelaje_limitado"]
                    contar("vias_con_tonelaje_limitado")

                tipo_superficie = str(via.get('tipo_superficie', '')).lower()
                if any(s in tipo_superficie for s in ('unpaved', 'dirt', 'gravel', 'sand')):
                    penalizacion_peso *= PARAMETROS["penalizacion_sin_pavimentar"]

                try:
                    carriles = int(float(via.get('carriles', 0) or 0))
                except (TypeError, ValueError):
                    carriles = 0
                carriles = max(0, min(carriles, 8))

                if tipo_via in ('motorway', 'motorway_link', 'trunk', 'trunk_link'):
                    friccion_vial_base = PARAMETROS["friccion_autopista"]
                    if carriles == 0:
                        carriles = 2
                elif tipo_via in ('primary', 'primary_link'):
                    friccion_vial_base = PARAMETROS["friccion_primaria"]
                    if carriles == 0:
                        carriles = 1
                elif tipo_via in ('secondary', 'tertiary'):
                    friccion_vial_base = PARAMETROS["friccion_secundaria"]
                    if carriles == 0:
                        carriles = 1
                else:
                    if carriles == 0:
                        carriles = 1

                vias_un_sentido_por_defecto = ('motorway', 'motorway_link',
                                               'trunk', 'trunk_link')
                if oneway_tag in ('yes', 'true', '1'):
                    es_doble_sentido = False
                elif oneway_tag == '-1':
                    es_doble_sentido = False
                    es_sentido_inverso = True
                elif sentido_unico_disponible:
                    es_doble_sentido = True
                else:
                    es_doble_sentido = tipo_via not in vias_un_sentido_por_defecto

            friccion_vial = friccion_vial_base / carriles

            lineas_a_procesar = []
            if geom_simplificada.geom_type == 'LineString':
                lineas_a_procesar.append(list(geom_simplificada.coords))
            elif geom_simplificada.geom_type == 'MultiLineString':
                for linea in geom_simplificada.geoms:
                    lineas_a_procesar.append(list(linea.coords))
            elif geom_simplificada.geom_type == 'Polygon':
                lineas_a_procesar.append(list(geom_simplificada.exterior.coords))

            factor_pendiente = factor_pend_tren if tipo_via == 'rail' else factor_pend_camion
            pendiente_maxima = pend_max_tren if tipo_via == 'rail' else pend_max_camion
            G_target = G_ferro if tipo_via == 'rail' else G_vial
            puertas_target = nodos_puertas_ferro if tipo_via == 'rail' else nodos_puertas_viales

            for coords in lineas_a_procesar:
                for i in range(len(coords) - 1):
                    lon1, lat1 = round(coords[i][0], 5), round(coords[i][1], 5)
                    lon2, lat2 = round(coords[i + 1][0], 5), round(coords[i + 1][1], 5)

                    if lon1 == lon2 and lat1 == lat2:
                        continue
                    distancia = calcular_distancia_haversine(lon1, lat1, lon2, lat2)
                    if distancia == 0:
                        continue

                    clave_origen = clave_raster(lat1, lon1)
                    clave_destino = clave_raster(lat2, lon2)
                    alt1 = cache_alturas.get(clave_origen)
                    alt2 = cache_alturas.get(clave_destino)

                    if tipo_via == 'rail':
                        penalizacion_urbana = 1.0
                    else:
                        densidad = (cache_poblacion.get(clave_origen, 0.0)
                                    + cache_poblacion.get(clave_destino, 0.0)) / 2.0
                        penalizacion_urbana = 1 + (densidad / divisor_pob)

                    nodo_origen = (lon1, lat1)
                    nodo_destino = (lon2, lat2)

                    pendiente_ida = pendiente_entre_nodos(
                        alt1, alt2, distancia, pendiente_maxima)

                    if not es_sentido_inverso:
                        topo_ida = penalizacion_topografica(pendiente_ida, factor_pendiente)
                        peso_ida = (distancia * topo_ida * penalizacion_urbana
                                    * friccion_vial * penalizacion_peso)
                        G_target.add_edge(
                            nodo_origen, nodo_destino,
                            weight=peso_ida,
                            capacidad=1.0 / peso_ida if peso_ida > 0 else 1.0,
                            tipo_via=tipo_via, nombre_via=nombre_via, peaje=peaje,
                            layer=layer_tag, maxweight=peso_maximo_via,
                            original_coords=[[lon1, lat1], [lon2, lat2]])
                        if es_puerta_oficial:
                            puertas_target.add(nodo_origen)

                    if es_doble_sentido or es_sentido_inverso:
                        topo_vuelta = penalizacion_topografica(-pendiente_ida, factor_pendiente)
                        peso_vuelta = (distancia * topo_vuelta * penalizacion_urbana
                                       * friccion_vial * penalizacion_peso)
                        G_target.add_edge(
                            nodo_destino, nodo_origen,
                            weight=peso_vuelta,
                            capacidad=1.0 / peso_vuelta if peso_vuelta > 0 else 1.0,
                            tipo_via=tipo_via, nombre_via=nombre_via, peaje=peaje,
                            layer=layer_tag, maxweight=peso_maximo_via,
                            original_coords=[[lon2, lat2], [lon1, lat1]])
                        if es_puerta_oficial:
                            puertas_target.add(nodo_destino)
        except Exception:
            contar("vias_sin_aristas")
            continue

    nodos_antes_vial = len(G_vial.nodes)
    if nodos_antes_vial > 0:
        componentes_vial = list(nx.weakly_connected_components(G_vial))
        if componentes_vial:
            G_vial = G_vial.subgraph(max(componentes_vial, key=len)).copy()
    contar("nodos_vial_antes_poda", nodos_antes_vial)
    contar("nodos_vial_tras_poda", len(G_vial.nodes))

    if len(G_ferro.nodes) > 0:
        componentes_ferro = list(nx.weakly_connected_components(G_ferro))
        if componentes_ferro:
            G_ferro = G_ferro.subgraph(max(componentes_ferro, key=len)).copy()

    nodos_puertas_viales = {n for n in nodos_puertas_viales if n in G_vial.nodes}
    nodos_puertas_ferro = {n for n in nodos_puertas_ferro if n in G_ferro.nodes}

    if nodos_puertas_viales:
        origen_puertas = "perimetro_overture"
    else:
        respaldo = puertas_por_proximidad(
            G_vial, lon_p, lat_p,
            PARAMETROS["radio_buffer_puertas_km"],
            PARAMETROS["max_puertas_respaldo"])
        if respaldo:
            nodos_puertas_viales = set(respaldo)
            origen_puertas = "respaldo_radio"
        else:
            origen_puertas = "nodo_artificial"
    contar("puertas_viales_detectadas", len(nodos_puertas_viales))

    if not nodos_puertas_ferro and len(G_ferro.nodes) > 0:
        nodos_puertas_ferro = set(puertas_por_proximidad(
            G_ferro, lon_p, lat_p,
            PARAMETROS["radio_buffer_puertas_km"],
            PARAMETROS["max_puertas_respaldo"],
            clases=CLASES_PUERTA_FERRO))

    nodo_puerto = (round(float(lon_p), 5), round(float(lat_p), 5))
    if len(G_vial.nodes) > 0 and not nodos_puertas_viales and nodo_puerto not in G_vial.nodes:
        nodos_cercanos = sorted(
            G_vial.nodes,
            key=lambda n: calcular_distancia_haversine(float(lon_p), float(lat_p), n[0], n[1])
        )[:3]
        G_vial.add_node(nodo_puerto)
        for nc in nodos_cercanos:
            G_vial.add_edge(nodo_puerto, nc, weight=0.001, capacidad=1000.0,
                            tipo_via='service', nombre_via='Acceso sintetico',
                            original_coords=[[float(lon_p), float(lat_p)], [nc[0], nc[1]]])

    cuota_tren = 0.0
    if len(G_ferro.edges) > PARAMETROS["min_aristas_ferro"] and len(nodos_puertas_ferro) > 0:
        red_ferro_util = set()
        G_ferro_undir = G_ferro.to_undirected()

        for p_ferro in nodos_puertas_ferro:
            if p_ferro in G_ferro_undir.nodes:
                red_ferro_util.update(nx.node_connected_component(G_ferro_undir, p_ferro))

        if red_ferro_util:
            cuota_tren = PARAMETROS["cuota_tren"]

            all_lons = [n[0] for n in red_ferro_util]
            all_lats = [n[1] for n in red_ferro_util]
            min_l, max_l = min(all_lons), max(all_lons)
            min_la, max_la = min(all_lats), max(all_lats)
            umbral = PARAMETROS["umbral_borde_puerto_seco_grados"]

            for nodo in red_ferro_util:
                if (nodo[0] <= min_l + umbral or nodo[0] >= max_l - umbral
                        or nodo[1] <= min_la + umbral or nodo[1] >= max_la - umbral):
                    industrias_locales.append({
                        "nombre_zona": "Puerto Seco Ferroviario (Sumidero Interland)",
                        "categoria": "logistics",
                        "centroide_lon": nodo[0],
                        "centroide_lat": nodo[1],
                        "masa_atraccion": PARAMETROS["masa_puerto_seco"]
                    })

    volumen_tren = volumen_carga * cuota_tren
    volumen_camion = volumen_carga * (1.0 - cuota_tren)

    trafico_aristas = {}
    for u, v in G_vial.edges():
        trafico_aristas[(u, v)] = 0.0
    for u, v in G_ferro.edges():
        trafico_aristas[(u, v)] = 0.0

    origenes_viales = [n for n in nodos_puertas_viales if n in G_vial.nodes]
    if not origenes_viales and nodo_puerto in G_vial.nodes:
        origenes_viales = [nodo_puerto]
    origenes_ferro = [n for n in nodos_puertas_ferro if n in G_ferro.nodes]

    rutas_viales, preds_viales = ({}, {})
    if len(G_vial.nodes) > 0 and origenes_viales:
        try:
            rutas_viales, preds_viales = arbol_de_caminos(G_vial, origenes_viales, 'weight')
        except Exception as e:
            print(f"[aviso] Dijkstra vial fallido: {e}", flush=True)

    rutas_ferro, preds_ferro = ({}, {})
    if len(G_ferro.nodes) > 0 and origenes_ferro:
        try:
            rutas_ferro, preds_ferro = arbol_de_caminos(G_ferro, origenes_ferro, 'weight')
        except Exception as e:
            print(f"[aviso] Dijkstra ferroviario fallido: {e}", flush=True)

    perfil_economico = matriz_comtrade.get(iso3_puerto, {"generico_logistica": 1.0})
    industrias_clasificadas = {sector: [] for sector in MAPEO_SECTORES.keys()}
    industrias_comerciales_fallback = []

    for ind in industrias_locales:
        sector_asignado = clasificar_por_categoria_overture(ind.get('categoria'), MAPEO_SECTORES)
        if sector_asignado:
            industrias_clasificadas[sector_asignado].append(ind)
        else:
            industrias_comerciales_fallback.append(ind)

    exponente = PARAMETROS["exponente_gravedad"]
    funcion_disuasion = PARAMETROS["funcion_disuasion"]
    beta_disuasion = PARAMETROS["beta_disuasion"]
    friccion_ultima_milla = PARAMETROS["friccion_ultima_milla"]
    nodos_demanda_vial = {}

    for grafo_modo, rutas_modo, preds_modo, vol_modo, es_vial in [
        (G_vial, rutas_viales, preds_viales, volumen_camion, True),
        (G_ferro, rutas_ferro, preds_ferro, volumen_tren, False)
    ]:
        if not grafo_modo.nodes or vol_modo <= 0:
            continue
        nodos_alcanzables = list(rutas_modo.keys())
        if not nodos_alcanzables:
            continue

        puntos_proyectados = [proyectar_local(n[0], n[1], lon_p, lat_p)
                              for n in nodos_alcanzables]
        arbol_espacial = cKDTree(puntos_proyectados)

        for sector, porcentaje_carga in perfil_economico.items():
            carga_sectorial = vol_modo * porcentaje_carga
            if carga_sectorial == 0:
                continue

            industrias_objetivo = industrias_clasificadas.get(sector, [])
            if not industrias_objetivo:
                industrias_objetivo = industrias_clasificadas.get("generico_logistica", [])
            if not industrias_objetivo:
                industrias_objetivo = industrias_comerciales_fallback
            if not industrias_objetivo:
                continue

            nodos_destino_sector = []

            for ind in industrias_objetivo:
                ind_lon, ind_lat = float(ind['centroide_lon']), float(ind['centroide_lat'])
                masa_bruta = float(ind['masa_atraccion'])

                try:
                    consulta = proyectar_local(ind_lon, ind_lat, lon_p, lat_p)
                    _dist_plana, indices = arbol_espacial.query(consulta, k=1)
                    idx = int(indices) if np.ndim(indices) == 0 else int(indices[0])
                    nodo_frontera = nodos_alcanzables[idx]

                    dist_hav = calcular_distancia_haversine(
                        nodo_frontera[0], nodo_frontera[1], ind_lon, ind_lat)
                    coste_total = rutas_modo[nodo_frontera] + dist_hav * friccion_ultima_milla

                    fuerza = fuerza_gravitatoria(
                        masa_bruta, coste_total, funcion_disuasion,
                        exponente, beta_disuasion)
                    if fuerza is not None and fuerza > 0:
                        nodos_destino_sector.append({
                            'nodo': nodo_frontera, 'fuerza': fuerza,
                            'camino': reconstruir_camino(nodo_frontera, preds_modo),
                            'ind_ref': ind
                        })
                except Exception:
                    continue

            sumatorio_fuerzas_sector = sum(d['fuerza'] for d in nodos_destino_sector)
            if sumatorio_fuerzas_sector > 0:
                for dest in nodos_destino_sector:
                    cuota_trafico = (dest['fuerza'] / sumatorio_fuerzas_sector) * carga_sectorial
                    dest['ind_ref']['demanda_teus_fija'] = \
                        dest['ind_ref'].get('demanda_teus_fija', 0.0) + cuota_trafico
                    if es_vial:
                        nodos_demanda_vial[dest['nodo']] = \
                            nodos_demanda_vial.get(dest['nodo'], 0.0) + cuota_trafico

                    camino = dest['camino']
                    for i in range(len(camino) - 1):
                        u, v = camino[i], camino[i + 1]
                        if grafo_modo.has_edge(u, v):
                            trafico_aristas[(u, v)] += cuota_trafico

    trafico_vial = {k: v for k, v in trafico_aristas.items() if G_vial.has_edge(*k)}
    destinos_demanda = [(nodo, dem) for nodo, dem in nodos_demanda_vial.items() if dem > 0]

    incremento_interdiccion, detalle_vulnerabilidad = vulnerabilidad_por_interdiccion(
        G_vial, origenes_viales, destinos_demanda, trafico_vial,
        PARAMETROS["n_aristas_criticas"],
        PARAMETROS["penalizacion_desconexion"], 'weight')
    vulnerabilidad = vulnerabilidad_normalizada(
        incremento_interdiccion, PARAMETROS["lambda_vulnerabilidad"])

    max_cuello_botella = max(trafico_vial.values(), default=0.0)
    if max_cuello_botella <= 0 and len(G_vial.nodes) > 0:
        contar("puertos_sin_reparto_vial", 1)

    denominador_visual = percentil_trafico(trafico_vial.values()) or 1.0

    features_geojson = []
    ranking_calles = {}
    friccion_desconocida = PARAMETROS["friccion_otras"]

    for via in vias:
        try:
            geom_original = via.get('geom_original')
            if not geom_original:
                continue
            nombre_via = via.get('ref_via') or via.get('nombre_via') or 'Desconocida'
            tipo_via = via.get('tipo_via', 'unclassified')

            traficos_segmentos = []
            pesos_segmentos = []
            n_ida = n_vuelta = 0

            if geom_original.geom_type in ('LineString', 'MultiLineString'):
                lineas_iter = ([geom_original] if geom_original.geom_type == 'LineString'
                               else geom_original.geoms)

                for linea in lineas_iter:
                    coords_list = list(linea.coords)
                    for i in range(len(coords_list) - 1):
                        a = (round(coords_list[i][0], 5), round(coords_list[i][1], 5))
                        b = (round(coords_list[i + 1][0], 5), round(coords_list[i + 1][1], 5))

                        G_modo = G_ferro if tipo_via == 'rail' else G_vial
                        tiene_ida = G_modo.has_edge(a, b)
                        tiene_vuelta = G_modo.has_edge(b, a)
                        n_ida += 1 if tiene_ida else 0
                        n_vuelta += 1 if tiene_vuelta else 0

                        traficos_segmentos.append(max(
                            trafico_aristas.get((a, b), 0.0),
                            trafico_aristas.get((b, a), 0.0)))

                        if tiene_ida:
                            pesos_segmentos.append(G_modo[a][b]['weight'])
                        elif tiene_vuelta:
                            pesos_segmentos.append(G_modo[b][a]['weight'])
                        else:
                            pesos_segmentos.append(
                                calcular_distancia_haversine(a[0], a[1], b[0], b[1])
                                * friccion_desconocida)

            trafico_medio_via = intensidad_visual(traficos_segmentos, denominador_visual)
            peso_total_via = sum(pesos_segmentos)
            peso_medio_via = (peso_total_via / len(pesos_segmentos)
                              if pesos_segmentos else 0.1)

            if n_ida and n_vuelta:
                sentido = 'doble'
            elif n_vuelta and not n_ida:
                sentido = 'vuelta'
            elif n_ida:
                sentido = 'ida'
            else:
                sentido = 'ninguno'

            features_geojson.append({
                "type": "Feature",
                "geometry": shapely.geometry.mapping(geom_original),
                "properties": {
                    "trafico": trafico_medio_via,
                    "tipo_via": tipo_via,
                    "nombre_via": nombre_via,
                    "peaje": via.get('peaje'),
                    "peso_logistico_real": peso_medio_via,
                    "peso_logistico_total": peso_total_via,
                    "n_segmentos": len(pesos_segmentos),
                    "sentido": sentido,
                }
            })

            if nombre_via != 'Desconocida' and tipo_via != 'rail':
                ranking_calles.setdefault(nombre_via, []).append(trafico_medio_via)
        except Exception:
            contar("vias_descartadas_geojson")
            continue

    top_calles = "Ninguna identificada"
    if ranking_calles:
        calles_max_trafico = {k: max(v) for k, v in ranking_calles.items()}
        calles_ordenadas = sorted(calles_max_trafico.items(),
                                  key=lambda x: x[1], reverse=True)[:3]
        top_calles = ", ".join([calle[0] for calle in calles_ordenadas])

    puertas_activas = len(nodos_puertas_viales) if len(nodos_puertas_viales) > 0 else 1

    if saturacion_medida is not None:
        saturacion = min(max(float(saturacion_medida), 0.0), 1.0)
        origen_saturacion = "frecuencia_excedencia"
        capacidad_base_red = capacidad_diaria
    else:
        if capacidad_diaria and capacidad_diaria > 0:
            capacidad_base_red = capacidad_diaria
        else:
            capacidad_base_red = puertas_activas * PARAMETROS["capacidad_fallback_por_puerta"]
        bruto = volumen_camion / capacidad_base_red if capacidad_base_red > 0 else 0.0
        saturacion = min(bruto, 1.0)
        origen_saturacion = "cociente_capacidad_constante"

    componente_saturacion = saturacion * PARAMETROS["peso_saturacion"]
    componente_vulnerabilidad = vulnerabilidad * PARAMETROS["peso_cuello_botella"]
    estres_final = round(indice_compuesto(
        saturacion, vulnerabilidad,
        PARAMETROS["peso_saturacion"], PARAMETROS["peso_cuello_botella"]), 2)

    industrias_geojson = []
    for ind in industrias_locales:
        if ind.get('demanda_teus_fija', 0.0) > 0:
            industrias_geojson.append({
                "type": "Feature",
                "geometry": {"type": "Point",
                             "coordinates": [float(ind['centroide_lon']),
                                             float(ind['centroide_lat'])]},
                "properties": {
                    "nombre": ind.get('nombre_zona', 'Desconocido'),
                    "categoria": ind.get('categoria', 'Desconocida'),
                    "atraccion": ind.get('masa_atraccion', 2000),
                    "demanda_teus": round(ind.get('demanda_teus_fija', 0.0), 2)
                }
            })

    todas_las_puertas = list(nodos_puertas_viales.union(nodos_puertas_ferro))

    resumen_estres = {
        "indice_estres": estres_final,
        "saturacion": round(saturacion, 4),
        "vulnerabilidad": round(vulnerabilidad, 4),
        "componente_saturacion": round(componente_saturacion, 3),
        "componente_vulnerabilidad": round(componente_vulnerabilidad, 3),
        "origen_saturacion": origen_saturacion,
        "incremento_interdiccion": round(incremento_interdiccion, 4),
        "detalle_vulnerabilidad": detalle_vulnerabilidad,
        "origen_puertas": origen_puertas,
        "puertas_viales": len(nodos_puertas_viales),
        "cuota_tren_aplicada": cuota_tren,
        "capacidad_base_red": capacidad_base_red,
        "max_trafico_arista": round(max_cuello_botella, 2),
        "volumen_camion": volumen_camion,
    }

    return (resumen_estres, features_geojson, top_calles, industrias_geojson,
            perfil_economico, todas_las_puertas)


def worker_procesar_puerto(datos_puerto, vias, industrias_locales, poligono_puerto, matriz_comtrade):
    nombre_puerto = datos_puerto.get('portname', 'Desconocido')
    try:
        reiniciar_metricas()
        contar("vias_recibidas", len(vias))
        contar("industrias_recibidas", len(industrias_locales))

        cache_alturas, cache_poblacion = cargar_caches_puerto(nombre_puerto)

        print(f"[Core] Iniciando análisis de {nombre_puerto}...", flush=True)

        lat_p = safe_float(datos_puerto.get('lat'))
        lon_p = safe_float(datos_puerto.get('lon'))
        pais = datos_puerto.get('country', 'Desconocido')
        cuota_imp = safe_float(datos_puerto.get('share_country_maritime_import'))
        cuota_exp = safe_float(datos_puerto.get('share_country_maritime_export'))

        vol = calcular_volumenes(datos_puerto)
        buques = vol.get("buques") or {}
        b_container = buques.get("container", 0.0)
        b_roro = buques.get("roro", 0.0)
        b_general = buques.get("general", 0.0)
        b_bulk = buques.get("bulk", 0.0)
        b_tanker = buques.get("tanker", 0.0)
        total_barcos = vol["total_barcos"]
        volumen_diario_movible = vol["volumen_diario_movible"]
        volumen_diario_directo = vol["volumen_diario_directo"]

        resumen, rutas_geojson, top_vias_colapsadas, industrias_geojson, perfil_eco, puertas_reales = calcular_estres_logistico(
            vias, industrias_locales, poligono_puerto, cache_alturas, cache_poblacion,
            volumen_diario_movible, lon_p, lat_p, matriz_comtrade,
            capacidad_diaria=vol.get("capacidad_diaria"),
            saturacion_medida=vol.get("saturacion"),
        )
        estres = resumen["indice_estres"]

        dependencia_nacional_media = (cuota_imp + cuota_exp) / 2.0
        riesgo_macro_score = estres * (dependencia_nacional_media / 100.0)

        ind_1 = datos_puerto.get('industry_top1') or 'Desconocida'
        ind_2 = datos_puerto.get('industry_top2') or 'Desconocida'
        ind_3 = datos_puerto.get('industry_top3') or 'Desconocida'

        industrias_afectadas = [i for i in [ind_1, ind_2, ind_3] if i != 'Desconocida' and i != 'None']
        texto_industrias = ", ".join(industrias_afectadas) if industrias_afectadas else "Múltiples sectores"

        tipos_carga = {"Contenedores": b_container, "RoRo (Vehículos)": b_roro, "Granel Sólido": b_bulk, "Granel Líquido": b_tanker, "Carga General": b_general}
        carga_dominante = max(tipos_carga, key=tipos_carga.get)

        resultado_basico = {
            "id": nombre_puerto, "lat": lat_p, "lng": lon_p,
            "rating_color": "red" if riesgo_macro_score > 2.0 else "yellow" if riesgo_macro_score > 0.5 else "green"
        }

        industria_critica_nombre = "Desconocida"
        if industrias_locales:
            try:
                industria_top = max(industrias_locales, key=lambda x: float(x.get('masa_atraccion', 0)))
                industria_critica_nombre = f"{industria_top.get('nombre_zona', 'Zona Industrial')} ({int(industria_top.get('masa_atraccion', 0))} m2)"
            except:
                pass

        resultado_detalle = {
            "indice_estres": estres,
            "volumen_diario": volumen_diario_movible + volumen_diario_directo,
            "volumen_diario_movible": volumen_diario_movible,
            "capacidad_diaria": vol.get("capacidad_diaria"),
            "unidad_volumen": vol.get("unidad_volumen"),
            "origen_volumen": vol.get("origen_volumen"),
            "perfil_portwatch": vol.get("perfil_portwatch"),
            "saturacion": resumen["saturacion"],
            "vulnerabilidad": resumen["vulnerabilidad"],
            "componente_saturacion": resumen["componente_saturacion"],
            "componente_vulnerabilidad": resumen["componente_vulnerabilidad"],
            "origen_saturacion": resumen["origen_saturacion"],
            "incremento_interdiccion": resumen["incremento_interdiccion"],
            "detalle_vulnerabilidad": resumen["detalle_vulnerabilidad"],
            "origen_puertas": resumen["origen_puertas"],
            "indice_comparable": bool(vol.get("indice_comparable")),
            "volumen_teus": volumen_diario_movible + volumen_diario_directo,
            "vias_totales": len(vias),
            "pais": pais,
            "nodo_industrial_principal": industria_critica_nombre,
            "cuota_import": round(cuota_imp, 2),
            "cuota_export": round(cuota_exp, 2),
            "riesgo_macroeconomico": round(riesgo_macro_score, 2),
            "carga_principal": carga_dominante,
            "porcentaje_container_roro": round(((b_container + b_roro) / total_barcos) * 100, 1),
            "industrias_top": texto_industrias,
            "top_calles_colapsadas": top_vias_colapsadas,
            "riesgo_cuello_botella": "ALTO" if estres > 7 else ("MODERADO" if estres > 4 else "BAJO"),
            "distribucion_comercial_comtrade": perfil_eco,
            "puertas_reales": puertas_reales,
            "overture_release": OVERTURE_RELEASE,
            "fecha_procesamiento_utc": datetime.now(timezone.utc).isoformat(),
            "calidad_datos": log_calidad(nombre_puerto),
        }

        guardar_caches_puerto(nombre_puerto, cache_alturas, cache_poblacion)

        return nombre_puerto, resultado_basico, resultado_detalle, rutas_geojson, industrias_geojson

    except Exception as e:
        print(f"Error en worker para {nombre_puerto}: {str(e)}", flush=True)
        traceback.print_exc()
        return None


def clave_segura(nombre_puerto):
    return "".join([c if c.isalnum() else "_" for c in nombre_puerto])


def registrar_puerto_fallido(nombre_puerto, motivo, talla, indice):
    try:
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=f"{PREFIX_FALLIDOS}{clave_segura(nombre_puerto)}.json",
            Body=json.dumps({
                "puerto": nombre_puerto,
                "motivo": motivo,
                "talla": talla,
                "indice_array": indice,
                "fecha_utc": datetime.now(timezone.utc).isoformat(),
            }),
            ContentType="application/json",
        )
        print(f"Registrado como FALLIDO en s3://{S3_BUCKET}/{PREFIX_FALLIDOS}: "
              f"{nombre_puerto} ({motivo})", flush=True)
    except Exception as e:
        print(f"No se pudo registrar el fallo de {nombre_puerto}: {e}", flush=True)


def limpiar_registro_fallido(nombre_puerto):
    try:
        s3_client.delete_object(
            Bucket=S3_BUCKET,
            Key=f"{PREFIX_FALLIDOS}{clave_segura(nombre_puerto)}.json",
        )
    except Exception:
        pass


def main_aws_batch():
    nombre_puerto = "(sin asignar)"
    talla_asignada = os.getenv("TALLA", "S")
    indice_array = -1
    try:
        print("Arrancando Worker en AWS Batch (Fargate Spot)...")
        indice_array = int(os.getenv("AWS_BATCH_JOB_ARRAY_INDEX", 0))

        obj_puertos = s3_client.get_object(Bucket=S3_BUCKET, Key=f"fuentes_externas/fmi_ports/puertos_{talla_asignada}.json")
        lista_puertos = json.loads(obj_puertos['Body'].read().decode('utf-8'))

        if indice_array >= len(lista_puertos):
            print(f"Índice {indice_array} procesado o fuera de rango. Apagando contenedor de forma segura.")
            return

        mi_puerto = lista_puertos[indice_array]
        nombre_puerto = mi_puerto.get('portname', 'Desconocido')
        print(f"Contenedor Asignado: Procesando {nombre_puerto} (Talla {talla_asignada})")

        matriz_comtrade = cargar_perfiles_comtrade_s3()
        con_duckdb = inicializar_duckdb()

        lat_p = safe_float(mi_puerto.get('lat'))
        lon_p = safe_float(mi_puerto.get('lon'))

        vias, industrias, poligono_puerto = extraer_entorno_overture(
            con_duckdb, lon_p, lat_p, radio_km=PARAMETROS["radio_extraccion_km"])

        if not vias:
            registrar_puerto_fallido(nombre_puerto, "sin_vias_en_overture", talla_asignada, indice_array)
        else:
            res = worker_procesar_puerto(mi_puerto, vias, industrias, poligono_puerto, matriz_comtrade)
            if not res:
                registrar_puerto_fallido(nombre_puerto, "error_en_worker (ver traza en CloudWatch)",
                                         talla_asignada, indice_array)
            else:
                nombre, res_basico, res_detalle, res_geojson, ind_geojson = res

                print(f"Subiendo resultados curados de {nombre} a S3...")

                s3_client.put_object(Bucket=S3_BUCKET, Key=f"{PREFIX_OUTPUT}detalles/{nombre}.json", Body=json.dumps(res_detalle))
                s3_client.put_object(Bucket=S3_BUCKET, Key=f"{PREFIX_OUTPUT}rutas/{nombre}.json", Body=json.dumps({"type": "FeatureCollection", "features": res_geojson}))
                s3_client.put_object(Bucket=S3_BUCKET, Key=f"{PREFIX_INDUSTRIA}{nombre}.json", Body=json.dumps({"type": "FeatureCollection", "features": ind_geojson}))

                s3_client.put_object(Bucket=S3_BUCKET, Key=f"{PREFIX_OUTPUT}basicos/basico_{nombre}.json", Body=json.dumps(res_basico))

                limpiar_registro_fallido(nombre)

        con_duckdb.close()
        print(f"¡Éxito! Finalizado el procesamiento de {nombre_puerto}")

    except Exception as e:
        print(f"Error crítico en el worker: {e}", flush=True)
        traceback.print_exc()
        registrar_puerto_fallido(nombre_puerto, f"error_critico: {e}", talla_asignada, indice_array)
        sys.exit(1)

if __name__ == '__main__':
    main_aws_batch()
