import os
import sys
import types
from unittest import mock

import pytest

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(RAIZ, "etl"))


def _modulo_falso(nombre, atributos=None):
    m = types.ModuleType(nombre)
    for k, v in (atributos or {}).items():
        setattr(m, k, v)
    return m


@pytest.fixture(scope="module")
def motor():
    pesados = {
        "boto3": _modulo_falso("boto3", {"client": lambda *a, **k: mock.MagicMock()}),
        "networkx": mock.MagicMock(),
        "rasterio": mock.MagicMock(),
        "rasterio.session": _modulo_falso("rasterio.session", {"AWSSession": mock.MagicMock()}),
        "rasterio.windows": _modulo_falso("rasterio.windows", {"from_bounds": mock.MagicMock()}),
        "rasterio.transform": _modulo_falso("rasterio.transform", {"rowcol": mock.MagicMock()}),
        "pycountry": mock.MagicMock(),
        "reverse_geocoder": mock.MagicMock(),
        "shapely": mock.MagicMock(),
        "shapely.geometry": mock.MagicMock(),
        "scipy": mock.MagicMock(),
        "scipy.spatial": _modulo_falso("scipy.spatial", {"cKDTree": mock.MagicMock()}),
        "duckdb": mock.MagicMock(),
        "requests": _modulo_falso("requests", {"get": mock.MagicMock()}),
    }
    os.environ.setdefault("S3_BUCKET_NAME", "bucket-de-pruebas")
    os.environ.setdefault("AWS_REGION", "us-west-2")
    with mock.patch.dict(sys.modules, pesados):
        import etl_procesamiento
        yield etl_procesamiento


def test_aplicar_parametros_sobrescribe_y_restaura(motor):
    original = motor.PARAMETROS["cuota_tren"]
    motor.aplicar_parametros({"cuota_tren": 0.55})
    assert motor.PARAMETROS["cuota_tren"] == 0.55
    motor.aplicar_parametros()
    assert motor.PARAMETROS["cuota_tren"] == original


def test_aplicar_parametros_rechaza_nombres_desconocidos(motor):
    with pytest.raises(KeyError):
        motor.aplicar_parametros({"cuota_tren_typo": 0.5})
    motor.aplicar_parametros()


def test_los_parametros_base_no_se_contaminan(motor):
    motor.aplicar_parametros({"peso_saturacion": 99.0})
    assert motor.PARAMETROS_BASE["peso_saturacion"] == 5.0
    motor.aplicar_parametros()


def _codigo_motor():
    ruta = os.path.join(RAIZ, "etl", "etl_procesamiento.py")
    with open(ruta, encoding="utf-8") as f:
        return f.read()


def test_no_quedan_constantes_magicas_en_el_motor():
    codigo = _codigo_motor()
    for constante in ("* 8000.0", "= 999999.0", "cuota_tren = 0.20", "* 3.5"):
        assert constante not in codigo
    assert codigo.count("PARAMETROS[") > 15


def test_el_exponente_de_gravedad_no_esta_incrustado():
    codigo = _codigo_motor()
    assert "coste_total ** 2" not in codigo
    assert 'PARAMETROS["exponente_gravedad"]' in codigo


def test_la_resolucion_de_la_cache_raster_es_parametrica():
    codigo = _codigo_motor()
    assert "round(lat,2)" not in codigo
    assert "round(lat, 2)" not in codigo
    assert 'PARAMETROS["decimales_cache_raster"]' in codigo


@pytest.mark.parametrize("parametro", [
    "exponente_gravedad",
    "lambda_vulnerabilidad",
    "penalizacion_desconexion",
    "n_aristas_criticas",
    "radio_buffer_puertas_km",
    "pendiente_maxima_camion",
    "pendiente_maxima_tren",
    "friccion_ultima_milla",
    "decimales_cache_raster",
    "ventana_poblacion_px",
    "altitud_minima_valida",
    "min_dias_base_capacidad",
    "incluir_comercio_minorista",
])
def test_los_parametros_nuevos_existen(motor, parametro):
    assert parametro in motor.PARAMETROS_BASE


def _codigo_sensibilidad():
    ruta = os.path.join(RAIZ, "etl", "analisis_sensibilidad.py")
    with open(ruta, encoding="utf-8") as f:
        return f.read()


def test_los_parametros_dominantes_entran_en_la_sensibilidad():
    codigo = _codigo_sensibilidad()
    for parametro in ("beta_disuasion", "lambda_vulnerabilidad",
                      "radio_buffer_puertas_km", "friccion_ultima_milla",
                      "dias_ventana_carga"):
        assert f'"{parametro}"' in codigo


def test_el_oat_solo_audita_parametros_activos(motor):
    codigo = _codigo_sensibilidad()
    lista = codigo.split("PARAMETROS_SENSIBLES = [")[1].split("]")[0]

    assert motor.PARAMETROS_BASE["funcion_disuasion"] == "exponencial"
    assert '"exponente_gravedad"' not in lista
    assert '"beta_disuasion"' in lista


def test_hay_una_ablacion_que_compara_las_dos_funciones_de_disuasion():
    codigo = _codigo_sensibilidad()
    assert "gravedad_potencia_inversa" in codigo
    assert '"funcion_disuasion": "potencia"' in codigo


