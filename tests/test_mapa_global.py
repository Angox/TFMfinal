import io
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "etl"))

import compilar_mapa_global as mapa

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class CuerpoFalso:
    def __init__(self, texto):
        self.texto = texto

    def read(self):
        return self.texto.encode("utf-8")


class PaginadorFalso:
    def __init__(self, paginas):
        self.paginas = paginas

    def paginate(self, **_kwargs):
        return list(self.paginas)


class S3Falso:
    def __init__(self, objetos, paginas=None):
        self.objetos = objetos
        self.descargas = []
        self.paginas = paginas or [{
            "Contents": [{"Key": k, "Size": len(v)} for k, v in objetos.items()]
        }]

    def get_paginator(self, _nombre):
        return PaginadorFalso(self.paginas)

    def get_object(self, Bucket=None, Key=None):
        self.descargas.append(Key)
        return {"Body": CuerpoFalso(self.objetos[Key])}


def coleccion(*features):
    return json.dumps({"type": "FeatureCollection", "features": list(features)})


def via(trafico=10.0, tipo="motorway", coords=None, **extras):
    if coords is None:
        coords = [[4.123456789, 51.987654321], [4.223456789, 51.887654321]]
    propiedades = {"trafico": trafico, "tipo_via": tipo,
                   "nombre_via": "A-42", "peaje": None,
                   "peso_logistico_real": 1.5, "peso_logistico_total": 30.0,
                   "n_segmentos": 20, "sentido": "doble"}
    propiedades.update(extras)
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": propiedades,
    }


def test_listar_rutas_recorre_todas_las_paginas_y_suma_el_peso():
    paginas = [
        {"Contents": [{"Key": "p/a.json", "Size": 10},
                      {"Key": "p/", "Size": 0}]},
        {"Contents": [{"Key": "p/b.json", "Size": 32},
                      {"Key": "p/notas.txt", "Size": 999}]},
    ]
    s3 = S3Falso({}, paginas=paginas)

    claves, total = mapa.listar_rutas(s3)

    assert claves == ["p/a.json", "p/b.json"]
    assert total == 42


def test_el_volcado_escribe_una_linea_por_via_y_solo_las_dos_propiedades(tmp_path):
    s3 = S3Falso({
        "p/uno.json": coleccion(via(trafico=12.345), via(trafico=0.0)),
        "p/dos.json": coleccion(via(trafico=90.0, tipo="rail")),
    })
    destino = tmp_path / "global.geojson"

    puertos, features = mapa.volcar_geojson(s3, list(s3.objetos), str(destino))

    assert (puertos, features) == (2, 3)
    lineas = destino.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 3

    primera = json.loads(lineas[0])
    assert set(primera["properties"]) == set(mapa.PROPIEDADES_MAPA)
    assert primera["properties"]["trafico"] == 12.35
    assert primera["geometry"]["coordinates"][0] == [4.12346, 51.98765]


def test_el_volcado_no_acumula_las_features_del_catalogo(tmp_path):
    escrito_al_leer = []
    destino = tmp_path / "global.geojson"

    class S3Espia(S3Falso):
        def get_object(self, Bucket=None, Key=None):
            escrito_al_leer.append(
                os.path.getsize(destino) if destino.exists() else 0)
            return super().get_object(Bucket=Bucket, Key=Key)

    gorda = via(coords=[[i / 1000.0, i / 1000.0] for i in range(2000)])
    s3 = S3Espia({f"p/{i}.json": coleccion(gorda, gorda) for i in range(6)})
    mapa.volcar_geojson(s3, list(s3.objetos), str(destino), paralelas=1)

    assert escrito_al_leer[-1] > 0
    assert escrito_al_leer == sorted(escrito_al_leer)


