import os
import random
import sys

import networkx as nx
import pytest

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(RAIZ, "etl"))

from grafos import (
    NODO_SUPERFUENTE,
    arbol_de_caminos,
    reconstruir_camino,
)


def grafo_aleatorio(n_nodos, n_aristas, semilla, peso="weight"):
    rng = random.Random(semilla)
    G = nx.DiGraph()
    G.add_nodes_from(range(n_nodos))
    for _ in range(n_aristas):
        u, v = rng.randrange(n_nodos), rng.randrange(n_nodos)
        if u != v:
            G.add_edge(u, v, **{peso: round(rng.uniform(0.1, 10.0), 3)})
    return G


def coste(G, camino, peso="weight"):
    return sum(G[camino[i]][camino[i + 1]][peso] for i in range(len(camino) - 1))


@pytest.mark.parametrize("semilla", [1, 2, 3, 7, 42])
def test_las_distancias_coinciden_con_multi_source_dijkstra(semilla):
    G = grafo_aleatorio(120, 400, semilla)
    origenes = [0, 5, 11]

    referencia, _ = nx.multi_source_dijkstra(G, set(origenes), weight="weight")
    distancias, _ = arbol_de_caminos(G, origenes, "weight")

    assert set(distancias) == set(referencia)
    for nodo, d in referencia.items():
        assert distancias[nodo] == pytest.approx(d)


@pytest.mark.parametrize("semilla", [1, 4, 9, 23])
def test_los_caminos_reconstruidos_son_minimos(semilla):
    G = grafo_aleatorio(120, 400, semilla)
    origenes = [0, 5, 11]

    referencia, _ = nx.multi_source_dijkstra(G, set(origenes), weight="weight")
    distancias, predecesores = arbol_de_caminos(G, origenes, "weight")

    for nodo in distancias:
        camino = reconstruir_camino(nodo, predecesores)
        assert camino[-1] == nodo
        assert camino[0] in origenes
        assert coste(G, camino) == pytest.approx(referencia[nodo])


def test_el_camino_de_un_origen_es_el_propio_nodo():
    G = grafo_aleatorio(50, 150, 5)
    distancias, predecesores = arbol_de_caminos(G, [0], "weight")
    assert reconstruir_camino(0, predecesores) == [0]
    assert distancias[0] == pytest.approx(0.0)


def test_funciona_con_otro_nombre_de_peso():
    G = grafo_aleatorio(60, 200, 3, peso="weight_dinamico")
    referencia, _ = nx.multi_source_dijkstra(G, {0}, weight="weight_dinamico")
    distancias, _ = arbol_de_caminos(G, [0], "weight_dinamico")
    for nodo, d in referencia.items():
        assert distancias[nodo] == pytest.approx(d)


def test_la_superfuente_no_queda_en_el_grafo():
    G = grafo_aleatorio(40, 120, 8)
    antes_nodos, antes_aristas = G.number_of_nodes(), G.number_of_edges()

    arbol_de_caminos(G, [0, 1], "weight")

    assert NODO_SUPERFUENTE not in G
    assert G.number_of_nodes() == antes_nodos
    assert G.number_of_edges() == antes_aristas


def test_la_superfuente_se_retira_aunque_dijkstra_falle(monkeypatch):
    G = grafo_aleatorio(30, 80, 2)
    antes = G.number_of_nodes()

    def explota(*a, **k):
        raise RuntimeError("fallo simulado")

    monkeypatch.setattr(nx, "dijkstra_predecessor_and_distance", explota)
    with pytest.raises(RuntimeError):
        arbol_de_caminos(G, [0], "weight")

    assert NODO_SUPERFUENTE not in G
    assert G.number_of_nodes() == antes


def test_ni_la_superfuente_ni_su_distancia_salen_en_el_resultado():
    G = grafo_aleatorio(40, 120, 6)
    distancias, predecesores = arbol_de_caminos(G, [0, 3], "weight")
    assert NODO_SUPERFUENTE not in distancias
    assert NODO_SUPERFUENTE not in predecesores


def test_sin_origenes_validos_devuelve_vacio():
    G = grafo_aleatorio(30, 80, 1)
    assert arbol_de_caminos(G, [], "weight") == ({}, {})
    assert arbol_de_caminos(G, [None], "weight") == ({}, {})
    assert arbol_de_caminos(G, ["fantasma"], "weight") == ({}, {})


def test_mezcla_de_origenes_validos_e_invalidos():
    G = grafo_aleatorio(40, 120, 4)
    distancias, _ = arbol_de_caminos(G, [None, "fantasma", 0], "weight")
    assert distancias
    assert distancias[0] == pytest.approx(0.0)


def test_nodos_inalcanzables_no_aparecen():
    G = nx.DiGraph()
    G.add_edge("a", "b", weight=1.0)
    G.add_edge("x", "y", weight=1.0)
    distancias, _ = arbol_de_caminos(G, ["a"], "weight")
    assert set(distancias) == {"a", "b"}


def test_grafo_de_un_solo_nodo():
    G = nx.DiGraph()
    G.add_node("solo")
    distancias, predecesores = arbol_de_caminos(G, ["solo"], "weight")
    assert distancias == {"solo": 0.0}
    assert reconstruir_camino("solo", predecesores) == ["solo"]


