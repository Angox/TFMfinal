import os
import random
import sys
import types
from unittest import mock

import pytest

import networkx
import shapely.geometry

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(RAIZ, "app"))

from reconstruccion import (
    construir_grafo_desde_geojson,
    podar_componente_principal,
)

N = 26
PASO = 0.004
LON0, LAT0 = 8.90, 44.40
ARTERIAS = (10, 18)
PUERTA = (10, 0)


def _punto(x, y):
    return [round(LON0 + x * PASO, 6), round(LAT0 + y * PASO, 6)]


def _cualquiera(nombre):
    m = types.ModuleType(nombre)
    m.__getattr__ = lambda _: mock.MagicMock()
    return m


DEPENDENCIAS_SUSTITUIDAS = (
    "fastapi", "fastapi.concurrency", "fastapi.staticfiles", "fastapi.responses",
    "fastapi.middleware", "fastapi.middleware.gzip", "starlette",
    "starlette.websockets", "boto3", "firebase_admin", "google",
    "google.generativeai", "pydantic", "requests",
)


@pytest.fixture(scope="module")
def simulador():
    pesados = {nombre: _cualquiera(nombre) for nombre in DEPENDENCIAS_SUSTITUIDAS}
    os.environ.setdefault("S3_BUCKET", "bucket-de-pruebas")
    os.environ.setdefault("AWS_REGION", "us-west-2")
    with mock.patch.dict(sys.modules, pesados):
        import main
        yield main


@pytest.fixture
def puerto(simulador):
    simulador.REPARTO_INTACTO.clear()
    simulador.COSTE_INTACTO.clear()

    features = []
    for x in range(N):
        for y in range(N):
            for a, b in (((x, y), (x + 1, y)), ((x, y), (x, y + 1))):
                if max(a[0], b[0]) >= N or max(a[1], b[1]) >= N:
                    continue
                arteria = a[0] == b[0] and a[0] in ARTERIAS
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString",
                                 "coordinates": [_punto(*a), _punto(*b)]},
                    "properties": {"tipo_via": "motorway" if arteria else "residential",
                                   "sentido": "doble", "nombre_via": f"v{len(features)}"},
                })

    grafo, geometrias, nodos = construir_grafo_desde_geojson(features)
    grafo, nodos = podar_componente_principal(grafo)

    def mas_cercano(x, y):
        objetivo = _punto(x, y)
        return min(nodos, key=lambda n: (n[0] - objetivo[0]) ** 2 + (n[1] - objetivo[1]) ** 2)

    nodo_puerto = mas_cercano(*PUERTA)
    rnd = random.Random(3)
    industrias = {"type": "FeatureCollection", "features": []}
    mapeadas = []
    for _ in range(400):
        x, y = rnd.randrange(N), rnd.randrange(4, N)
        mapeadas.append(mas_cercano(x, y))
        industrias["features"].append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": _punto(x, y)},
            "properties": {"demanda_teus": rnd.lognormvariate(4, 1.2)},
        })

    detalle = {"volumen_diario_movible": 50000, "capacidad_diaria": 60000,
               "vulnerabilidad": 0.3, "saturacion": 0.5,
               "puertas_reales": [list(nodo_puerto)]}
    return ({"type": "FeatureCollection", "features": features}, detalle, industrias,
            {"lat": LAT0, "lng": LON0}, grafo, mapeadas, nodo_puerto, geometrias)


CORTE = [[_punto(9.5, 7), _punto(10.5, 7)]]

CORTE_SEVERO = [[_punto(-0.5, 3), _punto(21.5, 3)]]


def _por_indice(resultado):
    return {i: f["properties"]
            for i, f in enumerate(resultado["rutas_simuladas"]["features"])}


def _banda(trafico):
    return 0 if trafico <= 15 else 1 if trafico <= 40 else 2 if trafico <= 80 else 3


def test_la_via_cortada_se_apaga_y_se_marca(simulador, puerto):
    cortado = simulador.calcular_impacto_dinamico("P", CORTE, "despejado", puerto, 1.0)
    marcadas = [p for p in _por_indice(cortado).values() if p.get("cortada")]

    assert cortado["vias_afectadas"] == len(marcadas) > 0
    assert all(p["trafico"] == 0.0 for p in marcadas)


def test_el_corte_resalta_las_vias_que_absorben_el_desvio(simulador, puerto):
    intacto = simulador.calcular_impacto_dinamico("P", [], "despejado", puerto, 1.0)
    cortado = simulador.calcular_impacto_dinamico("P", CORTE, "despejado", puerto, 1.0)

    antes, despues = _por_indice(intacto), _por_indice(cortado)
    desviadas = [i for i, p in despues.items() if "desvio" in p]

    assert desviadas
    assert cortado["vias_desviadas"] == len(desviadas)
    for i in desviadas:
        assert despues[i]["trafico"] > antes[i]["trafico"]
    assert intacto["vias_desviadas"] == 0
    assert all("desvio" not in p for p in antes.values())


def test_el_desvio_no_se_ve_solo_con_el_mapa_de_calor(simulador, puerto):
    intacto = simulador.calcular_impacto_dinamico("P", [], "despejado", puerto, 1.0)
    cortado = simulador.calcular_impacto_dinamico("P", CORTE, "despejado", puerto, 1.0)
    antes, despues = _por_indice(intacto), _por_indice(cortado)

    desviadas = [i for i, p in despues.items() if "desvio" in p]
    mudas = [i for i in desviadas
             if _banda(antes[i]["trafico"]) == _banda(despues[i]["trafico"])]
    assert mudas


