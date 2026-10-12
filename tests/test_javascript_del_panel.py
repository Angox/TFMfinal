import os

import pytest

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ABRE = '<script type="module">'
CIERRA = "</script>"


def _leer_html():
    ruta = os.path.join(RAIZ, "app", "static", "index.html")
    with open(ruta, encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n")


def _guiones_del_modulo(html):
    guiones = []
    desde = 0
    while True:
        inicio = html.find(ABRE, desde)
        if inicio < 0:
            return guiones
        cuerpo_desde = inicio + len(ABRE)
        fin = html.find(CIERRA, cuerpo_desde)
        assert fin > 0
        primera_linea = html.count("\n", 0, cuerpo_desde) + 1
        guiones.append((primera_linea, html[cuerpo_desde:fin]))
        desde = fin + len(CIERRA)


def _revisar_literales(codigo, linea_base):
    fallos = []
    estado = "codigo"
    pila_plantillas = []
    llaves_interpolacion = []
    linea = linea_base
    inicio_literal = None

    i = 0
    n = len(codigo)
    while i < n:
        c = codigo[i]

        if c == "\n":
            linea += 1
            if estado in ("cadena_simple", "cadena_doble"):
                fallos.append(
                    "línea %d: cadena abierta en la línea %d y cortada por un salto "
                    "de línea." % (linea, inicio_literal))
                estado = "codigo"
            elif estado == "comentario_linea":
                estado = "codigo"
            i += 1
            continue

        if estado == "comentario_linea":
            i += 1
            continue

        if estado == "comentario_bloque":
            if c == "*" and codigo[i + 1:i + 2] == "/":
                estado = "codigo"
                i += 2
                continue
            i += 1
            continue

        if estado in ("cadena_simple", "cadena_doble", "plantilla"):
            if c == "\\":
                i += 2
                continue
            if estado == "cadena_simple" and c == "'":
                estado = "codigo"
            elif estado == "cadena_doble" and c == '"':
                estado = "codigo"
            elif estado == "plantilla":
                if c == "`":
                    estado = "codigo"
                elif c == "$" and codigo[i + 1:i + 2] == "{":
                    pila_plantillas.append("plantilla")
                    llaves_interpolacion.append(0)
                    estado = "codigo"
                    i += 2
                    continue
            i += 1
            continue

        if c == "/" and codigo[i + 1:i + 2] == "/":
            estado = "comentario_linea"
            i += 2
            continue
        if c == "/" and codigo[i + 1:i + 2] == "*":
            estado = "comentario_bloque"
            i += 2
            continue
        if c == "'":
            estado, inicio_literal = "cadena_simple", linea
        elif c == '"':
            estado, inicio_literal = "cadena_doble", linea
        elif c == "`":
            estado, inicio_literal = "plantilla", linea
        elif pila_plantillas and c == "{":
            llaves_interpolacion[-1] += 1
        elif pila_plantillas and c == "}":
            if llaves_interpolacion[-1] == 0:
                pila_plantillas.pop()
                llaves_interpolacion.pop()
                estado = "plantilla"
            else:
                llaves_interpolacion[-1] -= 1
        i += 1

    if estado != "codigo":
        fallos.append("el fichero termina con un %s sin cerrar (abierto en la "
                      "línea %s)" % (estado.replace("_", " "), inicio_literal))
    if pila_plantillas:
        fallos.append("queda una interpolación `${...}` sin cerrar")
    return fallos


def test_hay_un_modulo_que_revisar():
    guiones = _guiones_del_modulo(_leer_html())
    assert guiones


@pytest.mark.parametrize("indice", range(4))
def test_las_cadenas_del_panel_abren_y_cierran(indice):
    guiones = _guiones_del_modulo(_leer_html())
    if indice >= len(guiones):
        pytest.skip("el fichero tiene %d módulos" % len(guiones))
    linea_base, codigo = guiones[indice]
    fallos = _revisar_literales(codigo, linea_base)
    assert not fallos


def test_el_revisor_detecta_una_cadena_partida():
    roto = 'alert("primera parte.\n\n"\n    + "segunda parte.");'
    assert _revisar_literales(roto, 1)

    sano = 'alert("primera parte. "\n    + "segunda parte.");'
    assert not _revisar_literales(sano, 1)

    plantilla = 'const h = `<div class="x">\n  ${cosa("a") + `${otra}`}\n</div>`;'
    assert not _revisar_literales(plantilla, 1)
