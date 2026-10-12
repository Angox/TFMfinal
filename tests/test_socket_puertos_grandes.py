import asyncio
import functools
import json
import os
import random
import sys
import threading
import time
import types
from unittest import mock

import pytest

import networkx
import shapely.geometry

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(RAIZ, "app"))

from reconstruccion import (
    construir_grafo_desde_geojson,
    podar_componente_principal,
)

N = 18
PASO = 0.004
LON0, LAT0 = 8.90, 44.40


def _leer(carpeta, nombre):
    with open(os.path.join(RAIZ, carpeta, nombre), encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n")


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
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString",
                                 "coordinates": [_punto(*a), _punto(*b)]},
                    "properties": {"tipo_via": "residential", "sentido": "doble",
                                   "nombre_via": "v%d" % len(features)},
                })

    grafo, geometrias, nodos = construir_grafo_desde_geojson(features)
    grafo, nodos = podar_componente_principal(grafo)

    def mas_cercano(x, y):
        o = _punto(x, y)
        return min(nodos, key=lambda n: (n[0] - o[0]) ** 2 + (n[1] - o[1]) ** 2)

    nodo_puerto = mas_cercano(0, 0)
    rnd = random.Random(7)
    industrias = {"type": "FeatureCollection", "features": []}
    mapeadas = []
    for _ in range(120):
        x, y = rnd.randrange(N), rnd.randrange(2, N)
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


CORTE = [[_punto(-0.5, 9), _punto(12.5, 9)]]


N_DENSO = 30
TROZOS_DENSO = 8
CORTE_DENSO = [[_punto(-0.5, 15), _punto(18.5, 15)]]


@pytest.fixture(scope="module")
def puerto_denso(simulador):
    def tramo(a, b):
        pa, pb = _punto(*a), _punto(*b)
        return [[round(pa[0] + (pb[0] - pa[0]) * k / TROZOS_DENSO, 8),
                 round(pa[1] + (pb[1] - pa[1]) * k / TROZOS_DENSO, 8)]
                for k in range(TROZOS_DENSO + 1)]

    features = []
    for x in range(N_DENSO):
        for y in range(N_DENSO):
            for a, b in (((x, y), (x + 1, y)), ((x, y), (x, y + 1))):
                if max(a[0], b[0]) >= N_DENSO or max(a[1], b[1]) >= N_DENSO:
                    continue
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": tramo(a, b)},
                    "properties": {"tipo_via": "residential", "sentido": "doble",
                                   "nombre_via": "v%d" % len(features)},
                })

    grafo, geometrias, nodos = construir_grafo_desde_geojson(features)
    grafo, nodos = podar_componente_principal(grafo)

    def mas_cercano(x, y):
        o = _punto(x, y)
        return min(nodos, key=lambda n: (n[0] - o[0]) ** 2 + (n[1] - o[1]) ** 2)

    nodo_puerto = mas_cercano(0, 0)
    rnd = random.Random(7)
    industrias = {"type": "FeatureCollection", "features": []}
    mapeadas = []
    for _ in range(120):
        x, y = rnd.randrange(N_DENSO), rnd.randrange(2, N_DENSO)
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


def test_sin_geojson_el_resultado_es_el_mismo_pero_sin_las_geometrias(simulador, puerto):
    entero = simulador.calcular_impacto_dinamico("P", CORTE, "despejado", puerto, 1.0)

    simulador.REPARTO_INTACTO.clear()
    simulador.COSTE_INTACTO.clear()
    solo_delta = simulador.calcular_impacto_dinamico(
        "P", CORTE, "despejado", puerto, 1.0, incluir_geojson=False)

    assert "rutas_simuladas" in entero
    assert "rutas_simuladas" not in solo_delta
    assert solo_delta["delta_rutas"] == entero["delta_rutas"]
    for clave, valor in entero.items():
        if clave == "rutas_simuladas":
            continue
        assert solo_delta[clave] == valor


