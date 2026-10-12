import os

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MODULOS_DUPLICADOS = ("calculos.py", "grafos.py", "config_aws.py",
                      "reconstruccion.py")


def _leer(carpeta, nombre):
    ruta = os.path.join(RAIZ, carpeta, nombre)
    with open(ruta, encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n")


@pytest.mark.parametrize("nombre", MODULOS_DUPLICADOS)
def test_las_dos_copias_existen(nombre):
    for carpeta in ("etl", "app"):
        assert os.path.exists(os.path.join(RAIZ, carpeta, nombre))


@pytest.mark.parametrize("nombre", MODULOS_DUPLICADOS)
def test_las_dos_copias_son_identicas(nombre):
    etl = _leer("etl", nombre)
    app = _leer("app", nombre)
    assert etl == app


def test_la_api_y_el_motor_comparten_la_definicion_del_indice():
    calculos = _leer("etl", "calculos.py")
    assert "def indice_compuesto(" in calculos
    assert "def saturacion_con_shock(" in calculos
    assert "def estres_con_aislamiento(" in calculos

    main = _leer("app", "main.py")
    motor = _leer("etl", "etl_procesamiento.py")
    assert "indice_compuesto(" in main
    assert "indice_compuesto(" in motor

    assert "estres_base * request.shock_multiplier" not in main


def test_el_simulador_recalcula_la_vulnerabilidad_tras_el_corte():
    main = _leer("app", "main.py")

    assert "coste_servicio_hinterland" in main
    assert "vulnerabilidad_corte" in main
    assert "sobrecoste_corte" in main

    assert "vulnerabilidad_base + vulnerabilidad_corte" in main


def test_la_referencia_del_corte_se_mide_con_el_mismo_clima():
    main = _leer("app", "main.py")
    assert "aplicar_clima(G_base, clima)" in main
    assert "for u, v, data in G_cut.edges(data=True)" not in main


def test_los_geojson_grandes_no_se_parsean_en_el_servidor():
    main = _leer("app", "main.py")
    assert "def responder_json_de_s3(" in main
    assert "StreamingResponse" in main
    assert "GZipMiddleware" in main
    assert "json.loads(obj['Body'].read().decode('utf-8'))" not in main.split(
        "def responder_json_de_s3")[1]


def test_lambda_de_vulnerabilidad_coincide_entre_motor_y_api():
    import re

    motor = _leer("etl", "etl_procesamiento.py")
    api = _leer("app", "main.py")

    m = re.search(r'"lambda_vulnerabilidad":\s*([0-9.]+)', motor)
    a = re.search(r'^LAMBDA_VULNERABILIDAD\s*=\s*([0-9.]+)', api, re.MULTILINE)

    assert m
    assert a
    assert float(m.group(1)) == float(a.group(1))


def test_las_vias_cortadas_se_marcan_en_vez_de_desaparecer():
    main = _leer("app", "main.py")
    assert 'props["cortada"] = True' in main
    assert "if i in vias_eliminadas: continue" not in main

    html = _leer("app", "static/index.html")
    assert "d.properties.cortada" in html


def test_el_backend_explica_que_ha_conseguido_el_corte():
    main = _leer("app", "main.py")
    assert "def diagnostico_del_corte(" in main
    assert '"diagnostico"' in main

    html = _leer("app", "static/index.html")
    assert "data.diagnostico" in html


def test_la_escala_de_color_no_se_recalcula_en_cada_escenario():
    main = _leer("app", "main.py")
    assert "def reparto_intacto(" in main
    assert "REPARTO_INTACTO" in main
    assert "p95_idx = int(len(valores_trafico) * 0.95)" not in main
    assert 'denominador_visual = referencia["p95"] * shock_multiplier' in main


def test_la_referencia_del_antes_es_siempre_la_red_intacta():
    main = _leer("app", "main.py")
    assert "trafico_por_via(grafo_base, origenes, destinos_demanda)" in main
    assert "propio=None if vias_eliminadas else" in main


def test_el_desvio_se_manda_via_a_via_y_se_pinta():
    main = _leer("app", "main.py")
    assert "def desvio_de_la_via(" in main
    assert 'props["desvio"]' in main
    assert '"vias_desviadas"' in main

    html = _leer("app", "static/index.html")
    assert "'desvio' in d.properties" in html
    assert "function textoDesvio(" in html


def test_el_simulador_pinta_el_estado_base_al_conectarse():
    main = _leer("app", "main.py")
    assert "Calculando el reparto base" in main
    html = _leer("app", "static/index.html")
    assert 'response.status === "aviso"' in html


def test_el_mapa_de_calor_tiene_UNA_sola_definicion():
    motor = _leer("etl", "etl_procesamiento.py")
    api = _leer("app", "main.py")
    calculos = _leer("etl", "calculos.py")

    assert "def intensidad_visual(" in calculos
    assert "def percentil_trafico(" in calculos

    for nombre, codigo in (("motor", motor), ("api", api)):
        assert "intensidad_visual(" in codigo

    assert "centrality[u] = max(" not in motor
    assert "sum(traficos_segmentos) / len(traficos_segmentos)" not in motor
    assert "trafico_norm = min((trafico / denominador_visual)" not in api


def test_el_copiloto_pregunta_por_el_socket_y_no_por_su_propio_post():
    html = _leer("app", "static/index.html")
    assert 'tipo_evento: "chat"' in html
    assert 'response.status === "chat"' in html
    assert "/api/chat/" not in html

    main = _leer("app", "main.py")
    assert 'tipo_evento == "chat"' in main
    assert "escenario_de_sesion" in main


def test_el_escenario_del_copiloto_lo_construye_el_servidor():
    main = _leer("app", "main.py")
    assert "session_ultimo_resultado" in main
    assert 'datos_recibidos.get("mensaje"' in main


def test_las_reglas_del_modelo_van_en_system_instruction():
    main = _leer("app", "main.py")
    assert "system_instruction=copiloto.INSTRUCCION_SISTEMA" in main
    assert "CONFIGURACION_GENERACION" in main
    assert '"temperature": 0.2' in main


def test_el_limite_de_la_consulta_es_el_mismo_en_las_dos_puntas():
    html = _leer("app", "static/index.html")
    copiloto_py = _leer("app", "copiloto.py")
    assert "MAX_LONGITUD_PREGUNTA = 500" in copiloto_py
    assert "const MAX_CONSULTA = 500" in html


def test_el_panel_respeta_los_saltos_de_linea_de_la_respuesta():
    html = _leer("app", "static/index.html")
    bloque = html[html.index(".msg-ia {"):html.index(".msg-ia {") + 400]
    assert "white-space: pre-wrap" in bloque
