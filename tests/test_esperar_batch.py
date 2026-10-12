import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "etl"))

from esperar_batch import (
    agregar,
    esperar,
    resumir_job,
    veredicto,
)


def job_simple(estado, nombre="tfm-hinterland-large", motivo=None):
    j = {"jobId": "j-1", "jobName": nombre, "status": estado}
    if motivo:
        j["statusReason"] = motivo
    return j


def job_array(size, exitosos=0, fallidos=0, estado="RUNNING",
              nombre="tfm-hinterland-small", motivo=None):
    en_curso = size - exitosos - fallidos
    j = {
        "jobId": "j-arr", "jobName": nombre, "status": estado,
        "arrayProperties": {
            "size": size,
            "statusSummary": {
                "SUBMITTED": 0, "PENDING": 0, "RUNNABLE": max(en_curso, 0),
                "STARTING": 0, "RUNNING": 0,
                "SUCCEEDED": exitosos, "FAILED": fallidos,
            },
        },
    }
    if motivo:
        j["statusReason"] = motivo
    return j


class ClienteFalso:
    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = 0

    def describe_jobs(self, jobs):
        self.llamadas += 1
        indice = min(self.llamadas - 1, len(self.respuestas) - 1)
        return {"jobs": self.respuestas[indice]}


@pytest.mark.parametrize("estado,terminado", [
    ("SUBMITTED", False), ("PENDING", False), ("RUNNABLE", False),
    ("STARTING", False), ("RUNNING", False),
    ("SUCCEEDED", True), ("FAILED", True),
])
def test_un_job_simple_solo_termina_en_estado_terminal(estado, terminado):
    assert resumir_job(job_simple(estado))["terminado"] is terminado


def test_un_job_simple_correcto_cuenta_como_exitoso():
    r = resumir_job(job_simple("SUCCEEDED"))
    assert (r["exitosos"], r["fallidos"], r["total"]) == (1, 0, 1)


def test_un_job_simple_fallido_cuenta_como_fallido():
    r = resumir_job(job_simple("FAILED"))
    assert (r["exitosos"], r["fallidos"], r["total"]) == (0, 1, 1)


def test_un_array_no_termina_por_el_estado_del_padre():
    r = resumir_job(job_array(size=10, exitosos=4, fallidos=1))
    assert r["terminado"] is False
    assert (r["exitosos"], r["fallidos"], r["en_curso"]) == (4, 1, 5)


def test_un_array_termina_cuando_todos_los_hijos_han_terminado():
    r = resumir_job(job_array(size=10, exitosos=9, fallidos=1))
    assert r["terminado"] is True
    assert r["en_curso"] == 0


def test_un_array_recien_encolado_no_se_da_por_terminado():
    recien = {"jobId": "j", "jobName": "n", "status": "SUBMITTED",
              "arrayProperties": {"size": 40, "statusSummary": {}}}
    r = resumir_job(recien)
    assert r["terminado"] is False
    assert r["en_curso"] == 40


def test_el_motivo_del_fallo_se_conserva():
    r = resumir_job(job_simple("FAILED", motivo="Essential container in task exited"))
    assert "Essential container" in r["motivo"]


def test_agregar_suma_las_tres_tallas():
    resumenes = [
        resumir_job(job_array(size=30, exitosos=28, fallidos=2)),
        resumir_job(job_array(size=8, exitosos=8)),
        resumir_job(job_simple("SUCCEEDED")),
    ]
    p = agregar(resumenes)
    assert p["total"] == 39
    assert p["exitosos"] == 37
    assert p["fallidos"] == 2
    assert p["terminado"] is True


def test_agregar_no_termina_si_una_talla_sigue_viva():
    resumenes = [
        resumir_job(job_array(size=30, exitosos=30)),
        resumir_job(job_simple("RUNNING")),
    ]
    assert agregar(resumenes)["terminado"] is False


def test_agregar_sin_trabajos():
    p = agregar([])
    assert p["total"] == 0 and p["terminado"] is True


def test_todo_correcto_aprueba():
    ok, motivo = veredicto(agregar([resumir_job(job_array(size=40, exitosos=40))]))
    assert ok is True
    assert "40" in motivo


