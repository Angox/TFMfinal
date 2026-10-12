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
def _entorno_controlado(motor, monkeypatch):
    motor.aplicar_parametros()
    motor.reiniciar_metricas()
    monkeypatch.setattr(motor, "obtener_iso3", lambda lat, lon: "ESP")

    def _caches_falsas(vias, cache_alturas, cache_poblacion, iso3_puerto=None):
        for via in vias:
            geom = shapely.geometry.shape(json.loads(via["geometria_geojson"]))
            via["geom_original"] = geom
            via["geom_simplificada"] = geom

    monkeypatch.setattr(motor, "precalcular_caches_en_bloque", _caches_falsas)
    yield
    motor.aplicar_parametros()


def via(nombre, coords, tipo="secondary", **extra):
    datos = {
        "id": nombre,
        "nombre_via": nombre,
        "tipo_via": tipo,
        "geometria_geojson": json.dumps(
            {"type": "LineString", "coordinates": [list(c) for c in coords]}),
        "carriles": "0",
        "maxweight": "",
        "maxweight_unidad": "",
        "tipo_superficie": "paved",
        "hgv_restringido": "no",
        "peaje": "no",
        "oneway": "no",
        "layer": "0",
    }
    datos.update(extra)
    return datos


def industria(lon, lat, masa=5000.0, nombre="Nave"):
    return {
        "nombre_zona": nombre,
        "categoria": "warehouse",
        "centroide_lon": lon,
        "centroide_lat": lat,
        "masa_atraccion": masa,
    }


def ejecutar(motor, vias, industrias, volumen=1000.0, **kwargs):
    resumen, geojson, top, ind_geo, _perfil, puertas = motor.calcular_estres_logistico(
        vias, list(industrias), [], {}, {}, volumen, 0.0, 0.0, {}, **kwargs)
    return resumen, geojson, top, ind_geo, puertas


def _corredor_unico():
    return [via("Corredor", [(0.0, 0.0), (0.01, 0.0), (0.02, 0.0), (0.03, 0.0)],
               tipo="primary")]


def _corredor_redundante():
    return [
        via("Corredor", [(0.0, 0.0), (0.01, 0.0), (0.02, 0.0), (0.03, 0.0)],
            tipo="primary"),
        via("Ronda", [(0.0, 0.0), (0.01, 0.01), (0.02, 0.01), (0.03, 0.0)],
            tipo="primary"),
    ]


def test_hay_puertas_aunque_overture_no_de_el_poligono(motor):
    resumen, _g, _t, _i, puertas = ejecutar(
        motor, _corredor_unico(), [industria(0.03, 0.0005)])

    assert resumen["origen_puertas"] == "respaldo_radio"
    assert resumen["puertas_viales"] > 0
    assert len(puertas) > 0


def test_el_poligono_del_puerto_tiene_prioridad_sobre_el_respaldo(motor):
    recinto = {
        "type": "Polygon",
        "coordinates": [[[-0.005, -0.005], [0.005, -0.005],
                         [0.005, 0.005], [-0.005, 0.005], [-0.005, -0.005]]],
    }
    poligono = [{"geometria_geojson": json.dumps(recinto)}]

    resumen, _g, _t, _i, _perfil, _p = motor.calcular_estres_logistico(
        _corredor_unico(), [industria(0.03, 0.0005)], poligono,
        {}, {}, 1000.0, 0.0, 0.0, {})

    assert resumen["origen_puertas"] == "perimetro_overture"
    assert resumen["puertas_viales"] > 0


def test_el_respaldo_no_coge_puertas_fuera_del_radio(motor):
    lejana = [via("Lejana", [(0.4, 0.4), (0.41, 0.4), (0.42, 0.4)], tipo="primary")]
    resumen, _g, _t, _i, _p = ejecutar(motor, lejana, [industria(0.42, 0.4005)])

    assert resumen["origen_puertas"] == "nodo_artificial"
    assert resumen["puertas_viales"] == 0


def test_una_red_sin_alternativa_es_mas_vulnerable_que_una_redundante(motor):
    unico, _g, _t, _i, _p = ejecutar(
        motor, _corredor_unico(), [industria(0.03, 0.0005)])
    redundante, _g2, _t2, _i2, _p2 = ejecutar(
        motor, _corredor_redundante(), [industria(0.03, 0.0005)])

    assert unico["vulnerabilidad"] > redundante["vulnerabilidad"]
    assert unico["vulnerabilidad"] > 0.0