def test_el_umbral_de_trafico_recorta_la_malla_sin_reparto(tmp_path):
    s3 = S3Falso({"p/uno.json": coleccion(via(trafico=0.0), via(trafico=55.0))})
    destino = tmp_path / "global.geojson"

    _puertos, features = mapa.volcar_geojson(
        s3, list(s3.objetos), str(destino), trafico_minimo=1.0)

    assert features == 1


def test_iterar_features_devuelve_lo_mismo_que_json_loads():
    texto = coleccion(via(trafico=1.0), via(trafico=2.0), via(trafico=3.0))
    assert list(mapa.iterar_features(texto)) == json.loads(texto)["features"]


def test_iterar_features_no_decodifica_por_delante():
    bueno = json.dumps(via(trafico=1.0))
    texto = ('{"type":"FeatureCollection","features":['
             + bueno + "," + bueno + ",{roto}]}")

    generador = mapa.iterar_features(texto)
    assert next(generador)["properties"]["trafico"] == 1.0
    assert next(generador)["properties"]["trafico"] == 1.0
    with pytest.raises(json.JSONDecodeError):
        next(generador)


def test_iterar_features_aguanta_una_coleccion_vacia():
    assert list(mapa.iterar_features(coleccion())) == []
    assert list(mapa.iterar_features("{}")) == []


def test_adelgazar_descarta_lo_que_no_se_puede_pintar():
    assert mapa.adelgazar(via(coords=[])) is None
    assert mapa.adelgazar({"type": "Feature", "properties": {}}) is None
    assert mapa.adelgazar(via(trafico=3.0), trafico_minimo=10.0) is None


def test_adelgazar_no_inventa_un_tipo_de_via():
    magra = mapa.adelgazar(via(tipo=None))
    assert magra["properties"]["tipo_via"] == "unclassified"

    ferro = mapa.adelgazar(via(tipo="rail"))
    assert ferro["properties"]["tipo_via"] == "rail"


def test_adelgazar_conserva_las_multilineas():
    multi = {"type": "Feature",
             "geometry": {"type": "MultiLineString",
                          "coordinates": [[[1.111111111, 2.222222222],
                                           [3.333333333, 4.444444444]]]},
             "properties": {"trafico": 5, "tipo_via": "trunk"}}
    magra = mapa.adelgazar(multi)
    assert magra["geometry"]["type"] == "MultiLineString"
    assert magra["geometry"]["coordinates"] == [[[1.11111, 2.22222],
                                                 [3.33333, 4.44444]]]


def test_el_comando_de_tippecanoe_acota_zoom_y_temporales():
    comando = mapa.comando_tippecanoe("entrada.geojson", "salida.pmtiles",
                                      zoom=12, temporal="/mnt/pmtiles")

    assert "--read-parallel" in comando
    assert "--drop-densest-as-needed" in comando
    assert comando[comando.index("-z") + 1] == "12"
    assert "-zg" not in comando and "--extend-zooms-if-still-dropping" not in comando
    assert comando[comando.index("--temporary-directory") + 1] == "/mnt/pmtiles"
    assert comando[comando.index("-l") + 1] == mapa.CAPA_TESELAS


def _js_del_mapa():
    ruta = os.path.join(RAIZ, "app", "static", "index.html")
    html = io.open(ruta, encoding="utf-8").read()
    inicio = html.find("CAPA_CARRETERAS_MAPLIBRE")
    fin = html.find("let deckgl")
    assert inicio != -1 and fin > inicio
    return html[inicio:fin]


def test_el_frontend_no_lee_ninguna_propiedad_que_el_pmtiles_ya_no_lleve():
    leidas = set(re.findall(r"\['get',\s*'([^']+)'\]", _js_del_mapa()))
    assert leidas
    assert leidas <= set(mapa.PROPIEDADES_MAPA)


def test_la_capa_de_las_teselas_se_llama_igual_en_los_dos_lados():
    capas = set(re.findall(r"'source-layer':\s*'([^']+)'", _js_del_mapa()))
    assert capas == {mapa.CAPA_TESELAS}
