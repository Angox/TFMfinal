import math
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "etl"))

from calculos import (
    RADIO_TIERRA_KM,
    calcular_distancia_haversine,
    estres_con_aislamiento,
    fuerza_gravitatoria,
    indice_compuesto,
    intensidad_visual,
    normalizar_tonelaje,
    pendiente_entre_nodos,
    penalizacion_topografica,
    percentil_trafico,
    proyectar_local,
    saturacion_con_shock,
    semivida_disuasion,
    vulnerabilidad_normalizada,
)


def test_sin_unidad_se_asume_tonelada():
    assert normalizar_tonelaje("7.5") == pytest.approx(7.5)
    assert normalizar_tonelaje(3.5, "") == pytest.approx(3.5)


def test_las_libras_se_convierten_a_toneladas():
    assert normalizar_tonelaje(80000, "lbs") == pytest.approx(36.287, abs=0.01)
    assert normalizar_tonelaje(80000, "lbs") < 40.0


@pytest.mark.parametrize("valor,unidad,esperado", [
    (3.5, "t", 3.5),
    (3500, "kg", 3.5),
    (40, "T", 40.0),
    (10, "short_ton", 9.07185),
])
def test_conversiones_conocidas(valor, unidad, esperado):
    assert normalizar_tonelaje(valor, unidad) == pytest.approx(esperado, rel=1e-4)


def test_una_unidad_desconocida_no_se_inventa_un_factor():
    assert normalizar_tonelaje(40, "quintales") is None


@pytest.mark.parametrize("valor", [None, "", "sin datos", 0, -5])
def test_valores_invalidos_devuelven_el_defecto(valor):
    assert normalizar_tonelaje(valor, "t") is None


def test_la_pendiente_es_adimensional():
    assert pendiente_entre_nodos(0.0, 100.0, 1.0) == pytest.approx(0.10)


def test_la_pendiente_de_bajada_es_negativa():
    assert pendiente_entre_nodos(100.0, 0.0, 1.0) == pytest.approx(-0.10)


def test_sin_altitud_no_se_inventa_desnivel():
    assert pendiente_entre_nodos(None, 100.0, 1.0) == 0.0
    assert pendiente_entre_nodos(100.0, None, 1.0) == 0.0
    assert pendiente_entre_nodos(None, None, 1.0) == 0.0


def test_la_pendiente_se_recorta_al_maximo_fisico():
    cruda = pendiente_entre_nodos(0.0, 200.0, 0.05)
    assert cruda == pytest.approx(4.0)

    recortada = pendiente_entre_nodos(0.0, 200.0, 0.05, pendiente_maxima=0.15)
    assert recortada == pytest.approx(0.15)


def test_el_recorte_es_simetrico_en_las_bajadas():
    assert pendiente_entre_nodos(200.0, 0.0, 0.05, pendiente_maxima=0.15) == pytest.approx(-0.15)


def test_distancia_cero_no_divide_por_cero():
    assert pendiente_entre_nodos(0.0, 100.0, 0.0) == 0.0


def test_la_penalizacion_es_asimetrica():
    assert penalizacion_topografica(0.06, 10.0) == pytest.approx(1.6)
    assert penalizacion_topografica(-0.06, 10.0) == 1.0
    assert penalizacion_topografica(0.0, 10.0) == 1.0


def test_factor_cero_anula_la_topografia():
    assert penalizacion_topografica(0.15, 0.0) == 1.0


def test_el_tren_sufre_mas_la_rampa_que_el_camion():
    assert penalizacion_topografica(0.03, 50.0) > penalizacion_topografica(0.03, 10.0)


def test_el_origen_se_proyecta_en_el_cero():
    x, y = proyectar_local(10.0, 45.0, 10.0, 45.0)
    assert x == pytest.approx(0.0)
    assert y == pytest.approx(0.0)


def test_un_grado_de_latitud_son_unos_111_km():
    _x, y = proyectar_local(0.0, 1.0, 0.0, 0.0)
    assert y == pytest.approx(math.pi / 180.0 * RADIO_TIERRA_KM, rel=1e-9)
    assert 111.0 < y < 111.4


def test_la_longitud_encoge_con_la_latitud():
    x_ecuador, _ = proyectar_local(1.0, 0.0, 0.0, 0.0)
    x_sesenta, _ = proyectar_local(1.0, 60.0, 0.0, 60.0)
    assert x_sesenta == pytest.approx(x_ecuador * 0.5, rel=1e-6)


