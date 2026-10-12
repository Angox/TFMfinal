import json
import os
import sys
import types
from unittest import mock

import pytest

import networkx
import numpy
import scipy.spatial
import shapely.geometry

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(RAIZ, "etl"))

from reconstruccion import (
    construir_grafo_desde_geojson,
    peso_por_segmento,
    podar_componente_principal,
)
from grafos import arbol_de_caminos

from test_motor_estres import (
    _corredor_redundante,
    _corredor_unico,
    industria,
    via,
)


def _modulo_falso(nombre, atributos=None):
    m = types.ModuleType(nombre)
    for k, v in (atributos or {}).items():
        setattr(m, k, v)
    return m


@pytest.fixture(scope="module")
def motor():
    pesados = {
        "boto3": _modulo_falso("boto3", {"client": lambda *a, **k: mock.MagicMock()}),
        "rasterio": mock.MagicMock(),
        "rasterio.session": _modulo_falso("rasterio.session", {"AWSSession": mock.MagicMock()}),
        "rasterio.windows": _modulo_falso("rasterio.windows", {"from_bounds": mock.MagicMock()}),
        "rasterio.transform": _modulo_falso("rasterio.transform", {"rowcol": mock.MagicMock()}),
        "pycountry": mock.MagicMock(),
        "reverse_geocoder": mock.MagicMock(),
        "duckdb": mock.MagicMock(),
        "requests": _modulo_falso("requests", {"get": mock.MagicMock()}),
    }
    os.environ.setdefault("S3_BUCKET_NAME", "bucket-de-pruebas")
    os.environ.setdefault("AWS_REGION", "us-west-2")
    with mock.patch.dict(sys.modules, pesados):
        import etl_procesamiento
        yield etl_procesamiento


@pytest.fixture(autouse=True)
def _entorno(motor, monkeypatch):
    motor.aplicar_parametros()
    motor.reiniciar_metricas()
    monkeypatch.setattr(motor, "obtener_iso3", lambda lat, lon: "ESP")

    def _caches(vias, cache_alturas, cache_poblacion, iso3_puerto=None):
        for v in vias:
            geom = shapely.geometry.shape(json.loads(v["geometria_geojson"]))
            v["geom_original"] = geom
            v["geom_simplificada"] = geom

    monkeypatch.setattr(motor, "precalcular_caches_en_bloque", _caches)
    yield
    motor.aplicar_parametros()


def _motor_y_reconstruido(motor, vias, industrias, **kw):
    resumen, geojson, _t, _i, _perfil, _p = motor.calcular_estres_logistico(
        vias, list(industrias), [], {}, {}, 1000.0, 0.0, 0.0, {}, **kw)
    grafo, geometrias, nodos = construir_grafo_desde_geojson(geojson)
    return resumen, geojson, grafo, geometrias, nodos


def test_recorrer_una_via_cuesta_lo_mismo_en_los_dos_grafos(motor):
    _r, geojson, grafo, _geo, _n = _motor_y_reconstruido(
        motor, _corredor_unico(), [industria(0.03, 0.0005)])

    props = geojson[0]["properties"]
    n = props["n_segmentos"]
    peso = peso_por_segmento(props, n)

    assert peso * n == pytest.approx(props["peso_logistico_total"])


def test_una_via_larga_no_sale_mas_barata_que_una_corta(motor):
    corta = via("Corta", [(0.0, 0.0), (0.01, 0.0)], tipo="primary")
    larga = via("Larga", [(0.01, 0.0), (0.02, 0.0), (0.03, 0.0), (0.04, 0.0)],
                tipo="primary")

    _r, geojson, _g, _geo, _n = _motor_y_reconstruido(
        motor, [corta, larga], [industria(0.04, 0.0005)])
    props = {f["properties"]["nombre_via"]: f["properties"] for f in geojson}

    coste_corta = peso_por_segmento(props["Corta"], props["Corta"]["n_segmentos"]) \
        * props["Corta"]["n_segmentos"]
    coste_larga = peso_por_segmento(props["Larga"], props["Larga"]["n_segmentos"]) \
        * props["Larga"]["n_segmentos"]

    assert coste_larga == pytest.approx(coste_corta * 3, rel=0.05)

    defecto_corta = (props["Corta"]["peso_logistico_real"]
                     / props["Corta"]["n_segmentos"]) * props["Corta"]["n_segmentos"]
    defecto_larga = (props["Larga"]["peso_logistico_real"]
                     / props["Larga"]["n_segmentos"]) * props["Larga"]["n_segmentos"]
    assert defecto_corta == pytest.approx(defecto_larga, rel=0.05)