def test_varios_origenes_gana_el_mas_cercano():
    G = nx.DiGraph()
    G.add_edge("o1", "destino", weight=10.0)
    G.add_edge("o2", "destino", weight=1.0)
    distancias, predecesores = arbol_de_caminos(G, ["o1", "o2"], "weight")
    assert distancias["destino"] == pytest.approx(1.0)
    assert reconstruir_camino("destino", predecesores) == ["o2", "destino"]


def _red_con_desvio():
    g = nx.DiGraph()
    for u, v, w in (("P", "A", 1.0), ("A", "D", 1.0),
                    ("P", "B", 5.0), ("B", "D", 5.0)):
        g.add_edge(u, v, weight=w)
        g.add_edge(v, u, weight=w)
    return g


def test_el_coste_pondera_por_demanda():
    from grafos import coste_servicio_hinterland
    g = _red_con_desvio()
    r = coste_servicio_hinterland(g, ["P"], [("D", 10.0)])
    assert r["coste"] == pytest.approx(20.0)
    assert r["servida"] == pytest.approx(10.0)
    assert r["desconectada"] == 0.0


def test_lo_inalcanzable_no_suma_coste_sino_demanda_desconectada():
    from grafos import coste_servicio_hinterland
    g = _red_con_desvio()
    g.add_node("ISLA")
    r = coste_servicio_hinterland(g, ["P"], [("D", 10.0), ("ISLA", 4.0)])
    assert r["servida"] == pytest.approx(10.0)
    assert r["desconectada"] == pytest.approx(4.0)
    assert r["total"] == pytest.approx(14.0)


def test_cortar_el_camino_directo_encarece_el_servicio():
    from grafos import coste_medio_servicio, coste_servicio_hinterland
    g = _red_con_desvio()
    intacto = coste_servicio_hinterland(g, ["P"], [("D", 10.0)])

    g.remove_edge("A", "D")
    g.remove_edge("D", "A")
    cortado = coste_servicio_hinterland(g, ["P"], [("D", 10.0)])

    assert coste_medio_servicio(intacto) == pytest.approx(2.0)
    assert coste_medio_servicio(cortado) == pytest.approx(10.0)
    sobrecoste = coste_medio_servicio(cortado) / coste_medio_servicio(intacto) - 1
    assert sobrecoste == pytest.approx(4.0)


def test_el_coste_medio_ignora_la_demanda_que_ya_no_se_atiende():
    from grafos import coste_medio_servicio, coste_servicio_hinterland
    g = _red_con_desvio()
    g.add_node("ISLA")
    r = coste_servicio_hinterland(g, ["P"], [("D", 10.0), ("ISLA", 90.0)])
    assert coste_medio_servicio(r) == pytest.approx(2.0)


def test_sin_demanda_atendida_no_hay_coste_medio():
    from grafos import coste_medio_servicio, coste_servicio_hinterland
    g = _red_con_desvio()
    g.add_node("ISLA")
    r = coste_servicio_hinterland(g, ["P"], [("ISLA", 5.0)])
    assert coste_medio_servicio(r) is None


def test_un_corte_que_no_afecta_no_encarece_nada():
    from grafos import coste_medio_servicio, coste_servicio_hinterland
    g = _red_con_desvio()
    intacto = coste_medio_servicio(coste_servicio_hinterland(g, ["P"], [("D", 10.0)]))

    g.remove_edge("P", "B")
    g.remove_edge("B", "P")
    cortado = coste_medio_servicio(coste_servicio_hinterland(g, ["P"], [("D", 10.0)]))

    assert cortado == pytest.approx(intacto)


@pytest.mark.parametrize("semilla", [1, 2, 3, 7, 42])
def test_solo_distancias_da_exactamente_las_mismas_distancias(semilla):
    G = grafo_aleatorio(120, 400, semilla)
    origenes = [0, 5, 11]

    completo, predecesores = arbol_de_caminos(G, origenes, "weight")
    solo, vacio = arbol_de_caminos(G, origenes, "weight", solo_distancias=True)

    assert solo == completo
    assert vacio == {}
    assert predecesores


def test_solo_distancias_tambien_retira_la_superfuente():
    G = grafo_aleatorio(40, 120, 5)
    nodos_antes = set(G.nodes)
    arbol_de_caminos(G, [0, 1], "weight", solo_distancias=True)
    assert set(G.nodes) == nodos_antes
    assert NODO_SUPERFUENTE not in G


def test_solo_distancias_sin_origenes_validos_no_revienta():
    G = grafo_aleatorio(20, 40, 3)
    assert arbol_de_caminos(G, [], "weight", solo_distancias=True) == ({}, {})
    assert arbol_de_caminos(G, ["fantasma"], "weight", solo_distancias=True) == ({}, {})


def test_el_coste_del_hinterland_no_cambia_al_no_pedir_predecesores(semilla=11):
    from grafos import coste_servicio_hinterland

    G = grafo_aleatorio(150, 600, semilla)
    origenes = [0, 3]
    distancias, _ = arbol_de_caminos(G, origenes, "weight")
    destinos = [(n, 1.0 + n % 7) for n in list(G.nodes)[:40]]

    resumen = coste_servicio_hinterland(G, origenes, destinos)

    esperado = sum(d * distancias[n] for n, d in destinos if n in distancias)
    assert resumen["coste"] == pytest.approx(esperado)
    assert resumen["total"] == pytest.approx(sum(d for _n, d in destinos))
    assert resumen["servida"] + resumen["desconectada"] == pytest.approx(resumen["total"])
