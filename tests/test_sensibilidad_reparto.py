import contextlib
import io
import json
import os
import sys
import types
from unittest import mock

import pytest

RAIZ = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(RAIZ, "etl"))


CATALOGOS = {
    "S": [{"portname": f"S{i}", "portid": f"ps{i}"} for i in range(4)],
    "M": [{"portname": f"M{i}", "portid": f"pm{i}"} for i in range(4)],
    "L": [{"portname": f"L{i}", "portid": f"pl{i}"} for i in range(7)],
}

PUERTO_SIN_DATOS = "L2"

RUIDO_DEL_IMPORT = ("Consultando STAC de Overture Maps...\n"
                    "Overture Release detectada: 2026-08-19.0")


class _S3Falso:
    def get_object(self, Bucket, Key):
        talla = Key.rsplit("_", 1)[1].split(".")[0]
        return {"Body": io.BytesIO(json.dumps(CATALOGOS[talla]).encode("utf-8"))}


@pytest.fixture
def sens():
    motor = types.ModuleType("etl_procesamiento")
    motor.PARAMETROS_BASE = {}
    motor.s3_client = _S3Falso()
    motor.S3_BUCKET = "bucket-de-pruebas"
    motor.cargar_perfiles_comtrade_s3 = lambda: {}
    motor.inicializar_duckdb = lambda: types.SimpleNamespace(close=lambda: None)

    with mock.patch.dict(sys.modules, {"etl_procesamiento": motor}):
        sys.modules.pop("analisis_sensibilidad", None)
        print(RUIDO_DEL_IMPORT)
        import analisis_sensibilidad as modulo

        modulo.preparar_puerto = lambda con, dp, m: (
            None if dp["portname"] == PUERTO_SIN_DATOS else {"nombre": dp["portname"]})
        modulo.analizar_puerto = lambda e: _resultado_falso(modulo, e["nombre"])
        yield modulo
        sys.modules.pop("analisis_sensibilidad", None)


def _resultado_falso(modulo, nombre):
    return {
        "puerto": nombre,
        "ablaciones": {n: {"indice_estres": 4.0, "trafico_medio": 1.0,
                           "saturacion": 0.1, "vulnerabilidad": 0.2,
                           "incremento_interdiccion": 0.0,
                           "origen_puertas": "respaldo_radio", "puertas_viales": 3}
                       for n in modulo.ABLACIONES},
        "sensibilidad": {p: {"valor_base": 1.0, "valor_menos": 0.7, "valor_mas": 1.3,
                             "i_el_menos": 3.9, "i_el_base": 4.0, "i_el_mas": 4.1,
                             "elasticidad": 0.05}
                         for p in modulo.PARAMETROS_SENSIBLES},
    }


def _correr(modulo, *extra):
    argv = ["analisis_sensibilidad.py", "--puertos", "12", "--tallas", "S,M,L"]
    salida = io.StringIO()
    with mock.patch.object(sys, "argv", argv + list(extra)):
        with contextlib.redirect_stdout(salida):
            modulo.main()
    return salida.getvalue()


def test_el_reparto_se_escribe_en_un_fichero_de_json_valido(sens, tmp_path):
    destino = tmp_path / "plan.json"
    _correr(sens, "--plan", "--fichero-plan", str(destino))

    crudo = destino.read_text(encoding="utf-8")
    assert "\n" not in crudo.strip()

    plan = json.loads(crudo)
    assert len(plan) == 12
    assert [p["indice"] for p in plan] == list(range(12))
    assert all({"indice", "nombre", "portid", "talla"} <= set(p) for p in plan)


def test_la_stdout_no_sirve_como_canal_de_datos_para_el_reparto(tmp_path):
    motor = types.ModuleType("etl_procesamiento")
    motor.PARAMETROS_BASE = {}
    motor.s3_client = _S3Falso()
    motor.S3_BUCKET = "bucket-de-pruebas"
    motor.cargar_perfiles_comtrade_s3 = lambda: {}
    motor.inicializar_duckdb = lambda: types.SimpleNamespace(close=lambda: None)

    destino = tmp_path / "plan.json"
    argv = ["analisis_sensibilidad.py", "--puertos", "12", "--tallas", "S,M,L",
            "--plan", "--fichero-plan", str(destino)]
    capturado = io.StringIO()

    with mock.patch.dict(sys.modules, {"etl_procesamiento": motor}):
        sys.modules.pop("analisis_sensibilidad", None)
        with contextlib.redirect_stdout(capturado):
            print(RUIDO_DEL_IMPORT)
            import analisis_sensibilidad as modulo
            with mock.patch.object(sys, "argv", argv):
                modulo.main()
        sys.modules.pop("analisis_sensibilidad", None)

    with pytest.raises(json.JSONDecodeError):
        json.loads(capturado.getvalue())

    assert len(json.loads(destino.read_text(encoding="utf-8"))) == 12


