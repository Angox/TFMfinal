import os
import sys

import pytest

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(RAIZ, "etl"))

from portwatch import (
    SEGMENTOS_DIRECTOS,
    SEGMENTOS_MOVIBLES,
    percentil,
    resumir_serie,
)


def dia(fecha, **kwargs):
    fila = {"date": fecha, "year": int(fecha[:4])}
    for s in SEGMENTOS_MOVIBLES + SEGMENTOS_DIRECTOS:
        fila[f"import_{s}"] = 0
        fila[f"export_{s}"] = 0
    fila.update(kwargs)
    return fila


def test_percentil_coincide_en_los_extremos():
    v = list(range(1, 101))
    assert percentil(v, 0.0) == 1
    assert percentil(v, 1.0) == 100


def test_percentil_interpola():
    assert percentil(list(range(1, 101)), 0.95) == pytest.approx(95.05)
    assert percentil([10, 20], 0.5) == pytest.approx(15.0)


def test_percentil_no_depende_del_orden_de_entrada():
    assert percentil([5, 1, 4, 2, 3], 0.5) == percentil([1, 2, 3, 4, 5], 0.5)


def test_percentil_de_lista_vacia():
    assert percentil([], 0.95) is None


def test_suma_importacion_y_exportacion_de_los_segmentos_movibles():
    filas = [dia("2024-01-01", import_container=100, export_container=50,
                 import_roro=10, export_general_cargo=5,
                 import_dry_bulk=999, export_tanker=999)]
    r = resumir_serie(filas, dias_ventana=None)
    assert r["carga_movible"] == pytest.approx(165)
    assert r["carga_directa"] == pytest.approx(1998)


def test_capacidad_es_el_percentil_del_historico():
    filas = [dia(f"2024-01-{d:02d}", import_container=d * 100) for d in range(1, 21)]
    r = resumir_serie(filas, dias_ventana=None, percentil_capacidad=0.95)
    assert r["capacidad_movible"] == pytest.approx(1905.0)
    assert r["maximo_movible"] == pytest.approx(2000.0)
    assert r["mediana_movible"] == pytest.approx(1050.0)


def test_los_dias_a_cero_no_hunden_la_media():
    filas = ([dia(f"2024-01-{d:02d}", import_container=1000) for d in range(1, 11)]
             + [dia(f"2024-02-{d:02d}") for d in range(1, 11)])
    r = resumir_serie(filas, dias_ventana=None)
    assert r["carga_movible"] == pytest.approx(1000.0)
    assert r["n_dias"] == 20 and r["n_dias_activos"] == 10


def test_la_ventana_solo_mira_los_ultimos_dias():
    filas = ([dia(f"2023-01-{d:02d}", import_container=5000) for d in range(1, 11)]
             + [dia(f"2024-01-{d:02d}", import_container=1000) for d in range(1, 11)])
    r = resumir_serie(filas, dias_ventana=10)
    assert r["carga_movible"] == pytest.approx(1000.0)
    assert r["capacidad_movible"] > 4000


def test_serie_vacia_o_toda_a_cero_devuelve_none():
    assert resumir_serie([]) is None
    assert resumir_serie([dia("2024-01-01")]) is None


def test_el_resumen_declara_unidad_y_fuente():
    r = resumir_serie([dia("2024-01-01", import_container=10)], dias_ventana=None)
    assert r["unidad"] == "toneladas/dia"
    assert "PortWatch" in r["fuente"]


def test_con_ventana_completa_la_capacidad_es_autoreferente():
    filas = [dia(f"2024-01-{d:02d}", import_container=d * 10) for d in range(1, 29)]
    r = resumir_serie(filas, dias_ventana=None)
    assert r["capacidad_autoreferente"] is True
    assert r["carga_movible"] <= r["capacidad_movible"]


def _serie(valores):
    return [dia(f"2020-01-{(i % 28) + 1:02d}", import_container=v)
            for i, v in enumerate(valores)]


