import networkx as nx
from shapely.geometry import shape

DECIMALES_NODO = 5

TIPO_FERROVIARIO = "rail"
SENTIDOS_CON_IDA = ("doble", "ida")
SENTIDOS_CON_VUELTA = ("doble", "vuelta")


def _nodo(coord):
    return (round(coord[0], DECIMALES_NODO), round(coord[1], DECIMALES_NODO))


def _lineas(geom):
    if geom.geom_type == "LineString":
        return [list(geom.coords)]
    if geom.geom_type == "MultiLineString":
        return [list(l.coords) for l in geom.geoms]
    return []


def peso_por_segmento(propiedades, total_segmentos):
    if total_segmentos <= 0:
        return 0.0

    total = propiedades.get("peso_logistico_total")
    if total is None:
        media = propiedades.get("peso_logistico_real", 1.0) or 1.0
        total = float(media) * total_segmentos
    return float(total) / total_segmentos


def construir_grafo_desde_geojson(features, incluir_ferrocarril=False):
    grafo = nx.DiGraph()
    geometrias = []
    nodos = set()

    for indice, feature in enumerate(features):
        try:
            geom = shape(feature["geometry"])
        except Exception:
            geometrias.append(None)
            continue
        geometrias.append(geom)

        try:
            propiedades = feature.get("properties", {}) or {}
            tipo_via = propiedades.get("tipo_via", "unclassified")
            if tipo_via == TIPO_FERROVIARIO and not incluir_ferrocarril:
                continue

            lineas = _lineas(geom)
            total_segmentos = sum(len(coords) - 1 for coords in lineas)
            if total_segmentos <= 0:
                continue

            peso = peso_por_segmento(propiedades, total_segmentos)
            sentido = propiedades.get("sentido", "doble")

            for coords in lineas:
                for j in range(len(coords) - 1):
                    u, v = _nodo(coords[j]), _nodo(coords[j + 1])
                    if sentido in SENTIDOS_CON_IDA:
                        grafo.add_edge(u, v, weight=peso, feature_idx=indice,
                                       tipo_via=tipo_via)
                    if sentido in SENTIDOS_CON_VUELTA:
                        grafo.add_edge(v, u, weight=peso, feature_idx=indice,
                                       tipo_via=tipo_via)
                    nodos.add(u)
                    nodos.add(v)
        except Exception:
            continue

    return grafo, geometrias, nodos


def podar_componente_principal(grafo):
    if len(grafo.nodes) == 0:
        return grafo, set()
    componentes = list(nx.weakly_connected_components(grafo))
    if not componentes:
        return grafo, set(grafo.nodes)
    principal = grafo.subgraph(max(componentes, key=len)).copy()
    return principal, set(principal.nodes)
