import networkx as nx

NODO_SUPERFUENTE = ("__superfuente__", 0.0)


def arbol_de_caminos(grafo, origenes, peso, solo_distancias=False):
    origenes = [o for o in origenes if o is not None and o in grafo]
    if not origenes:
        return {}, {}

    grafo.add_node(NODO_SUPERFUENTE)
    for origen in origenes:
        grafo.add_edge(NODO_SUPERFUENTE, origen, **{peso: 0.0})
    try:
        if solo_distancias:
            predecesores = {}
            distancias = nx.single_source_dijkstra_path_length(
                grafo, NODO_SUPERFUENTE, weight=peso)
        else:
            predecesores, distancias = nx.dijkstra_predecessor_and_distance(
                grafo, NODO_SUPERFUENTE, weight=peso)
    finally:
        grafo.remove_node(NODO_SUPERFUENTE)

    distancias.pop(NODO_SUPERFUENTE, None)
    predecesores.pop(NODO_SUPERFUENTE, None)
    return distancias, predecesores


def reconstruir_camino(nodo, predecesores):
    camino = [nodo]
    vistos = {nodo}
    actual = nodo
    while True:
        anteriores = predecesores.get(actual)
        if not anteriores:
            break
        anterior = anteriores[0]
        if anterior == NODO_SUPERFUENTE or anterior in vistos:
            break
        camino.append(anterior)
        vistos.add(anterior)
        actual = anterior
    camino.reverse()
    return camino


def coste_servicio_hinterland(grafo, origenes, destinos_demanda, peso='weight'):
    distancias, _predecesores = arbol_de_caminos(
        grafo, origenes, peso, solo_distancias=True)
    coste, servida, desconectada, total = 0.0, 0.0, 0.0, 0.0
    for nodo, demanda in destinos_demanda:
        total += demanda
        if nodo in distancias:
            coste += demanda * distancias[nodo]
            servida += demanda
        else:
            desconectada += demanda
    return {"coste": coste, "servida": servida,
            "desconectada": desconectada, "total": total}


def coste_medio_servicio(resumen):
    if not resumen or resumen["servida"] <= 0:
        return None
    return resumen["coste"] / resumen["servida"]