def test_cortar_el_unico_paso_desconecta_toda_la_demanda(motor):
    resumen, _g, _t, _i, _p = ejecutar(
        motor, _corredor_unico(), [industria(0.03, 0.0005)])

    detalle = resumen["detalle_vulnerabilidad"]
    assert detalle["fraccion_demanda_desconectada"] == pytest.approx(1.0)
    assert detalle["arista_critica"] is not None


def test_la_vulnerabilidad_esta_acotada_en_cero_uno(motor):
    for vias, inds in ((_corredor_unico(), [industria(0.03, 0.0005)]),
                       (_corredor_redundante(), [industria(0.03, 0.0005)]),
                       (_corredor_unico(), [])):
        resumen, _g, _t, _i, _p = ejecutar(motor, vias, inds)
        assert 0.0 <= resumen["vulnerabilidad"] <= 1.0


def test_sin_industrias_no_hay_vulnerabilidad_que_medir(motor):
    resumen, _g, _t, _i, _p = ejecutar(motor, _corredor_unico(), [])
    assert resumen["vulnerabilidad"] == 0.0


def test_desactivar_la_interdiccion_anula_el_termino(motor):
    motor.aplicar_parametros({"n_aristas_criticas": 0})
    resumen, _g, _t, _i, _p = ejecutar(
        motor, _corredor_unico(), [industria(0.03, 0.0005)])
    assert resumen["vulnerabilidad"] == 0.0


def test_el_corte_afecta_a_los_dos_sentidos_de_la_calzada(motor):
    resumen, _g, _t, _i, _p = ejecutar(
        motor, _corredor_unico(), [industria(0.03, 0.0005)])
    assert resumen["incremento_interdiccion"] > 0.0


def _red_dos_calidades():
    return [
        via("Autopista", [(0.0, 0.0), (0.01, 0.005), (0.02, 0.0)], tipo="motorway"),
        via("Terciaria", [(0.0, 0.0), (0.01, -0.005), (0.02, 0.0)], tipo="tertiary"),
    ]


def _trafico_por_calle(geojson):
    return {f["properties"]["nombre_via"]: f["properties"]["trafico"]
            for f in geojson}


def test_el_trafico_prefiere_la_autopista(motor):
    _r, geojson, _t, _i, _p = ejecutar(
        motor, _red_dos_calidades(), [industria(0.02, 0.0)])
    trafico = _trafico_por_calle(geojson)
    assert trafico["Autopista"] > trafico["Terciaria"]


def test_invertir_la_jerarquia_viaria_invierte_el_reparto(motor):
    motor.aplicar_parametros({"friccion_autopista": 9.0, "friccion_secundaria": 0.2})
    _r, geojson, _t, _i, _p = ejecutar(
        motor, _red_dos_calidades(), [industria(0.02, 0.0)])
    trafico = _trafico_por_calle(geojson)
    assert trafico["Terciaria"] > trafico["Autopista"]


def test_una_via_prohibida_a_pesados_no_entra_en_el_grafo(motor):
    vias = _corredor_unico()
    vias[0]["hgv_restringido"] = "yes"
    _r, geojson, _t, _i, _p = ejecutar(motor, vias, [industria(0.03, 0.0005)])

    assert _trafico_por_calle(geojson)["Corredor"] == 0
    assert motor.METRICAS.get("vias_prohibidas_hgv", 0) == 1


def test_el_limite_de_peso_se_lee_con_su_unidad(motor):
    vias = _corredor_unico()
    vias[0]["maxweight"] = "80000"
    vias[0]["maxweight_unidad"] = "lbs"
    ejecutar(motor, vias, [industria(0.03, 0.0005)])
    assert motor.METRICAS.get("vias_con_tonelaje_limitado", 0) == 1


def test_un_limite_en_toneladas_por_encima_del_umbral_no_penaliza(motor):
    vias = _corredor_unico()
    vias[0]["maxweight"] = "60"
    vias[0]["maxweight_unidad"] = "t"
    ejecutar(motor, vias, [industria(0.03, 0.0005)])
    assert motor.METRICAS.get("vias_con_tonelaje_limitado", 0) == 0