def test_un_puerto_estable_excede_su_capacidad_en_torno_al_5_por_ciento():
    base = [1000 + (i % 17) * 10 for i in range(1000)]
    ventana = [1000 + (i % 17) * 10 for i in range(365)]
    r = resumir_serie(_serie(base + ventana), dias_ventana=365)

    assert r["capacidad_autoreferente"] is False
    assert 0.0 <= r["frecuencia_excedencia"] <= 0.15


def test_un_puerto_tensionado_excede_su_capacidad_casi_siempre():
    base = [1000 + (i % 17) * 10 for i in range(1000)]
    ventana = [1800 + (i % 17) * 10 for i in range(365)]
    r = resumir_serie(_serie(base + ventana), dias_ventana=365)

    assert r["frecuencia_excedencia"] > 0.9
    assert r["ratio_p95"] > 1.0


def test_la_volatilidad_ya_no_baja_la_nota():
    regular = [1000] * 1365
    irregular = [500 if i % 2 else 1500 for i in range(1365)]

    r_reg = resumir_serie(_serie(regular), dias_ventana=365)
    r_irr = resumir_serie(_serie(irregular), dias_ventana=365)

    assert r_reg["carga_movible"] == pytest.approx(r_irr["carga_movible"], rel=0.02)

    antiguo_reg = r_reg["carga_movible"] / r_reg["capacidad_movible"]
    antiguo_irr = r_irr["carga_movible"] / r_irr["capacidad_movible"]
    assert antiguo_reg > antiguo_irr * 1.2

    assert abs(r_reg["frecuencia_excedencia"] - r_irr["frecuencia_excedencia"]) < 0.2


def test_la_frecuencia_esta_acotada_en_cero_uno():
    for valores in ([1000] * 1365,
                    [1000] * 1000 + [50000] * 365,
                    [1000] * 1000 + [1] * 365):
        r = resumir_serie(_serie(valores), dias_ventana=365)
        assert 0.0 <= r["frecuencia_excedencia"] <= 1.0


def test_una_serie_corta_se_marca_como_autoreferente():
    r = resumir_serie(_serie([1000] * 400), dias_ventana=365, min_dias_base=180)
    assert r["capacidad_autoreferente"] is True
    assert r["n_dias_base"] == 35


def test_el_periodo_base_y_la_ventana_no_se_solapan():
    r = resumir_serie(_serie([1000] * 1365), dias_ventana=365)
    assert r["n_dias_base"] == 1000
    assert r["n_dias_ventana"] == 365
    assert r["n_dias_base"] + r["n_dias_ventana"] == r["n_dias_activos"]


def test_los_dias_a_cero_siguen_sin_contar():
    valores = [1000 if i % 2 else 0 for i in range(1400)]
    r = resumir_serie(_serie(valores), dias_ventana=365)
    assert r["carga_movible"] == pytest.approx(1000.0)
    assert r["n_dias_activos"] == 700


def test_percentil_acota_q_por_arriba():
    v = list(range(1, 101))
    assert percentil(v, 1.235) == 100
    assert percentil(v, 5.0) == 100


def test_percentil_acota_q_por_abajo():
    v = list(range(1, 101))
    assert percentil(v, -0.3) == 1


def test_percentil_fuera_de_rango_no_revienta_con_pocos_valores():
    for n in (1, 2, 3, 10):
        v = list(range(n))
        assert percentil(v, 1.235) == n - 1
        assert percentil(v, -1.0) == 0


def test_resumir_serie_tolera_un_percentil_perturbado():
    filas = [dia(f"2024-01-{(i % 28) + 1:02d}", import_container=1000 + i % 17)
             for i in range(500)]
    r = resumir_serie(filas, dias_ventana=100, percentil_capacidad=0.95 * 1.3)
    assert r is not None
    assert r["capacidad_movible"] > 0
