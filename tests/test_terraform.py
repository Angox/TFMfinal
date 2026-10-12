import glob
import os
import re

import pytest

RAIZ = os.path.join(os.path.dirname(__file__), "..")
TERRAFORM = os.path.join(RAIZ, "terraform")

ADMITIDOS_AWS = re.compile(r"^[0-9A-Za-z_ .:/()#,@\[\]+=&;{}!$*-]*$")

RECURSOS_RESTRINGIDOS = ("aws_security_group", "aws_security_group_rule")


def ficheros_tf():
    return sorted(glob.glob(os.path.join(TERRAFORM, "*.tf")))


def bloques_de_recurso(contenido, tipos):
    bloques = []
    for tipo in tipos:
        for m in re.finditer(r'resource\s+"%s"\s+"([^"]+)"\s*\{' % re.escape(tipo), contenido):
            nombre = m.group(1)
            i = m.end()
            profundidad = 1
            while i < len(contenido) and profundidad:
                if contenido[i] == "{":
                    profundidad += 1
                elif contenido[i] == "}":
                    profundidad -= 1
                i += 1
            bloques.append((tipo, nombre, contenido[m.end():i - 1]))
    return bloques


def textos_restringidos():
    encontrados = []
    for ruta in ficheros_tf():
        with open(ruta, encoding="utf-8") as f:
            contenido = f.read()
        for tipo, nombre, cuerpo in bloques_de_recurso(contenido, RECURSOS_RESTRINGIDOS):
            limpio = "\n".join(l.split("#")[0] for l in cuerpo.splitlines())
            for atributo in ("description", "name"):
                for m in re.finditer(r'\b%s\s*=\s*"([^"]*)"' % atributo, limpio):
                    encontrados.append((os.path.basename(ruta), f"{tipo}.{nombre}",
                                        atributo, m.group(1)))
    return encontrados


def test_hay_security_groups_que_comprobar():
    assert textos_restringidos()


def test_las_descripciones_de_security_group_son_validas_para_aws():
    invalidos = [(f, r, a, v) for f, r, a, v in textos_restringidos()
                 if not ADMITIDOS_AWS.match(v)]
    assert not invalidos


def test_ningun_texto_restringido_lleva_caracteres_no_ascii():
    con_acentos = [(f, r, a, v) for f, r, a, v in textos_restringidos()
                   if any(ord(c) > 127 for c in v)]
    assert not con_acentos


@pytest.mark.parametrize("valor,valido", [
    ("Salida hacia S3, ECR y los datasets publicos de terceros", True),
    ("Solo salida para los workers del ETL en Fargate Spot", True),
    ("tfm-batch-etl", True),
    ("HTTPS (443) + HTTP (80)", True),
    ("Salida hacia los datasets públicos", False),
    ("Conexión saliente", False),
    ("Tráfico de años", False),
])
def test_el_patron_de_aws_acepta_y_rechaza_lo_esperado(valor, valido):
    assert bool(ADMITIDOS_AWS.match(valor)) is valido


def test_el_bloque_egress_anidado_se_detecta():
    ejemplo = '''
    resource "aws_security_group" "prueba" {
      name        = "sg-prueba"
      description = "Descripcion externa"

      egress {
        description = "Descripcion interna"
        from_port   = 0
      }
    }
    '''
    bloques = bloques_de_recurso(ejemplo, ("aws_security_group",))
    assert len(bloques) == 1
    cuerpo = bloques[0][2]
    assert "Descripcion externa" in cuerpo and "Descripcion interna" in cuerpo


SEGUNDOS_MINIMOS_WEBSOCKET = 600


def _sin_comentarios(cuerpo):
    return "\n".join(l.split("#")[0] for l in cuerpo.splitlines())


def recursos(tipo):
    encontrados = []
    for ruta in ficheros_tf():
        with open(ruta, encoding="utf-8") as f:
            contenido = f.read()
        for _tipo, nombre, cuerpo in bloques_de_recurso(contenido, (tipo,)):
            encontrados.append((os.path.basename(ruta), nombre, cuerpo))
    return encontrados


def test_hay_un_cloud_run_y_un_backend_service_que_comprobar():
    assert recursos("google_cloud_run_v2_service")
    assert recursos("google_compute_backend_service")


def test_el_cloud_run_aguanta_una_sesion_de_simulacion():
    for fichero, nombre, cuerpo in recursos("google_cloud_run_v2_service"):
        m = re.search(r'^\s*timeout\s*=\s*"(\d+)s"', _sin_comentarios(cuerpo), re.M)
        assert m
        assert int(m.group(1)) >= SEGUNDOS_MINIMOS_WEBSOCKET


def test_el_backend_service_no_declara_timeout_sec():
    for fichero, nombre, cuerpo in recursos("google_compute_backend_service"):
        assert not re.search(r"^\s*timeout_sec\s*=", _sin_comentarios(cuerpo), re.M)