def test_la_saturacion_medida_se_usa_tal_cual(motor):
    resumen, _g, _t, _i, _p = ejecutar(
        motor, _corredor_unico(), [industria(0.03, 0.0005)],
        capacidad_diaria=5000.0, saturacion_medida=0.4)

    assert resumen["saturacion"] == pytest.approx(0.4)
    assert resumen["origen_saturacion"] == "frecuencia_excedencia"
    assert resumen["componente_saturacion"] == pytest.approx(2.0)


def test_sin_saturacion_medida_se_usa_el_cociente_acotado(motor):
    resumen, _g, _t, _i, _p = ejecutar(
        motor, _corredor_unico(), [industria(0.03, 0.0005)],
        volumen=10_000_000.0)

    assert resumen["saturacion"] == pytest.approx(1.0)
    assert resumen["origen_saturacion"] == "cociente_capacidad_constante"


def test_el_indice_es_la_suma_ponderada_de_sus_dos_componentes(motor):
    resumen, _g, _t, _i, _p = ejecutar(
        motor, _corredor_redundante(), [industria(0.03, 0.0005)],
        saturacion_medida=0.3)

    esperado = round(resumen["componente_saturacion"]
                     + resumen["componente_vulnerabilidad"], 2)
    assert resumen["indice_estres"] == pytest.approx(esperado, abs=0.01)


@pytest.mark.parametrize("saturacion", [0.0, 0.25, 0.5, 1.0])
def test_el_indice_nunca_se_sale_del_rango(motor, saturacion):
    resumen, _g, _t, _i, _p = ejecutar(
        motor, _corredor_unico(), [industria(0.03, 0.0005)],
        saturacion_medida=saturacion)
    assert 0.0 <= resumen["indice_estres"] <= 10.0


def test_el_indice_crece_con_la_saturacion(motor):
    indices = []
    for sat in (0.0, 0.3, 0.6, 1.0):
        resumen, _g, _t, _i, _p = ejecutar(
            motor, _corredor_redundante(), [industria(0.03, 0.0005)],
            saturacion_medida=sat)
        indices.append(resumen["indice_estres"])
    assert indices == sorted(indices)
    assert indices[0] < indices[-1]


def test_el_geojson_publica_el_coste_total_de_cada_via(motor):
    _r, geojson, _t, _i, _p = ejecutar(
        motor, _corredor_unico(), [industria(0.03, 0.0005)])
    props = geojson[0]["properties"]

    assert props["n_segmentos"] == 3
    assert props["peso_logistico_total"] == pytest.approx(
        props["peso_logistico_real"] * props["n_segmentos"])


def test_el_geojson_declara_el_sentido_de_circulacion(motor):
    vias = _corredor_unico()
    vias[0]["oneway"] = "yes"
    _r, geojson, _t, _i, _p = ejecutar(motor, vias, [industria(0.03, 0.0005)])

    assert geojson[0]["properties"]["sentido"] == "ida"


def test_una_via_de_doble_sentido_se_declara_como_tal(motor):
    _r, geojson, _t, _i, _p = ejecutar(
        motor, _corredor_unico(), [industria(0.03, 0.0005)])
    assert geojson[0]["properties"]["sentido"] == "doble"


def test_la_poda_a_la_componente_mayor_queda_registrada(motor):
    vias = _corredor_unico() + [
        via("Isla", [(0.3, 0.3), (0.31, 0.3)], tipo="secondary")]
    ejecutar(motor, vias, [industria(0.03, 0.0005)])

    assert motor.METRICAS["nodos_vial_antes_poda"] > motor.METRICAS["nodos_vial_tras_poda"]


def _red_intermodal():
    vias = [via("Corredor", [(0.0, 0.0), (0.01, 0.0), (0.02, 0.0), (0.03, 0.0)],
                tipo="primary")]
    coords = [(0.0005 * k, 0.0005) for k in range(60)]
    vias.append(via("Ramal", coords, tipo="rail"))
    return vias


def test_el_ferrocarril_encuentra_sus_puertas_por_proximidad(motor):
    resumen, _g, _t, _i, _p = ejecutar(
        motor, _red_intermodal(), [industria(0.03, 0.0005)])

    assert resumen["cuota_tren_aplicada"] == pytest.approx(
        motor.PARAMETROS["cuota_tren"])