def test_el_camino_minimo_reconstruido_cuesta_lo_mismo_que_el_del_motor(motor):
    vias = _corredor_unico()
    resumen, geojson, grafo, _geo, _n = _motor_y_reconstruido(
        motor, vias, [industria(0.03, 0.0005)])

    origen = (0.0, 0.0)
    destino = (0.03, 0.0)
    assert origen in grafo and destino in grafo

    distancias, _p = arbol_de_caminos(grafo, [origen], "weight")
    coste_reconstruido = distancias[destino]
    coste_publicado = geojson[0]["properties"]["peso_logistico_total"]

    assert coste_reconstruido == pytest.approx(coste_publicado, rel=1e-6)


def test_un_sentido_unico_no_se_convierte_en_doble(motor):
    vias = _corredor_unico()
    vias[0]["oneway"] = "yes"
    _r, _g, grafo, _geo, _n = _motor_y_reconstruido(
        motor, vias, [industria(0.03, 0.0005)])

    assert grafo.has_edge((0.0, 0.0), (0.01, 0.0))
    assert not grafo.has_edge((0.01, 0.0), (0.0, 0.0))


def test_una_via_de_doble_sentido_conserva_los_dos_arcos(motor):
    _r, _g, grafo, _geo, _n = _motor_y_reconstruido(
        motor, _corredor_unico(), [industria(0.03, 0.0005)])

    assert grafo.has_edge((0.0, 0.0), (0.01, 0.0))
    assert grafo.has_edge((0.01, 0.0), (0.0, 0.0))


def test_el_ferrocarril_no_entra_en_el_grafo_del_camion(motor):
    coords = [(0.0005 * k, 0.0005) for k in range(60)]
    vias = _corredor_unico() + [via("Ramal", coords, tipo="rail")]

    _r, _g, grafo, _geo, _n = _motor_y_reconstruido(
        motor, vias, [industria(0.03, 0.0005)])

    tipos = {d.get("tipo_via") for _u, _v, d in grafo.edges(data=True)}
    assert "rail" not in tipos


def test_se_puede_pedir_el_ferrocarril_explicitamente(motor):
    coords = [(0.0005 * k, 0.0005) for k in range(60)]
    vias = _corredor_unico() + [via("Ramal", coords, tipo="rail")]

    _r, geojson, _g, _geo, _n = _motor_y_reconstruido(
        motor, vias, [industria(0.03, 0.0005)])
    grafo, _geo2, _n2 = construir_grafo_desde_geojson(
        geojson, incluir_ferrocarril=True)

    tipos = {d.get("tipo_via") for _u, _v, d in grafo.edges(data=True)}
    assert "rail" in tipos


def test_hay_exactamente_una_geometria_por_feature(motor):
    _r, geojson, _g, geometrias, _n = _motor_y_reconstruido(
        motor, _corredor_redundante(), [industria(0.03, 0.0005)])
    assert len(geometrias) == len(geojson)


def test_una_geometria_rota_no_desalinea_los_indices():
    features = [
        {"geometry": {"type": "LineString", "coordinates": [[0, 0], [0.01, 0]]},
         "properties": {"nombre_via": "A", "tipo_via": "primary",
                        "peso_logistico_total": 1.0, "n_segmentos": 1,
                        "sentido": "doble"}},
        {"geometry": {"type": "Disparate", "coordinates": "roto"},
         "properties": {"nombre_via": "B"}},
        {"geometry": {"type": "LineString", "coordinates": [[1, 1], [1.01, 1]]},
         "properties": {"nombre_via": "C", "tipo_via": "primary",
                        "peso_logistico_total": 2.0, "n_segmentos": 1,
                        "sentido": "doble"}},
    ]
    grafo, geometrias, _n = construir_grafo_desde_geojson(features)

    assert len(geometrias) == 3
    assert geometrias[1] is None
    assert grafo[(1.0, 1.0)][(1.01, 1.0)]["feature_idx"] == 2


