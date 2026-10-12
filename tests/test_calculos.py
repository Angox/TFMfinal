import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "etl"))

from calculos import (
    RADIO_TIERRA_KM,
    calcular_distancia_haversine,
    clasificar_por_categoria_overture,
    clasificar_por_codigo_hs,
    ruta_tesela_dem,
    safe_float,
)


@pytest.mark.parametrize("entrada,esperado", [
    (1.5, 1.5),
    ("1.5", 1.5),
    (0, 0.0),
    ("0", 0.0),
    (-3, -3.0),
    ("  2.75  ", 2.75),
])
def test_safe_float_convierte_valores_validos(entrada, esperado):
    assert safe_float(entrada) == pytest.approx(esperado)


@pytest.mark.parametrize("entrada", [
    None, "", "   ", "None", "none", "NaN", "nan", "null", "NULL", "hola", [], {},
])
def test_safe_float_devuelve_el_defecto_con_nulos(entrada):
    assert safe_float(entrada) == 0.0


def test_safe_float_respeta_el_defecto_indicado():
    assert safe_float(None, default=1000.0) == 1000.0
    assert safe_float("nan", default=-1.0) == -1.0


def test_haversine_distancia_cero():
    assert calcular_distancia_haversine(-3.70, 40.42, -3.70, 40.42) == pytest.approx(0.0)


def test_haversine_es_simetrica():
    ida = calcular_distancia_haversine(-3.70, 40.42, 2.17, 41.39)
    vuelta = calcular_distancia_haversine(2.17, 41.39, -3.70, 40.42)
    assert ida == pytest.approx(vuelta)


def test_haversine_madrid_barcelona():
    d = calcular_distancia_haversine(-3.7038, 40.4168, 2.1734, 41.3851)
    assert d == pytest.approx(505, abs=10)


def test_haversine_un_grado_de_latitud_en_el_ecuador():
    d = calcular_distancia_haversine(0.0, 0.0, 0.0, 1.0)
    assert d == pytest.approx(math.pi * RADIO_TIERRA_KM / 180.0, rel=1e-9)


def test_haversine_antipodas():
    d = calcular_distancia_haversine(0.0, 0.0, 180.0, 0.0)
    assert d == pytest.approx(math.pi * RADIO_TIERRA_KM, rel=1e-6)


def test_haversine_cruza_el_antimeridiano_sin_romperse():
    d = calcular_distancia_haversine(171.0, 0.0, -179.0, 0.0)
    assert d == pytest.approx(10 * math.pi * RADIO_TIERRA_KM / 180.0, rel=1e-6)


MAPEO_PRUEBA = {
    "automocion_transporte": {
        "hs_codes": ["87", "86"],
        "overture_cats": ["car_factory", "automotive_repair"],
    },
    "agroalimentario": {
        "hs_codes": [str(i).zfill(2) for i in range(1, 25)],
        "overture_cats": ["food_processing", "bakery"],
    },
    "generico_logistica": {
        "hs_codes": [],
        "overture_cats": ["warehouse", "logistics"],
    },
}


@pytest.mark.parametrize("categoria,esperado", [
    ("car_factory", "automocion_transporte"),
    ("CAR_FACTORY", "automocion_transporte"),
    ("industrial_car_factory_zone", "automocion_transporte"),
    ("food_processing", "agroalimentario"),
    ("warehouse", "generico_logistica"),
])
def test_clasificacion_overture_asigna_el_sector(categoria, esperado):
    assert clasificar_por_categoria_overture(categoria, MAPEO_PRUEBA) == esperado


@pytest.mark.parametrize("categoria", [None, "", "peluqueria", "cosa_rara"])
def test_clasificacion_overture_sin_coincidencia(categoria):
    assert clasificar_por_categoria_overture(categoria, MAPEO_PRUEBA) is None


def test_clasificacion_overture_respeta_el_orden_de_declaracion():
    assert clasificar_por_categoria_overture(
        "car_factory_warehouse", MAPEO_PRUEBA
    ) == "automocion_transporte"


@pytest.mark.parametrize("codigo,esperado", [
    ("87", "automocion_transporte"),
    ("86", "automocion_transporte"),
    ("01", "agroalimentario"),
    ("24", "agroalimentario"),
    (87, "automocion_transporte"),
])
def test_clasificacion_hs_asigna_el_sector(codigo, esperado):
    assert clasificar_por_codigo_hs(codigo, MAPEO_PRUEBA) == esperado


def test_clasificacion_hs_normaliza_el_cero_a_la_izquierda():
    assert clasificar_por_codigo_hs("1", MAPEO_PRUEBA) == "agroalimentario"
    assert clasificar_por_codigo_hs(1, MAPEO_PRUEBA) == "agroalimentario"


@pytest.mark.parametrize("codigo", [None, "99", "TOTAL", ""])
def test_clasificacion_hs_cae_al_generico(codigo):
    assert clasificar_por_codigo_hs(codigo, MAPEO_PRUEBA) == "generico_logistica"


def test_clasificacion_hs_25_no_es_agroalimentario():
    assert clasificar_por_codigo_hs("25", MAPEO_PRUEBA) == "generico_logistica"


def test_ruta_dem_contra_teselas_reales_del_bucket():
    assert "Copernicus_DSM_COG_10_S34_00_W059_00_DEM" in ruta_tesela_dem(-33.88, -58.41)
    assert "Copernicus_DSM_COG_10_N44_00_E008_00_DEM" in ruta_tesela_dem(44.41, 8.93)


@pytest.mark.parametrize("lat,lon,esperado", [
    (0.5, 0.5, "N00_00_E000"),
    (44.41, 8.93, "N44_00_E008"),
    (60.0, 120.0, "N60_00_E120"),
    (-0.5, -0.5, "S01_00_W001"),
    (-33.88, -58.41, "S34_00_W059"),
    (-1.0, -1.0, "S01_00_W001"),
])
def test_ruta_dem_usa_floor_y_no_truncamiento(lat, lon, esperado):
    assert esperado in ruta_tesela_dem(lat, lon)


def test_ruta_dem_rellena_con_ceros_a_la_izquierda():
    r = ruta_tesela_dem(5.0, 7.0)
    assert "N05_00_E007" in r


def test_ruta_dem_repite_el_nombre_en_carpeta_y_fichero():
    r = ruta_tesela_dem(44.41, 8.93)
    nombre = r.rsplit("/", 1)[-1][:-4]
    assert r == f"s3://copernicus-dem-30m/{nombre}/{nombre}.tif"


def test_ruta_dem_admite_otro_bucket():
    assert ruta_tesela_dem(0.0, 0.0, bucket="mi-copia").startswith("s3://mi-copia/")