def test_sin_ferrocarril_la_cuota_es_cero(motor):
    resumen, _g, _t, _i, _p = ejecutar(
        motor, _corredor_unico(), [industria(0.03, 0.0005)])
    assert resumen["cuota_tren_aplicada"] == 0.0


def test_el_tren_no_comparte_grafo_con_el_camion(motor):
    _r, geojson, _t, _i, _p = ejecutar(
        motor, _red_intermodal(), [industria(0.03, 0.0005)])
    tipos = {f["properties"]["nombre_via"]: f["properties"]["tipo_via"]
             for f in geojson}
    assert tipos["Ramal"] == "rail"
    assert tipos["Corredor"] == "primary"


def _hinterland_disperso():
    vias = [via("Corredor",
                [(0.0, 0.0), (0.005, 0.0), (0.01, 0.0), (0.02, 0.0),
                 (0.04, 0.0), (0.08, 0.0), (0.15, 0.0)], tipo="primary")]
    industrias = [industria(0.005, 0.0001, nombre="Pegada"),
                  industria(0.02, 0.0001, nombre="Cerca"),
                  industria(0.08, 0.0001, nombre="Media"),
                  industria(0.15, 0.0001, nombre="Lejos")]
    return vias, industrias


def _demanda_por_industria(ind_geojson):
    return {f["properties"]["nombre"]: f["properties"]["demanda_teus"]
            for f in ind_geojson}


def test_la_exponencial_no_deja_el_hinterland_sin_demanda(motor):
    vias, industrias = _hinterland_disperso()
    _r, _g, _t, ind_exp, _p = ejecutar(motor, vias, industrias)
    reparto_exp = _demanda_por_industria(ind_exp)

    motor.aplicar_parametros({"funcion_disuasion": "potencia"})
    vias, industrias = _hinterland_disperso()
    _r, _g, _t, ind_pot, _p = ejecutar(motor, vias, industrias)
    reparto_pot = _demanda_por_industria(ind_pot)

    total_exp = sum(reparto_exp.values())
    total_pot = sum(reparto_pot.values())

    assert reparto_pot["Pegada"] / total_pot > reparto_exp["Pegada"] / total_exp
    assert reparto_exp["Lejos"] / total_exp > reparto_pot["Lejos"] / total_pot


def test_el_reparto_conserva_la_carga_total(motor):
    vias, industrias = _hinterland_disperso()
    _r, _g, _t, ind_geo, _p = ejecutar(motor, vias, industrias, volumen=5000.0)
    assert sum(_demanda_por_industria(ind_geo).values()) == pytest.approx(5000.0, rel=1e-6)


def test_beta_cero_reparte_solo_por_masa(motor):
    motor.aplicar_parametros({"beta_disuasion": 0.0})
    vias = [via("Corredor", [(0.0, 0.0), (0.02, 0.0), (0.15, 0.0)], tipo="primary")]
    industrias = [industria(0.02, 0.0001, masa=1000.0, nombre="Cerca"),
                  industria(0.15, 0.0001, masa=1000.0, nombre="Lejos")]
    _r, _g, _t, ind_geo, _p = ejecutar(motor, vias, industrias)
    reparto = _demanda_por_industria(ind_geo)
    assert reparto["Cerca"] == pytest.approx(reparto["Lejos"], rel=1e-6)


def test_la_cuota_ferroviaria_alivia_la_saturacion_estimada(motor):
    vias, industrias = _hinterland_disperso()
    coords = [(0.0005 * k, 0.0005) for k in range(60)]
    vias = vias + [via("Ramal", coords, tipo="rail")]

    con_tren, _g, _t, _i, _p = ejecutar(motor, list(vias), industrias, volumen=6000.0)

    motor.aplicar_parametros({"cuota_tren": 0.0})
    vias2, industrias2 = _hinterland_disperso()
    vias2 = vias2 + [via("Ramal", coords, tipo="rail")]
    sin_tren, _g, _t, _i, _p = ejecutar(motor, vias2, industrias2, volumen=6000.0)

    assert con_tren["cuota_tren_aplicada"] > 0
    assert sin_tren["cuota_tren_aplicada"] == 0
    assert con_tren["saturacion"] < sin_tren["saturacion"]