def test_el_delta_pesa_muchisimo_menos_que_el_geojson(simulador, puerto):
    r = simulador.calcular_impacto_dinamico("P", CORTE, "despejado", puerto, 1.0)
    delta = len(json.dumps(r["delta_rutas"]))
    entero = len(json.dumps(r["rutas_simuladas"]))
    assert entero > 10 * delta


def test_sin_cortes_no_se_clona_el_grafo(simulador, puerto):
    with mock.patch.object(simulador.nx, "subgraph_view",
                           wraps=simulador.nx.subgraph_view) as espia:
        simulador.calcular_impacto_dinamico("P", [], "despejado", puerto, 1.0)
        assert espia.call_count == 0

        simulador.REPARTO_INTACTO.clear()
        simulador.COSTE_INTACTO.clear()
        simulador.calcular_impacto_dinamico("P", CORTE, "despejado", puerto, 1.0)
        assert espia.call_count == 1


class _SocketFalso:
    def __init__(self):
        self.enviados = []

    async def send_json(self, payload):
        self.enviados.append(payload)


async def _en_hilo(funcion, *args, **kwargs):
    bucle = asyncio.get_event_loop()
    return await bucle.run_in_executor(None, functools.partial(funcion, *args, **kwargs))


def test_un_calculo_largo_manda_latidos_y_devuelve_el_resultado(simulador):
    socket = _SocketFalso()

    def tarda():
        time.sleep(0.35)
        return {"listo": True}

    with mock.patch.object(simulador, "run_in_threadpool", _en_hilo), \
         mock.patch.object(simulador, "INTERVALO_LATIDO_WS", 0.1):
        resultado = asyncio.run(
            simulador.calcular_con_latido(socket, "Cortando red...", tarda))

    assert resultado == {"listo": True}
    assert len(socket.enviados) >= 2
    assert all(m == {"status": "processing", "fase": "Cortando red..."}
               for m in socket.enviados)


def test_un_calculo_corto_no_manda_ningun_latido(simulador):
    socket = _SocketFalso()

    with mock.patch.object(simulador, "run_in_threadpool", _en_hilo), \
         mock.patch.object(simulador, "INTERVALO_LATIDO_WS", 5):
        resultado = asyncio.run(
            simulador.calcular_con_latido(socket, "fase", lambda: 42))

    assert resultado == 42
    assert socket.enviados == []


def test_si_el_socket_se_cae_el_fallo_sale_a_la_superficie(simulador):
    socket = _SocketFalso()

    async def revienta(_payload):
        raise ConnectionResetError("socket cerrado")

    socket.send_json = revienta

    with mock.patch.object(simulador, "run_in_threadpool", _en_hilo), \
         mock.patch.object(simulador, "INTERVALO_LATIDO_WS", 0.05):
        with pytest.raises(ConnectionResetError):
            asyncio.run(simulador.calcular_con_latido(
                socket, "fase", lambda: time.sleep(0.3)))


def test_el_websocket_pide_el_calculo_sin_geojson():
    main = _leer("app", "main.py")
    llamadas = [bloque[:400] for bloque in main.split("await calcular_con_latido(")[1:]
                if "calcular_impacto_dinamico" in bloque[:400]]
    assert len(llamadas) == 2
    for numero, llamada in enumerate(llamadas, start=1):
        assert "incluir_geojson=False" in llamada
    assert 'del resultado["rutas_simuladas"]' not in main

    html = _leer("app", "static/index.html")
    assert "function aplicarDelta(" in html
    assert "data.rutas_simuladas" in html


def test_la_reconexion_con_cortes_se_salta_el_reparto_base():
    main = _leer("app", "main.py")
    bloque = main.split('if datos_recibidos.get("cortes_pendientes"):')[1][:400]
    assert "continue" in bloque

    html = _leer("app", "static/index.html")
    assert "cortes_pendientes: cortesDeLaSesion.length > 0" in html


def test_el_reparto_puede_llegar_antes_que_las_geometrias():
    html = _leer("app", "static/index.html")
    assert "deltaPendiente" in html
    assert ("if (deltaPendiente) { aplicarDelta(deltaPendiente); deltaPendiente = null; }"
            in html)