def test_la_poda_se_queda_con_la_componente_mayor():
    features = [
        {"geometry": {"type": "LineString",
                      "coordinates": [[0, 0], [0.01, 0], [0.02, 0]]},
         "properties": {"tipo_via": "primary", "peso_logistico_total": 2.0,
                        "n_segmentos": 2, "sentido": "doble"}},
        {"geometry": {"type": "LineString", "coordinates": [[5, 5], [5.01, 5]]},
         "properties": {"tipo_via": "primary", "peso_logistico_total": 1.0,
                        "n_segmentos": 1, "sentido": "doble"}},
    ]
    grafo, _geo, _n = construir_grafo_desde_geojson(features)
    podado, nodos = podar_componente_principal(grafo)

    assert (0.0, 0.0) in nodos
    assert (5.0, 5.0) not in nodos
    assert len(podado.nodes) == 3


def test_podar_un_grafo_vacio_no_revienta():
    import networkx as nx
    podado, nodos = podar_componente_principal(nx.DiGraph())
    assert len(podado.nodes) == 0
    assert nodos == set()


def test_los_datos_antiguos_sin_el_total_se_reconstruyen_bien():
    props = {"peso_logistico_real": 4.0}
    assert peso_por_segmento(props, 5) == pytest.approx(4.0)
    assert peso_por_segmento(props, 5) * 5 == pytest.approx(20.0)


def test_el_total_manda_sobre_la_media_si_estan_los_dos():
    props = {"peso_logistico_real": 4.0, "peso_logistico_total": 30.0}
    assert peso_por_segmento(props, 5) == pytest.approx(6.0)


def test_sin_segmentos_no_divide_por_cero():
    assert peso_por_segmento({"peso_logistico_total": 10.0}, 0) == 0.0


def _indice_como_lo_hace_la_api(detalle, multiplicador=1.0, fraccion_aislada=0.0):
    from calculos import (estres_con_aislamiento, indice_compuesto,
                          saturacion_con_shock)
    saturacion = saturacion_con_shock(detalle["saturacion"], multiplicador)
    red = indice_compuesto(saturacion, detalle["vulnerabilidad"], 5.0, 5.0)
    return estres_con_aislamiento(red, fraccion_aislada)


def test_sin_corte_y_sin_shock_el_simulador_da_el_mismo_indice_que_el_etl(motor):
    resumen, _g, _grafo, _geo, _n = _motor_y_reconstruido(
        motor, _corredor_redundante(), [industria(0.03, 0.0005)],
        saturacion_medida=0.42)

    assert _indice_como_lo_hace_la_api(resumen) == pytest.approx(
        resumen["indice_estres"], abs=0.01)


def test_el_etl_publica_las_dos_componentes_que_el_simulador_necesita(motor):
    resumen, _g, _grafo, _geo, _n = _motor_y_reconstruido(
        motor, _corredor_unico(), [industria(0.03, 0.0005)], saturacion_medida=0.3)

    for campo in ("saturacion", "vulnerabilidad", "componente_saturacion",
                  "componente_vulnerabilidad", "origen_saturacion", "origen_puertas"):
        assert campo in resumen


def test_un_shock_uniforme_no_llega_a_duplicar_el_indice(motor):
    resumen, _g, _grafo, _geo, _n = _motor_y_reconstruido(
        motor, _corredor_redundante(), [industria(0.03, 0.0005)],
        saturacion_medida=0.3)

    base = resumen["indice_estres"]
    correcto = _indice_como_lo_hace_la_api(resumen, multiplicador=2.0)
    incorrecto = min(base * 2.0, 10.0)

    assert correcto < incorrecto
    assert correcto > base


def test_aislar_toda_la_demanda_lleva_el_indice_al_maximo(motor):
    resumen, _g, _grafo, _geo, _n = _motor_y_reconstruido(
        motor, _corredor_unico(), [industria(0.03, 0.0005)], saturacion_medida=0.1)
    assert _indice_como_lo_hace_la_api(resumen, fraccion_aislada=1.0) == pytest.approx(10.0)
