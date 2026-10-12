import os
import sys
from random import Random

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "etl"))

from muestreo import (anadir_puertos_fijos, muestra_repartida_por_paises,
                      reparto_proporcional)


def puertos_falsos(n, pais, prefijo="p"):
    return [{"portname": f"{prefijo}{i}", "country": pais} for i in range(n)]


def test_reparto_suma_el_total_pedido():
    asignado = reparto_proporcional({"S": 1000, "M": 300, "L": 100}, 40)
    assert sum(asignado.values()) == 40


def test_reparto_es_proporcional_a_la_poblacion():
    asignado = reparto_proporcional({"S": 1000, "M": 300, "L": 100}, 140)
    assert asignado["S"] > asignado["M"] > asignado["L"]


def test_ninguna_talla_desaparece():
    asignado = reparto_proporcional({"S": 5000, "M": 200, "L": 3}, 50)
    assert asignado["L"] >= 1
    assert asignado["M"] >= 1


def test_reparto_no_excede_la_poblacion_del_estrato():
    asignado = reparto_proporcional({"S": 10, "M": 2, "L": 1}, 100)
    assert asignado["S"] <= 10 and asignado["M"] <= 2 and asignado["L"] <= 1


def test_estratos_vacios_reciben_cero():
    asignado = reparto_proporcional({"S": 10, "M": 0, "L": 5}, 6)
    assert asignado["M"] == 0


def test_muestra_menor_que_el_numero_de_estratos():
    asignado = reparto_proporcional({"S": 100, "M": 50, "L": 10}, 2)
    assert sum(asignado.values()) == 2
    assert asignado["S"] == 1 and asignado["M"] == 1 and asignado["L"] == 0


def test_reparto_con_todo_vacio():
    assert reparto_proporcional({"S": 0, "M": 0, "L": 0}, 10) == {"S": 0, "M": 0, "L": 0}


def test_devuelve_el_tamano_pedido():
    puertos = puertos_falsos(50, "ES") + puertos_falsos(50, "IT", "q")
    assert len(muestra_repartida_por_paises(puertos, 20, Random(1))) == 20


def test_no_se_concentra_en_el_pais_dominante():
    puertos = puertos_falsos(90, "ES") + puertos_falsos(10, "IT", "q")
    muestra = muestra_repartida_por_paises(puertos, 10, Random(7))
    paises = [p["country"] for p in muestra]
    assert paises.count("IT") >= 4


def test_es_reproducible_con_la_misma_semilla():
    puertos = puertos_falsos(40, "ES") + puertos_falsos(40, "IT", "q")
    a = muestra_repartida_por_paises(puertos, 15, Random(42))
    b = muestra_repartida_por_paises(puertos, 15, Random(42))
    assert [p["portname"] for p in a] == [p["portname"] for p in b]


def test_semillas_distintas_dan_muestras_distintas():
    puertos = puertos_falsos(200, "ES")
    a = muestra_repartida_por_paises(puertos, 20, Random(1))
    b = muestra_repartida_por_paises(puertos, 20, Random(2))
    assert [p["portname"] for p in a] != [p["portname"] for p in b]


def test_pedir_mas_de_los_que_hay_devuelve_todos():
    puertos = puertos_falsos(5, "ES")
    assert len(muestra_repartida_por_paises(puertos, 99, Random(1))) == 5


def test_no_repite_puertos():
    puertos = puertos_falsos(30, "ES") + puertos_falsos(30, "IT", "q")
    muestra = muestra_repartida_por_paises(puertos, 25, Random(3))
    nombres = [(p["country"], p["portname"]) for p in muestra]
    assert len(nombres) == len(set(nombres))


def test_tolera_puertos_sin_pais():
    puertos = [{"portname": f"x{i}"} for i in range(10)]
    assert len(muestra_repartida_por_paises(puertos, 4, Random(1))) == 4


@pytest.mark.parametrize("n", [0, 1, 2, 7, 13])
def test_tamanos_variados(n):
    puertos = puertos_falsos(10, "ES") + puertos_falsos(10, "IT", "q")
    assert len(muestra_repartida_por_paises(puertos, n, Random(5))) == n


def es_offshore(puerto):
    return str(puerto.get("portid") or "").startswith("fso")


@pytest.mark.parametrize("portid,esperado", [
    ("fso0", True), ("fso123", True),
    ("port1114", False), ("port57", False),
    ("", False), (None, False),
])
def test_detecta_las_terminales_offshore(portid, esperado):
    assert es_offshore({"portid": portid}) is esperado


def test_el_filtro_deja_solo_puertos_reales():
    catalogo = ([{"portid": f"port{i}", "portname": f"P{i}"} for i in range(10)]
                + [{"portid": f"fso{i}", "portname": f"Terminal {i}"} for i in range(5)])
    reales = [p for p in catalogo if not es_offshore(p)]
    assert len(reales) == 10
    assert all(p["portid"].startswith("port") for p in reales)


def catalogo_falso(portids, pais="ES"):
    return [{"portid": pid, "portname": pid.upper(), "country": pais} for pid in portids]


def test_anade_los_casos_que_el_sorteo_dejo_fuera():
    catalogo = catalogo_falso(["port1", "port387", "port2", "port1114"])
    sorteados = [catalogo[0], catalogo[2]]
    seleccion, anadidos = anadir_puertos_fijos(sorteados, catalogo, {"port387", "port1114"})
    assert {p["portid"] for p in seleccion} == {"port1", "port2", "port387", "port1114"}
    assert anadidos == {"port387", "port1114"}


def test_no_duplica_un_caso_que_ya_habia_salido_en_el_sorteo():
    catalogo = catalogo_falso(["port387", "port1", "port2"])
    sorteados = [catalogo[0], catalogo[1]]
    seleccion, anadidos = anadir_puertos_fijos(sorteados, catalogo, {"port387"})
    assert [p["portid"] for p in seleccion].count("port387") == 1
    assert anadidos == set()


def test_ignora_portids_que_no_existen_en_el_catalogo():
    catalogo = catalogo_falso(["port1", "port2"])
    seleccion, anadidos = anadir_puertos_fijos([], catalogo, {"port999", "puerto_inventado"})
    assert seleccion == [] and anadidos == set()


def test_respeta_el_orden_sorteo_primero_forzados_despues():
    catalogo = catalogo_falso(["port387", "port1", "port2"])
    sorteados = [catalogo[1], catalogo[2]]
    seleccion, _ = anadir_puertos_fijos(sorteados, catalogo, {"port387"})
    assert [p["portid"] for p in seleccion] == ["port1", "port2", "port387"]


def test_sin_puertos_fijos_devuelve_la_muestra_intacta():
    catalogo = catalogo_falso(["port1", "port2"])
    seleccion, anadidos = anadir_puertos_fijos(catalogo, catalogo, set())
    assert [p["portid"] for p in seleccion] == ["port1", "port2"]
    assert anadidos == set()


def test_no_muta_la_lista_original():
    catalogo = catalogo_falso(["port1", "port387"])
    sorteados = [catalogo[0]]
    anadir_puertos_fijos(sorteados, catalogo, {"port387"})
    assert len(sorteados) == 1


def test_solo_toca_los_puertos_de_su_propia_talla():
    catalogo_s = catalogo_falso(["port1", "port2"])
    seleccion, anadidos = anadir_puertos_fijos([], catalogo_s, {"port1114"})
    assert anadidos == set() and seleccion == []