def test_el_reset_devuelve_tambien_el_shock_y_el_clima():
    main = _leer("app", "main.py")
    bloque = main.split('elif tipo_evento == "reset_cortes":')[1][:600]
    assert "session_shock = 1.0" in bloque
    assert "session_clima = clima_real_actual" in bloque


def test_la_via_cortada_se_va_del_mapa():
    html = _leer("app", "static/index.html")
    assert "const rutasVisibles = geojsonRutasActual.features.filter(" in html
    assert "data: rutasVisibles," in html
    assert "feat.properties.cortada = !!(update && update.cortada);" in html
    assert "if (d.properties.cortada) return [0, 0, 0, 255];" in html


def test_las_vias_desviadas_vuelven_a_la_escala_de_color():
    html = _leer("app", "static/index.html")
    assert "Math.round(168 + 60 * f)" not in html
    assert "if ('desvio' in d.properties) return 6;" in html

    main = _leer("app", "main.py")
    assert "violeta" not in main


def test_calculos_simultaneos_sobre_el_mismo_puerto_no_se_corrompen(simulador, puerto_denso):
    from grafos import NODO_SUPERFUENTE

    for ronda in range(2):
        simulador.REPARTO_INTACTO.clear()
        simulador.COSTE_INTACTO.clear()
        resultados, errores = [], []
        cerrojo = threading.Lock()

        def trabajo():
            try:
                r = simulador.calcular_impacto_dinamico(
                    "D", CORTE_DENSO, "despejado", puerto_denso, 1.0,
                    incluir_geojson=False)
                with cerrojo:
                    resultados.append(r)
            except Exception as e:
                with cerrojo:
                    errores.append("%s: %s" % (type(e).__name__, e))

        hilos = [threading.Thread(target=trabajo) for _ in range(4)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(timeout=180)

        assert not errores
        assert len(resultados) == 4
        primero = resultados[0]
        for otro in resultados[1:]:
            assert otro == primero

        assert NODO_SUPERFUENTE not in puerto_denso[4]


def test_un_calculo_que_ya_no_espera_nadie_se_abandona(simulador, puerto):
    with pytest.raises(simulador.CalculoAbandonado):
        simulador.calcular_impacto_dinamico(
            "P", CORTE, "despejado", puerto, 1.0, incluir_geojson=False,
            sigue_interesando=lambda: False)


def test_abandonar_libera_el_turno_al_siguiente(simulador, puerto):
    with pytest.raises(simulador.CalculoAbandonado):
        simulador.calcular_impacto_dinamico(
            "P", CORTE, "despejado", puerto, 1.0, incluir_geojson=False,
            sigue_interesando=lambda: False)

    assert simulador.CERROJO_MOTOR.acquire(timeout=5)
    simulador.CERROJO_MOTOR.release()

    r = simulador.calcular_impacto_dinamico(
        "P", CORTE, "despejado", puerto, 1.0, incluir_geojson=False)
    assert r["vias_afectadas"] > 0


def test_el_socket_avisa_al_motor_de_que_ya_no_le_espera_nadie():
    main = _leer("app", "main.py")
    assert 'sesion_viva = {"ok": True}' in main
    assert 'sesion_viva["ok"] = False' in main
    cola = main[main.rindex("except CalculoAbandonado"):]
    assert "finally:" in cola and 'sesion_viva["ok"] = False' in cola

    assert main.count("sigue_interesando=hace_falta_todavia") == 2


def test_el_contador_de_reintentos_no_se_reinicia_con_el_saludo():
    html = _leer("app", "static/index.html")
    saludo = html.split('if (response.status === "auth_ok") {')[1].split("} else if")[0]
    assert "reconexionesSeguidas = 0" not in saludo

    exito = html.split('} else if (response.status === "success") {')[1][:600]
    assert "reconexionesSeguidas = 0" in exito


def test_el_cierre_del_socket_dice_por_que():
    html = _leer("app", "static/index.html")
    assert "socketSimulador.onclose = (evento) => {" in html
    assert "evento.code" in html and "evento.wasClean" in html
    assert "ultimoCierreWS" in html


def _barrido_completo(simulador, nodos, lon, lat, lon_ref, lat_ref):
    from calculos import proyectar_local
    objetivo = proyectar_local(lon, lat, lon_ref, lat_ref)
    return min(nodos,
               key=lambda n: simulador._distancia2_proyectada(n, objetivo,
                                                              lon_ref, lat_ref))


LATITUDES = [("Santos", -46.30, -23.95), ("Génova", 8.90, 44.40),
             ("Narvik", 17.42, 68.44), ("Guayaquil", -79.90, -2.19)]


@pytest.mark.parametrize("etiqueta,lon_ref,lat_ref", LATITUDES)
def test_el_nodo_mas_cercano_es_el_mismo_que_daba_el_barrido(simulador, etiqueta,
                                                             lon_ref, lat_ref):
    rnd = random.Random(19)
    nodos = []
    for _ in range(4000):
        lon = lon_ref + rnd.uniform(-0.25, 0.25)
        lat = lat_ref + rnd.uniform(-0.25, 0.25)
        if abs(lon - lon_ref) < 0.06 and abs(lat - lat_ref) < 0.06:
            continue
        nodos.append((round(lon, 7), round(lat, 7)))

    rejilla = simulador.construir_rejilla(nodos, lon_ref, lat_ref)

    puntos = []
    for i in range(60):
        if i % 3 == 0:
            puntos.append((lon_ref + rnd.uniform(-0.05, 0.05),
                           lat_ref + rnd.uniform(-0.05, 0.05)))
        elif i % 3 == 1:
            puntos.append((lon_ref + rnd.uniform(-1.5, 1.5),
                           lat_ref + rnd.uniform(-1.5, 1.5)))
        else:
            puntos.append((lon_ref + rnd.uniform(-0.25, 0.25),
                           lat_ref + rnd.uniform(-0.25, 0.25)))

    from calculos import proyectar_local
    for lon, lat in puntos:
        esperado = _barrido_completo(simulador, nodos, lon, lat, lon_ref, lat_ref)
        obtenido = simulador.nodo_mas_cercano(rejilla, lon, lat)
        if obtenido == esperado:
            continue
        objetivo = proyectar_local(lon, lat, lon_ref, lat_ref)
        d_esperada = simulador._distancia2_proyectada(esperado, objetivo,
                                                      lon_ref, lat_ref)
        d_obtenida = simulador._distancia2_proyectada(obtenido, objetivo,
                                                      lon_ref, lat_ref)
        assert d_obtenida <= d_esperada + 1e-12


def test_buscar_lejos_de_la_red_no_barre_todos_los_nodos(simulador):
    rnd = random.Random(3)
    nodos = [(round(8.90 + rnd.uniform(-0.2, 0.2), 7),
              round(44.40 + rnd.uniform(-0.2, 0.2), 7)) for _ in range(20000)]
    rejilla = simulador.construir_rejilla(nodos, 8.90, 44.40)

    medidos = []
    original = simulador._distancia2_proyectada

    def espia(nodo, objetivo, lon_ref, lat_ref):
        medidos.append(nodo)
        return original(nodo, objetivo, lon_ref, lat_ref)

    with mock.patch.object(simulador, "_distancia2_proyectada", espia):
        assert simulador.nodo_mas_cercano(rejilla, 10.5, 45.9) is not None

    assert len(medidos) < len(nodos) / 4


def test_la_rejilla_indexa_con_enteros_y_no_con_redondeos():
    main = _leer("app", "main.py")
    assert "int(math.floor(n[0] / LADO_CELDA))" in main
    assert "round(cx + dx, 2)" not in main
    assert "candidatos = nodos_lista" not in main


def test_el_keepalive_del_servidor_tiene_margen():
    dockerfile = _leer("app", "Dockerfile")
    orden = [l for l in dockerfile.splitlines() if l.startswith("CMD [")]
    assert len(orden) == 1
    argumentos = json.loads(orden[0][len("CMD "):])

    def valor(bandera):
        assert bandera in argumentos
        return float(argumentos[argumentos.index(bandera) + 1])

    assert valor("--ws-ping-timeout") >= 120
    assert valor("--ws-ping-interval") >= 20
    assert valor("--ws-max-queue") >= 128


TRAFICO_TREN_DEL_ETL = 63.5


@pytest.fixture
def puerto_con_tren(simulador):
    simulador.REPARTO_INTACTO.clear()
    simulador.COSTE_INTACTO.clear()

    features = []
    for x in range(N):
        for y in range(N):
            for a, b in (((x, y), (x + 1, y)), ((x, y), (x, y + 1))):
                if max(a[0], b[0]) >= N or max(a[1], b[1]) >= N:
                    continue
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString",
                                 "coordinates": [_punto(*a), _punto(*b)]},
                    "properties": {"tipo_via": "residential", "sentido": "doble",
                                   "nombre_via": "v%d" % len(features),
                                   "trafico": 40.0},
                })

    indice_tren = len(features)
    features.append({
        "type": "Feature",
        "geometry": {"type": "LineString",
                     "coordinates": [_punto(x, 3.4) for x in range(N)]},
        "properties": {"tipo_via": "rail", "sentido": "doble",
                       "nombre_via": "ferrocarril",
                       "trafico": TRAFICO_TREN_DEL_ETL},
    })

    grafo, geometrias, nodos = construir_grafo_desde_geojson(features)
    grafo, nodos = podar_componente_principal(grafo)

    def mas_cercano(x, y):
        o = _punto(x, y)
        return min(nodos, key=lambda n: (n[0] - o[0]) ** 2 + (n[1] - o[1]) ** 2)

    nodo_puerto = mas_cercano(0, 0)
    rnd = random.Random(7)
    industrias = {"type": "FeatureCollection", "features": []}
    mapeadas = []
    for _ in range(80):
        x, y = rnd.randrange(N), rnd.randrange(2, N)
        mapeadas.append(mas_cercano(x, y))
        industrias["features"].append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": _punto(x, y)},
            "properties": {"demanda_teus": rnd.lognormvariate(4, 1.2)},
        })

    detalle = {"volumen_diario_movible": 50000, "capacidad_diaria": 60000,
               "vulnerabilidad": 0.3, "saturacion": 0.5,
               "puertas_reales": [list(nodo_puerto)]}
    puerto = ({"type": "FeatureCollection", "features": features}, detalle,
              industrias, {"lat": LAT0, "lng": LON0}, grafo, mapeadas,
              nodo_puerto, geometrias)
    return puerto, indice_tren