def test_el_plan_es_identico_en_dos_invocaciones(sens):
    assert json.loads(_correr(sens, "--plan")) == json.loads(_correr(sens, "--plan"))


def test_el_plan_reparte_entre_las_tallas_pedidas(sens):
    plan = json.loads(_correr(sens, "--plan"))
    assert {p["talla"] for p in plan} == {"S", "M", "L"}


def test_cada_indice_analiza_su_propio_puerto(sens, tmp_path):
    plan = json.loads(_correr(sens, "--plan"))
    destino = str(tmp_path / "parciales")

    for p in plan:
        _correr(sens, "--indice", str(p["indice"]), "--salida", destino)

    assert len(os.listdir(destino)) == len(plan)
    for p in plan:
        with open(os.path.join(destino, f"puerto_{p['indice']:03d}.json"),
                  encoding="utf-8") as f:
            parcial = json.load(f)
        assert parcial["puerto"] == p["nombre"]
        assert parcial["_indice"] == p["indice"]


def test_un_indice_fuera_del_plan_falla_en_vez_de_analizar_otro_puerto(sens, tmp_path):
    with pytest.raises(SystemExit) as e:
        _correr(sens, "--indice", "99", "--salida", str(tmp_path))
    assert e.value.code == 1


def test_un_puerto_sin_datos_se_marca_omitido_y_no_tumba_la_matriz(sens, tmp_path):
    plan = json.loads(_correr(sens, "--plan"))
    indice = next(p["indice"] for p in plan if p["nombre"] == PUERTO_SIN_DATOS)
    destino = str(tmp_path / "parciales")

    _correr(sens, "--indice", str(indice), "--salida", destino)

    with open(os.path.join(destino, f"puerto_{indice:03d}.json"), encoding="utf-8") as f:
        parcial = json.load(f)
    assert parcial["omitido"] is True
    assert parcial["resultado"] is None


def test_la_combinacion_ordena_por_indice_y_no_por_llegada(sens, tmp_path):
    plan = json.loads(_correr(sens, "--plan"))
    destino = tmp_path / "parciales"
    destino.mkdir()

    for p in reversed(plan):
        if p["nombre"] == PUERTO_SIN_DATOS:
            continue
        parcial = {"_indice": p["indice"], "puerto": p["nombre"], "omitido": False,
                   "resultado": _resultado_falso(sens, p["nombre"])}
        (destino / f"puerto_{p['indice']:03d}.json").write_text(
            json.dumps(parcial), encoding="utf-8")

    salida = tmp_path / "informe"
    _correr(sens, "--combinar", str(destino), "--salida", str(salida))

    datos = json.loads((salida / "sensibilidad.json").read_text(encoding="utf-8"))
    esperado = [p["nombre"] for p in plan if p["nombre"] != PUERTO_SIN_DATOS]
    assert [r["puerto"] for r in datos["resultados"]] == esperado


def test_la_combinacion_encuentra_los_parciales_en_subcarpetas(sens, tmp_path):
    destino = tmp_path / "parciales"
    for indice, nombre in ((0, "Alfa"), (1, "Bravo")):
        sub = destino / f"parcial-{indice}"
        sub.mkdir(parents=True)
        (sub / f"puerto_{indice:03d}.json").write_text(json.dumps(
            {"_indice": indice, "puerto": nombre, "omitido": False,
             "resultado": _resultado_falso(sens, nombre)}), encoding="utf-8")

    salida = tmp_path / "informe"
    _correr(sens, "--combinar", str(destino), "--salida", str(salida))

    md = (salida / "sensibilidad.md").read_text(encoding="utf-8")
    assert "Puertos analizados: **2**" in md


def test_combinar_sin_parciales_falla_en_vez_de_publicar_un_informe_vacio(sens, tmp_path):
    vacio = tmp_path / "nada"
    vacio.mkdir()
    with pytest.raises(SystemExit) as e:
        _correr(sens, "--combinar", str(vacio), "--salida", str(tmp_path / "out"))
    assert e.value.code == 1


def test_el_informe_combinado_es_identico_al_de_un_solo_proceso(sens, tmp_path):
    plan = json.loads(_correr(sens, "--plan"))

    parciales = tmp_path / "parciales"
    for p in plan:
        _correr(sens, "--indice", str(p["indice"]), "--salida", str(parciales))
    en_paralelo = tmp_path / "paralelo"
    _correr(sens, "--combinar", str(parciales), "--salida", str(en_paralelo))

    en_serie = tmp_path / "serie"
    _correr(sens, "--salida", str(en_serie))

    assert ((en_paralelo / "sensibilidad.md").read_text(encoding="utf-8")
            == (en_serie / "sensibilidad.md").read_text(encoding="utf-8"))
    assert (json.loads((en_paralelo / "sensibilidad.json").read_text(encoding="utf-8"))
            == json.loads((en_serie / "sensibilidad.json").read_text(encoding="utf-8")))
