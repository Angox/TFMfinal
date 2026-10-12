import os
import sys

import pytest

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(RAIZ, "etl"))

from generar_resultados import (
    agregar_calidad,
    agregar_sectores,
    construir_filas,
    describir_distribucion,
)


def test_distribucion_basica():
    d = describir_distribucion([1, 2, 3, 4, 5])
    assert d["n"] == 5
    assert d["min"] == 1 and d["max"] == 5
    assert d["mediana"] == 3
    assert d["media"] == 3


def test_distribucion_percentiles_interpolados():
    d = describir_distribucion(list(range(1, 101)))
    assert d["p25"] == pytest.approx(25.75)
    assert d["mediana"] == pytest.approx(50.5)
    assert d["p75"] == pytest.approx(75.25)


def test_distribucion_ignora_no_numericos():
    d = describir_distribucion([1, None, "hola", 3, {}, 5])
    assert d["n"] == 3
    assert d["media"] == 3


def test_distribucion_vacia_no_revienta():
    assert describir_distribucion([])["n"] == 0
    assert describir_distribucion([None, "x"])["n"] == 0


def test_distribucion_de_un_solo_valor():
    d = describir_distribucion([7.5])
    assert d["n"] == 1 and d["mediana"] == 7.5 and d["desviacion"] == 0.0


def test_calidad_suma_contadores_de_todos_los_puertos():
    detalles = [
        {"calidad_datos": {"vias_recibidas": 100, "vias_geometria_invalida": 10,
                           "vias_sin_aristas": 5, "vias_descartadas_pct": 15.0}},
        {"calidad_datos": {"vias_recibidas": 100, "vias_geometria_invalida": 20,
                           "vias_sin_aristas": 0, "vias_descartadas_pct": 20.0}},
    ]
    c = agregar_calidad(detalles)
    assert c["totales"]["vias_recibidas"] == 200
    assert c["vias_descartadas"] == 35
    assert c["vias_descartadas_pct"] == pytest.approx(17.5)


def test_calidad_no_suma_los_porcentajes():
    detalles = [{"calidad_datos": {"vias_recibidas": 10, "vias_geometria_invalida": 1,
                                   "vias_sin_aristas": 0, "vias_descartadas_pct": 10.0}}]
    c = agregar_calidad(detalles)
    assert "vias_descartadas_pct" not in c["totales"]
    assert c["vias_descartadas_pct"] == pytest.approx(10.0)


def test_calidad_tolera_puertos_sin_metricas():
    c = agregar_calidad([{}, {"calidad_datos": None}, {"calidad_datos": "roto"}])
    assert c["puertos_con_metricas"] == 0
    assert c["vias_descartadas_pct"] == 0.0


def test_sectores_promedia_por_puerto():
    detalles = [
        {"distribucion_comercial_comtrade": {"agroalimentario": 0.8, "textil_moda": 0.2}},
        {"distribucion_comercial_comtrade": {"agroalimentario": 0.4, "textil_moda": 0.6}},
    ]
    s = agregar_sectores(detalles)
    assert s["agroalimentario"] == pytest.approx(0.6)
    assert s["textil_moda"] == pytest.approx(0.4)


def test_sectores_se_ordenan_de_mayor_a_menor():
    detalles = [{"distribucion_comercial_comtrade": {"a": 0.1, "b": 0.9}}]
    assert list(agregar_sectores(detalles)) == ["b", "a"]


def test_sectores_sin_datos():
    assert agregar_sectores([{}, {"distribucion_comercial_comtrade": {}}]) == {}


def test_construir_filas_combina_detalle_y_basico():
    filas = construir_filas(
        {"Valencia": {"pais": "Spain", "indice_estres": 7.2, "volumen_diario": 5000}},
        {"Valencia": {"lat": 39.4, "lng": -0.3, "rating_color": "red"}},
    )
    assert len(filas) == 1
    f = filas[0]
    assert f["puerto"] == "Valencia" and f["pais"] == "Spain"
    assert f["lat"] == 39.4 and f["rating_color"] == "red"


def test_construir_filas_acepta_el_nombre_antiguo_del_volumen():
    assert construir_filas({"P": {"volumen_teus": 4321}}, {})[0]["volumen_diario"] == 4321
    assert construir_filas({"P": {"volumen_diario": 99}}, {})[0]["volumen_diario"] == 99


def test_construir_filas_marca_el_origen_del_volumen():
    assert construir_filas({"P": {}}, {})[0]["origen_volumen"] == "desconocido"
    fila = construir_filas({"P": {"origen_volumen": "portwatch_diario",
                                  "capacidad_diaria": 567105.4}}, {})[0]
    assert fila["origen_volumen"] == "portwatch_diario"
    assert fila["capacidad_diaria"] == pytest.approx(567105.4)


def test_construir_filas_acepta_el_nombre_antiguo_del_campo():
    filas = construir_filas({"P": {"vias_totales_km": 1234}}, {})
    assert filas[0]["vias_totales"] == 1234
    filas = construir_filas({"P": {"vias_totales": 99}}, {})
    assert filas[0]["vias_totales"] == 99


def test_construir_filas_sin_basico_no_revienta():
    filas = construir_filas({"P": {"indice_estres": 1.0}}, {})
    assert filas[0]["lat"] is None and filas[0]["rating_color"] is None


def test_construir_filas_cuenta_las_puertas():
    filas = construir_filas({"P": {"puertas_reales": [[1, 2], [3, 4], [5, 6]]}}, {})
    assert filas[0]["puertas_reales"] == 3
    filas = construir_filas({"P": {}}, {})
    assert filas[0]["puertas_reales"] == 0


def test_construir_filas_ordena_por_puerto():
    filas = construir_filas({"Zaragoza": {}, "Algeciras": {}, "Malaga": {}}, {})
    assert [f["puerto"] for f in filas] == ["Algeciras", "Malaga", "Zaragoza"]