@pytest.mark.parametrize("corte", [CORTE, CORTE_SEVERO], ids=["absorbido", "severo"])
def test_la_escala_no_se_renormaliza_con_el_corte(simulador, puerto, corte):
    intacto = simulador.calcular_impacto_dinamico("P", [], "despejado", puerto, 1.0)
    cortado = simulador.calcular_impacto_dinamico("P", corte, "despejado", puerto, 1.0)
    antes, despues = _por_indice(intacto), _por_indice(cortado)

    quietas = [i for i in antes
               if not despues[i].get("cortada") and "desvio" not in despues[i]
               and antes[i]["trafico"] > 0]
    assert quietas
    for i in quietas:
        assert despues[i]["trafico"] <= antes[i]["trafico"] + 1e-9


def test_un_corte_severo_no_puede_pintar_la_red_mas_fria_de_lo_que_estaba(
        simulador, puerto):
    intacto = simulador.calcular_impacto_dinamico("P", [], "despejado", puerto, 1.0)
    cortado = simulador.calcular_impacto_dinamico(
        "P", CORTE_SEVERO, "despejado", puerto, 1.0)
    antes, despues = _por_indice(intacto), _por_indice(cortado)

    assert cortado["sobrecoste_corte"] > 0.5

    vivas = [i for i in antes if not despues[i].get("cortada")]
    calor_antes = sum(antes[i]["trafico"] for i in vivas)
    calor_despues = sum(despues[i]["trafico"] for i in vivas)
    assert calor_despues > 0.7 * calor_antes

    calientes = lambda d: sum(1 for i in vivas if d[i]["trafico"] > 15)
    assert calientes(despues) > 0.7 * calientes(antes)


def test_la_referencia_es_la_red_intacta_aunque_el_clima_cambie_con_el_corte_puesto(
        simulador, puerto):
    simulador.calcular_impacto_dinamico("P", [], "despejado", puerto, 1.0)
    simulador.calcular_impacto_dinamico("P", CORTE, "nieve", puerto, 1.0)
    guardada = simulador.REPARTO_INTACTO[("P", "nieve")]["p95"]

    simulador.REPARTO_INTACTO.clear()
    simulador.calcular_impacto_dinamico("P", [], "nieve", puerto, 1.0)
    verdadera = simulador.REPARTO_INTACTO[("P", "nieve")]["p95"]

    assert guardada == pytest.approx(verdadera)


def test_el_shock_no_mueve_ni_la_escala_ni_el_desvio(simulador, puerto):
    def escenario(shock):
        simulador.REPARTO_INTACTO.clear()
        simulador.calcular_impacto_dinamico("P", [], "despejado", puerto, shock)
        return simulador.calcular_impacto_dinamico("P", CORTE, "despejado", puerto, shock)

    uno, tres = escenario(1.0), escenario(3.0)
    assert [p["trafico"] for p in _por_indice(uno).values()] == pytest.approx(
        [p["trafico"] for p in _por_indice(tres).values()])
    assert uno["vias_desviadas"] == tres["vias_desviadas"]


def test_resetear_los_cortes_devuelve_el_mapa_a_su_estado_original(simulador, puerto):
    intacto = simulador.calcular_impacto_dinamico("P", [], "despejado", puerto, 1.0)
    simulador.calcular_impacto_dinamico("P", CORTE, "despejado", puerto, 1.0)
    vuelta = simulador.calcular_impacto_dinamico("P", [], "despejado", puerto, 1.0)

    assert [p["trafico"] for p in _por_indice(vuelta).values()] == pytest.approx(
        [p["trafico"] for p in _por_indice(intacto).values()])
    assert vuelta["vias_desviadas"] == 0
    assert all("cortada" not in p for p in _por_indice(vuelta).values())


def test_los_cortes_reenviados_al_reconectar_se_conservan(simulador):
    lineas = [[[8.7, 44.4], [8.7, 44.47]], [[8.8, 44.4], [8.9, 44.42], [9.0, 44.4]]]
    assert simulador.sanear_lineas_corte(lineas) == lineas


def test_el_saneado_descarta_lo_que_no_es_un_trazo(simulador):
    basura = [
        [[8.7, 44.4]],
        "esto no es una línea",
        [],
        [[8.7], [44.4]],
        None,
        42,
    ]
    assert simulador.sanear_lineas_corte(basura) == []
    for valor in (None, "corte", 7, {"linea": 1}):
        assert simulador.sanear_lineas_corte(valor) == []


def test_el_saneado_convierte_a_float_y_no_pierde_los_trazos_buenos(simulador):
    mezcla = [[[8.7, 44.4]], [["8.7", "44.4"], ["8.7", "44.47"]], "ruido"]
    assert simulador.sanear_lineas_corte(mezcla) == [[[8.7, 44.4], [8.7, 44.47]]]


def test_los_cortes_restaurados_dan_el_mismo_resultado_que_los_originales(
        simulador, puerto):
    original = simulador.calcular_impacto_dinamico("P", CORTE, "despejado", puerto, 1.0)
    restaurados = simulador.sanear_lineas_corte(CORTE)
    recuperado = simulador.calcular_impacto_dinamico(
        "P", restaurados, "despejado", puerto, 1.0)

    assert recuperado["vias_afectadas"] == original["vias_afectadas"]
    assert recuperado["vias_desviadas"] == original["vias_desviadas"]
    assert [p["trafico"] for p in _por_indice(recuperado).values()] == pytest.approx(
        [p["trafico"] for p in _por_indice(original).values()])