def test_la_proyeccion_concuerda_con_haversine_en_distancias_cortas():
    lon_ref, lat_ref = 5.6, 58.9
    for dlon, dlat in ((0.05, 0.0), (0.0, 0.05), (0.03, -0.04)):
        x, y = proyectar_local(lon_ref + dlon, lat_ref + dlat, lon_ref, lat_ref)
        plana = math.hypot(x, y)
        esferica = calcular_distancia_haversine(
            lon_ref, lat_ref, lon_ref + dlon, lat_ref + dlat)
        assert plana == pytest.approx(esferica, rel=0.01)


def test_sin_sobrecoste_no_hay_vulnerabilidad():
    assert vulnerabilidad_normalizada(0.0, 3.0) == 0.0
    assert vulnerabilidad_normalizada(-1.0, 3.0) == 0.0


def test_la_vulnerabilidad_esta_acotada_en_uno():
    assert vulnerabilidad_normalizada(1e9, 3.0) == pytest.approx(1.0)
    for x in (0.01, 0.5, 3.0, 50.0):
        assert 0.0 <= vulnerabilidad_normalizada(x, 3.0) <= 1.0
    for x in (0.01, 0.5, 3.0):
        assert vulnerabilidad_normalizada(x, 3.0) < 1.0


def test_la_vulnerabilidad_es_monotona_creciente():
    valores = [vulnerabilidad_normalizada(x / 10, 3.0) for x in range(0, 40)]
    assert valores == sorted(valores)


def test_lambda_controla_la_pendiente():
    assert vulnerabilidad_normalizada(0.2, 6.0) > vulnerabilidad_normalizada(0.2, 3.0)


def test_el_indice_recorre_todo_el_rango():
    assert indice_compuesto(0.0, 0.0) == 0.0
    assert indice_compuesto(1.0, 1.0) == 10.0
    assert indice_compuesto(0.5, 0.5) == pytest.approx(5.0)


def test_las_dos_dimensiones_pesan_igual():
    assert indice_compuesto(1.0, 0.0) == pytest.approx(indice_compuesto(0.0, 1.0))


def test_el_indice_respeta_pesos_personalizados():
    assert indice_compuesto(1.0, 0.0, 7.0, 3.0) == pytest.approx(7.0)
    assert indice_compuesto(0.0, 1.0, 7.0, 3.0) == pytest.approx(3.0)


@pytest.mark.parametrize("sat,vul", [(-1, 0.5), (2, 0.5), (0.5, -3), (0.5, 9)])
def test_el_indice_acota_sus_entradas(sat, vul):
    assert 0.0 <= indice_compuesto(sat, vul) <= 10.0


def test_el_shock_solo_escala_la_saturacion():
    sat, vul, k = 0.3, 0.6, 2.0
    base = indice_compuesto(sat, vul)
    correcto = indice_compuesto(saturacion_con_shock(sat, k), vul)
    incorrecto = min(base * k, 10.0)

    assert correcto == pytest.approx(0.6 * 5 + 0.6 * 5)
    assert correcto < incorrecto


def test_el_shock_no_desborda_la_saturacion():
    assert saturacion_con_shock(0.8, 5.0) == 1.0
    assert saturacion_con_shock(0.5, 0.0) == 0.0


def test_shock_unitario_no_cambia_nada():
    for sat in (0.0, 0.37, 1.0):
        assert saturacion_con_shock(sat, 1.0) == pytest.approx(sat)


def test_sin_aislamiento_el_indice_no_cambia():
    assert estres_con_aislamiento(4.2, 0.0) == pytest.approx(4.2)


def test_aislamiento_total_lleva_al_maximo():
    assert estres_con_aislamiento(4.2, 1.0) == pytest.approx(10.0)


def test_el_aislamiento_es_monotono():
    valores = [estres_con_aislamiento(3.0, f / 10) for f in range(11)]
    assert valores == sorted(valores)


@pytest.mark.parametrize("base", [0.0, 2.5, 7.7, 10.0])
@pytest.mark.parametrize("fraccion", [-0.5, 0.0, 0.33, 1.0, 2.0])
def test_el_aislamiento_nunca_se_sale_del_rango(base, fraccion):
    assert 0.0 <= estres_con_aislamiento(base, fraccion) <= 10.0