def test_el_reparto_base_no_apaga_la_saturacion_del_tren(simulador, puerto_con_tren):
    puerto, indice_tren = puerto_con_tren
    base = simulador.calcular_impacto_dinamico("T", [], "despejado", puerto, 1.0)

    props_tren = base["rutas_simuladas"]["features"][indice_tren]["properties"]
    assert props_tren["tipo_via"] == "rail"
    assert props_tren["trafico"] == TRAFICO_TREN_DEL_ETL

    assert str(indice_tren) not in base["delta_rutas"]

    viales = [str(i) for i in base["delta_rutas"] if i != str(indice_tren)]
    assert viales


def test_un_corte_sobre_la_via_de_tren_la_marca_pero_no_inventa_trafico(
        simulador, puerto_con_tren):
    puerto, indice_tren = puerto_con_tren
    corte = [[_punto(6, 2.5), _punto(6, 4.5)]]
    cortado = simulador.calcular_impacto_dinamico("T", corte, "despejado", puerto, 1.0)

    delta_tren = cortado["delta_rutas"].get(str(indice_tren))
    assert delta_tren is not None
    assert delta_tren["cortada"] is True


def test_el_cliente_no_toca_nunca_el_trafico_del_tren():
    html = _leer("app", "static/index.html")
    cuerpo = html.split("function aplicarDelta(")[1].split("\n    }")[0]
    assert "if (feat.properties.tipo_via === 'rail') return;" in cuerpo
    assert "feat.properties.cortada = !!(update && update.cortada);" in cuerpo
    assert "delete feat.properties.desvio;" in cuerpo
    assert (cuerpo.index("tipo_via === 'rail') return;")
            < cuerpo.index("feat.properties.trafico = update ?"))