def test_la_sensibilidad_recalcula_el_perfil_de_volumen():
    ruta = os.path.join(RAIZ, "etl", "analisis_sensibilidad.py")
    with open(ruta, encoding="utf-8") as f:
        codigo = f.read()
    assert "serie_diaria" in codigo
    assert "motor.calcular_volumenes(" in codigo.split("def ejecutar_escenario")[1]


def test_calcular_volumenes_separa_carga_movible_y_directa(motor):
    motor.aplicar_parametros()
    puerto = {
        "vessel_count_container": "365",
        "vessel_count_RoRo": "0",
        "vessel_count_general_cargo": "0",
        "vessel_count_dry_bulk": "365",
        "vessel_count_tanker": "0",
    }
    vol = motor.calcular_volumenes(puerto)
    assert vol["volumen_diario_movible"] == 2000
    assert vol["volumen_diario_directo"] == 300


def test_calcular_volumenes_tolera_los_nulos_del_fmi(motor):
    motor.aplicar_parametros()
    vol = motor.calcular_volumenes({"vessel_count_container": "nan",
                                    "vessel_count_RoRo": None})
    assert vol["volumen_diario_movible"] == 0
    assert vol["total_barcos"] == 1.0


def test_los_coeficientes_de_teus_son_parametrizables(motor):
    puerto = {"vessel_count_container": "365"}
    base = motor.calcular_volumenes(puerto)["volumen_diario_movible"]
    motor.aplicar_parametros({"teus_por_buque_container": 4.0})
    doble = motor.calcular_volumenes(puerto)["volumen_diario_movible"]
    motor.aplicar_parametros()
    assert doble == pytest.approx(2 * base, rel=0.01)


def test_todas_las_ablaciones_usan_parametros_reales(motor):
    sys.path.insert(0, os.path.join(RAIZ, "etl"))
    with mock.patch.dict(sys.modules, {"etl_procesamiento": motor}):
        import analisis_sensibilidad as sens

    for nombre, sobrescrituras in sens.ABLACIONES.items():
        desconocidos = set(sobrescrituras) - set(motor.PARAMETROS_BASE)
        assert not desconocidos

    for parametro in sens.PARAMETROS_SENSIBLES:
        assert parametro in motor.PARAMETROS_BASE


def test_el_baseline_anula_toda_la_friccion(motor):
    with mock.patch.dict(sys.modules, {"etl_procesamiento": motor}):
        import analisis_sensibilidad as sens

    baseline = sens.ABLACIONES["baseline_distancia_pura"]
    for clave in ("friccion_autopista", "friccion_primaria", "friccion_secundaria",
                  "penalizacion_tonelaje_limitado", "penalizacion_sin_pavimentar",
                  "penalizacion_hgv_restringido"):
        assert baseline[clave] == 1.0
    assert baseline["factor_pendiente_camion"] == 0.0
    assert baseline["divisor_poblacion"] == float("inf")


def test_divisor_poblacion_infinito_anula_la_penalizacion_urbana():
    assert 1 + (5000.0 / float("inf")) == 1.0


def test_factor_pendiente_cero_anula_la_penalizacion_topografica():
    pendiente = 0.08
    assert 1 + (0.0 * pendiente) == 1.0


def _sensibilidad():
    import importlib
    import sys as _sys
    _sys.path.insert(0, os.path.join(RAIZ, "etl"))
    return importlib.import_module("analisis_sensibilidad")


def test_un_percentil_no_se_perturba_multiplicando(motor):
    sens = _sensibilidad()
    bajo, alto = sens.perturbaciones("percentil_capacidad", 0.95)
    assert 0.0 < bajo < 1.0
    assert 0.0 < alto < 1.0
    assert bajo < alto
    assert (bajo, alto) == (0.90, 0.99)


def test_los_parametros_sin_cota_siguen_con_el_mas_menos_30(motor):
    sens = _sensibilidad()
    bajo, alto = sens.perturbaciones("friccion_autopista", 0.4)
    assert bajo == pytest.approx(0.4 * 0.7)
    assert alto == pytest.approx(0.4 * 1.3)


def test_los_parametros_acotados_no_se_salen_de_su_intervalo(motor):
    sens = _sensibilidad()
    for parametro, (minimo, maximo) in sens.LIMITES.items():
        for valor_base in (minimo, maximo, (minimo + maximo) / 2):
            bajo, alto = sens.perturbaciones(parametro, valor_base)
            assert minimo <= bajo <= maximo
            assert minimo <= alto <= maximo


def test_todo_parametro_sensible_produce_perturbaciones_validas(motor):
    sens = _sensibilidad()
    for parametro in sens.PARAMETROS_SENSIBLES:
        valor_base = motor.PARAMETROS_BASE[parametro]
        bajo, alto = sens.perturbaciones(parametro, valor_base)
        assert isinstance(bajo, (int, float)) and isinstance(alto, (int, float))
        assert bajo >= 0.0 and alto >= 0.0
        if parametro.startswith("percentil"):
            assert 0.0 < bajo < 1.0 and 0.0 < alto < 1.0