def test_unos_pocos_fallos_no_tumban_la_corrida():
    p = agregar([resumir_job(job_array(size=40, exitosos=38, fallidos=2))])
    ok, motivo = veredicto(p, umbral_fallos_pct=25.0)
    assert ok is True
    assert "fallidos" in motivo or "fallado" in motivo


def test_demasiados_fallos_paran_el_pipeline():
    p = agregar([resumir_job(job_array(size=40, exitosos=25, fallidos=15))])
    ok, motivo = veredicto(p, umbral_fallos_pct=25.0)
    assert ok is False
    assert "umbral" in motivo


def test_que_fallen_todas_es_un_fallo_sistemico():
    p = agregar([resumir_job(job_array(size=40, fallidos=40, estado="FAILED"))])
    ok, motivo = veredicto(p)
    assert ok is False
    assert "sistémico" in motivo


def test_sin_terminar_nunca_aprueba():
    p = agregar([resumir_job(job_array(size=40, exitosos=39))])
    ok, motivo = veredicto(p)
    assert ok is False
    assert "sin terminar" in motivo


def test_el_timeout_nunca_aprueba_aunque_todo_fuera_bien():
    p = agregar([resumir_job(job_array(size=40, exitosos=40))])
    assert p["terminado"] is True
    ok, motivo = veredicto(p, agotado=True)
    assert ok is False
    assert "agot" in motivo


def test_una_muestra_vacia_no_aprueba():
    ok, motivo = veredicto(agregar([]))
    assert ok is False
    assert "ninguna tarea" in motivo


@pytest.mark.parametrize("umbral,esperado", [(5.0, False), (10.0, True), (50.0, True)])
def test_el_umbral_es_configurable(umbral, esperado):
    p = agregar([resumir_job(job_array(size=40, exitosos=36, fallidos=4))])
    ok, _motivo = veredicto(p, umbral_fallos_pct=umbral)
    assert ok is esperado


def test_sondea_hasta_que_termina():
    cliente = ClienteFalso([
        [job_array(size=4, exitosos=0)],
        [job_array(size=4, exitosos=2)],
        [job_array(size=4, exitosos=4)],
    ])
    ok, _motivo, progreso = esperar(
        cliente, ["j-arr"], intervalo=1, salida=lambda t: None, dormir=lambda s: None)

    assert ok is True
    assert cliente.llamadas == 3
    assert progreso["exitosos"] == 4


def test_no_devuelve_ok_si_se_agota_el_tiempo():
    cliente = ClienteFalso([[job_array(size=4, exitosos=1)]])
    ok, motivo, progreso = esperar(
        cliente, ["j-arr"], timeout_minutos=1, intervalo=30,
        salida=lambda t: None, dormir=lambda s: None)

    assert ok is False
    assert "agot" in motivo
    assert progreso["en_curso"] == 3


def test_sin_identificadores_no_aprueba():
    ok, motivo, _p = esperar(ClienteFalso([[]]), [], salida=lambda t: None)
    assert ok is False
    assert "identificador" in motivo


def test_espera_a_las_tres_tallas_no_solo_a_la_primera():
    cliente = ClienteFalso([
        [job_array(size=3, exitosos=3, nombre="small"), job_simple("RUNNING", "large")],
        [job_array(size=3, exitosos=3, nombre="small"), job_simple("SUCCEEDED", "large")],
    ])
    ok, _motivo, progreso = esperar(
        cliente, ["a", "b"], intervalo=1, salida=lambda t: None, dormir=lambda s: None)

    assert ok is True
    assert cliente.llamadas == 2
    assert progreso["total"] == 4


def test_el_progreso_se_reporta_en_cada_sondeo():
    lineas = []
    cliente = ClienteFalso([
        [job_array(size=4, exitosos=1)],
        [job_array(size=4, exitosos=4)],
    ])
    esperar(cliente, ["j"], intervalo=1, salida=lineas.append, dormir=lambda s: None)

    assert len(lineas) == 2
    assert "4" in lineas[-1]