def test_el_aislamiento_distingue_lo_que_el_contador_absoluto_confundia():
    pocas = estres_con_aislamiento(3.0, 4 / 500)
    muchas = estres_con_aislamiento(3.0, 4 / 5)
    antiguo = min(3.0 + 4 * 3.0, 10.0)

    assert pocas < muchas
    assert antiguo == 10.0
    assert pocas < 3.1


def test_la_potencia_no_esta_definida_en_coste_cero():
    assert fuerza_gravitatoria(1000, 0.0, "potencia") is None


def test_la_exponencial_vale_la_masa_en_coste_cero():
    assert fuerza_gravitatoria(1000, 0.0, "exponencial") == pytest.approx(1000.0)


def test_la_potencia_concentra_el_reparto_en_los_destinos_pegados_al_puerto():
    cerca = fuerza_gravitatoria(1000, 0.1, "potencia")
    lejos = fuerza_gravitatoria(1000, 20.0, "potencia")
    assert cerca / lejos > 10_000

    cerca_e = fuerza_gravitatoria(1000, 0.1, "exponencial")
    lejos_e = fuerza_gravitatoria(1000, 20.0, "exponencial")
    assert cerca_e / lejos_e < 3


def test_la_exponencial_decae_de_forma_monotona():
    valores = [fuerza_gravitatoria(1000, c, "exponencial") for c in range(0, 100, 5)]
    assert valores == sorted(valores, reverse=True)
    assert all(v > 0 for v in valores)


def test_beta_se_lee_como_semivida():
    beta = 0.03
    media_vida = semivida_disuasion(beta)
    assert media_vida == pytest.approx(math.log(2) / beta)
    assert fuerza_gravitatoria(1000, media_vida, "exponencial", beta=beta) == pytest.approx(500.0)


def test_beta_mayor_concentra_mas_el_reparto():
    lejano = 40.0
    assert (fuerza_gravitatoria(1000, lejano, "exponencial", beta=0.10)
            < fuerza_gravitatoria(1000, lejano, "exponencial", beta=0.01))


def test_semivida_de_beta_nulo_es_infinita():
    assert semivida_disuasion(0.0) == float("inf")
    assert fuerza_gravitatoria(1000, 500.0, "exponencial", beta=0.0) == pytest.approx(1000.0)


@pytest.mark.parametrize("masa", [None, 0, -5])
def test_una_masa_no_positiva_no_atrae(masa):
    assert fuerza_gravitatoria(masa, 10.0, "exponencial") is None


def test_una_funcion_desconocida_no_se_traga_en_silencio():
    with pytest.raises(ValueError):
        fuerza_gravitatoria(1000, 10.0, "inventada")


def test_la_intensidad_es_el_maximo_de_los_tramos_no_la_media():
    tramos = [10_000, 51_675, 200]
    assert intensidad_visual(tramos, 36_183) == pytest.approx(100.0)

    media = sum(tramos) / len(tramos) / 36_183 * 100
    assert media == pytest.approx(57.0, abs=1.0)


def test_la_intensidad_se_recorta_en_cien():
    assert intensidad_visual([10_000_000], 100) == 100.0


def test_una_via_sin_trafico_sale_a_cero():
    assert intensidad_visual([], 100) == 0.0
    assert intensidad_visual([0, 0], 100) == 0.0


@pytest.mark.parametrize("denominador", [0, None, -5])
def test_un_denominador_invalido_no_divide_por_cero(denominador):
    assert intensidad_visual([500], denominador) == 0.0


def test_el_percentil_ignora_las_aristas_vacias():
    assert percentil_trafico([0] * 1000 + [10, 20, 30]) == 30


def test_el_percentil_no_se_sale_de_la_lista():
    for n in (1, 2, 3, 50):
        assert percentil_trafico(list(range(1, n + 1))) <= n


def test_percentil_de_una_red_sin_trafico():
    assert percentil_trafico([]) == 0.0
    assert percentil_trafico([0, 0, 0]) == 0.0


def test_el_percentil_es_mas_robusto_que_el_maximo():
    red = [100] * 99 + [10_000]
    assert percentil_trafico(red) == 100
    assert max(red) == 10_000
    assert intensidad_visual([100], percentil_trafico(red)) == 100.0
    assert intensidad_visual([100], max(red)) == pytest.approx(1.0)
