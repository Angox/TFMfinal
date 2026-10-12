import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "estudio_costes"))

import catalogo_precios
from catalogo_precios import convertir
from perfil_carga import RECURSOS_POR_TALLA, UNIDADES, PerfilCarga


@pytest.mark.parametrize("unidad_api,destino,esperado", [
    ("1 Second", "vCPU·h", 3600.0),
    ("1 GiB Second", "GB·h", 3600.0),
    ("Hours", "vCPU·h", 1.0),
    ("100 Hours", "vCPU·h", 0.01),
    ("10K", "millar", 0.1),
    ("Requests", "millar", 1000.0),
    ("1 GB/Month", "GB·mes", 1.0),
    ("GB-Mo", "GB·mes", 1.0),
    ("GiBy.mo", "GB·mes", 1.0),
    ("1 GB", "GB", 1.0),
    ("gibibyte", "GB", 1.0),
    ("gibibyte month", "GB·mes", 1.0),
    ("gibibyte second", "GB·h", 3600.0),
    ("count", "millar", 1000.0),
    ("1K tokens", "millón de tokens", 1000.0),
    ("1K", "millón de tokens", 1000.0),
    ("1M", "millón de tokens", 1.0),
    ("1M tokens", "millón de tokens", 1.0),
])
def test_conversiones_correctas(unidad_api, destino, esperado):
    valor, fallo = convertir(1.0, unidad_api, destino)
    assert fallo is None
    assert valor == pytest.approx(esperado)


def test_el_segundo_de_azure_no_se_compara_crudo_con_la_hora_de_aws():
    por_hora, _ = convertir(3.4e-05, "1 Second", "vCPU·h")
    assert por_hora == pytest.approx(0.1224, rel=1e-6)
    assert por_hora > 0.04048


def test_operaciones_por_10k_no_se_comparan_crudas_con_el_millar():
    por_millar, _ = convertir(0.0043, "10K", "millar")
    assert por_millar == pytest.approx(0.00043)


@pytest.mark.parametrize("unidad_api,destino", [
    ("1 Second", "GB·mes"),
    ("1 GB/Month", "millar"),
    ("10K", "GB"),
    ("Hours", "GB·mes"),
])
def test_conversiones_imposibles_devuelven_motivo(unidad_api, destino):
    valor, fallo = convertir(1.0, unidad_api, destino)
    assert valor is None
    assert fallo


@pytest.mark.parametrize("unidad_api", ["", None, "furlongs por quincena"])
def test_unidades_desconocidas_no_se_convierten(unidad_api):
    valor, fallo = convertir(1.0, unidad_api, "GB")
    assert valor is None and fallo


def test_horas_de_computo_coinciden_con_los_recursos_por_talla():
    perfil = PerfilCarga(
        puertos_por_talla={"S": 10, "M": 0, "L": 0},
        horas_por_puerto={"S": 2.0, "M": 1.0, "L": 1.0},
        ejecuciones_etl_mes=1,
    )
    vcpu_h, gb_h = perfil.horas_computo_lote()
    assert vcpu_h == 10 * 2.0 * RECURSOS_POR_TALLA["S"]["vcpu"]
    assert gb_h == 10 * 2.0 * RECURSOS_POR_TALLA["S"]["gb"]


def test_las_ejecuciones_mensuales_escalan_el_computo():
    base = PerfilCarga(ejecuciones_etl_mes=1).horas_computo_lote()[0]
    doble = PerfilCarga(ejecuciones_etl_mes=2).horas_computo_lote()[0]
    assert doble == pytest.approx(2 * base)


def test_todos_los_conceptos_tienen_unidad():
    from perfil_carga import UNIDADES
    consumos = PerfilCarga().consumos()
    assert set(consumos) == set(UNIDADES)


def test_las_peticiones_se_expresan_en_millares():
    perfil = PerfilCarga(escrituras_s3_mes=60_000, lecturas_s3_mes=400_000)
    c = perfil.consumos()
    assert c["peticiones_escritura_millar"] == 60.0
    assert c["peticiones_lectura_millar"] == 400.0


def test_ningun_consumo_es_negativo():
    for concepto, valor in PerfilCarga().consumos().items():
        assert valor >= 0


def _sku(id_sku, descripcion, regiones, precio, unidad, con_tramo_gratis=False):
    tramos = []
    if con_tramo_gratis:
        tramos.append({"startUsageAmount": 0, "unitPrice": {"units": "0", "nanos": 0}})
    enteros = int(precio)
    tramos.append({"startUsageAmount": 100,
                   "unitPrice": {"units": str(enteros),
                                 "nanos": int(round((precio - enteros) * 1e9))}})
    return {
        "skuId": id_sku,
        "description": descripcion,
        "serviceRegions": regiones,
        "pricingInfo": [{"pricingExpression": {"usageUnitDescription": unidad,
                                               "tieredRates": tramos}}],
    }


class _CatalogoFalso:
    def __init__(self, servicios, skus):
        self.servicios = servicios
        self.skus = skus
        self.llamadas = []

    def __call__(self, url, timeout=180, cabeceras=None):
        self.llamadas.append((url, cabeceras or {}))
        if "/services/" in url:
            id_servicio = url.split("/services/")[1].split("/")[0]
            return {"skus": self.skus.get(id_servicio, [])}
        if "pageToken=" in url:
            return {"services": [{"serviceId": i, "displayName": n}
                                 for i, n in self.servicios[1:]]}
        return {"services": [{"serviceId": self.servicios[0][0],
                              "displayName": self.servicios[0][1]}],
                "nextPageToken": "pagina-2"}


@pytest.fixture
def gcp(monkeypatch):
    def montar(servicios, skus, region="europe-southwest1"):
        falso = _CatalogoFalso(servicios, skus)
        monkeypatch.setattr(catalogo_precios, "_leer_json", falso)
        monkeypatch.setenv("GCP_BILLING_API_KEY", "CLAVE-DE-PRUEBA")
        cliente = catalogo_precios.PreciosGCP(region)
        return cliente, falso

    return montar


def test_sin_clave_el_concepto_queda_pendiente(monkeypatch, tmp_path):
    monkeypatch.delenv("GCP_BILLING_API_KEY", raising=False)
    monkeypatch.setattr(catalogo_precios.PreciosGCP, "FICHERO_CLAVE",
                        str(tmp_path / "no-existe"))
    precio = catalogo_precios.PreciosGCP().buscar("Cloud Run", ["cpu"], "vCPU·h")
    assert precio.origen == "pendiente" and precio.valor is None
    assert "GCP_BILLING_API_KEY" in precio.nota


def test_la_clave_viaja_en_la_cabecera_y_nunca_en_la_url(gcp):
    cliente, falso = gcp([("SVC-RUN", "Cloud Run")],
                         {"SVC-RUN": [_sku("A", "Cloud Run CPU Allocation Time",
                                           ["europe-southwest1"], 0.000024, "seconds")]})
    cliente.buscar("Cloud Run", ["cpu allocation time"], "vCPU·h")
    assert falso.llamadas
    for url, cabeceras in falso.llamadas:
        assert "CLAVE-DE-PRUEBA" not in url
        assert cabeceras.get("X-Goog-Api-Key") == "CLAVE-DE-PRUEBA"


def test_el_servicio_se_resuelve_por_nombre_siguiendo_la_paginacion(gcp):
    cliente, _ = gcp([("SVC-RUN", "Cloud Run"), ("SVC-AR", "Artifact Registry")],
                     {"SVC-AR": [_sku("B", "Artifact Registry Storage",
                                      ["europe-southwest1"], 0.10, "gibibyte month")]})
    precio = cliente.buscar("Artifact Registry", ["storage"], "GB·mes")
    assert precio.origen == "api"
    assert precio.referencia == "B"
    assert precio.valor == pytest.approx(0.10)


def test_los_alias_cubren_los_renombrados_de_google(gcp):
    cliente, _ = gcp([("SVC-RUN", "Cloud Run"), ("SVC-LOG", "Stackdriver Logging")],
                     {"SVC-LOG": [_sku("C", "Log Volume", ["global"], 0.50, "gibibyte")]})
    precio = cliente.buscar(("Cloud Logging", "Stackdriver Logging"), ["log volume"], "GB")
    assert precio.origen == "api" and precio.referencia == "C"


def test_gana_el_sku_de_la_region_exacta_frente_al_global(gcp):
    cliente, _ = gcp(
        [("SVC-GCS", "Cloud Storage")],
        {"SVC-GCS": [_sku("GLOBAL", "Standard Storage", ["global"], 0.020, "gibibyte month"),
                     _sku("MADRID", "Standard Storage Madrid", ["europe-southwest1"],
                          0.023, "gibibyte month")]})
    precio = cliente.buscar("Cloud Storage", ["standard storage"], "GB·mes")
    assert precio.referencia == "MADRID"
    assert precio.valor == pytest.approx(0.023)


def test_el_tramo_gratuito_no_se_toma_como_precio(gcp):
    cliente, _ = gcp([("SVC-GCS", "Cloud Storage")],
                     {"SVC-GCS": [_sku("D", "Class A Operations", ["europe-southwest1"],
                                       0.000005, "count", con_tramo_gratis=True)]})
    precio = cliente.buscar("Cloud Storage", ["class a"], "millar")
    assert precio.valor == pytest.approx(0.005)


def test_excluye_descarta_las_variantes_que_no_se_comparan(gcp):
    cliente, _ = gcp(
        [("SVC-GCS", "Cloud Storage")],
        {"SVC-GCS": [_sku("NEAR", "Nearline Standard Storage Madrid", ["europe-southwest1"],
                          0.010, "gibibyte month"),
                     _sku("STD", "Standard Storage Madrid", ["europe-southwest1"],
                          0.023, "gibibyte month")]})
    precio = cliente.buscar("Cloud Storage", ["standard storage"], "GB·mes",
                            excluye=["nearline"])
    assert precio.referencia == "STD"


def test_los_descuentos_por_compromiso_nunca_son_el_precio_bajo_demanda(gcp):
    cliente, _ = gcp(
        [("SVC-RUN", "Cloud Run")],
        {"SVC-RUN": [_sku("CUD", "Commitment v1: Cloud Run CPU Allocation Time",
                          ["europe-southwest1"], 0.000010, "seconds"),
                     _sku("OD", "Cloud Run CPU Allocation Time",
                          ["europe-southwest1"], 0.000024, "seconds")]})
    precio = cliente.buscar("Cloud Run", ["cpu allocation time"], "vCPU·h")
    assert precio.referencia == "OD"
    assert precio.valor == pytest.approx(0.0864)


def test_un_renombrado_deja_el_concepto_pendiente_en_vez_de_acertar_por_azar(gcp):
    cliente, _ = gcp(
        [("SVC-RUN", "Cloud Run")],
        {"SVC-RUN": [_sku("BARATO", "Instances CPU", ["europe-southwest1"],
                          0.00000027, "seconds"),
                     _sku("BUENO", "Services CPU (Request-based billing)",
                          ["europe-southwest1"], 0.000024, "seconds")]})

    precio = cliente.buscar("Cloud Run", ["services cpu", "request-based"], "vCPU·h")
    assert precio.referencia == "BUENO"

    precio = cliente.buscar("Cloud Run", ["cpu allocation time"], "vCPU·h")
    assert precio.origen == "pendiente" and precio.valor is None


def test_una_unidad_no_convertible_deja_el_concepto_pendiente(gcp):
    cliente, _ = gcp([("SVC-GCS", "Cloud Storage")],
                     {"SVC-GCS": [_sku("F", "Standard Storage Madrid", ["europe-southwest1"],
                                       0.023, "furlongs por quincena")]})
    precio = cliente.buscar("Cloud Storage", ["standard storage"], "GB·mes")
    assert precio.origen == "pendiente" and precio.valor is None


def test_cada_concepto_de_gcp_se_pide_a_su_propio_servicio(monkeypatch):
    import generar_informe

    class Espia:
        def __init__(self, region):
            self.region = region

        def buscar(self, servicio, contiene, unidad, excluye=None):
            nombre = servicio if isinstance(servicio, str) else servicio[0]
            return catalogo_precios.Precio(1.0, unidad, "api", referencia=nombre,
                                           nota=" + ".join(contiene))

    monkeypatch.setattr(generar_informe, "PreciosGCP", Espia)
    precios = generar_informe.precios_gcp("europe-southwest1")

    assert precios["registro_contenedores_gb_mes"].referencia == "Artifact Registry"
    assert precios["logs_gb"].referencia == "Cloud Logging"
    assert precios["almacenamiento_gb_mes"].referencia == "Cloud Storage"
    assert precios["computo_web_vcpu_h"].referencia == "Cloud Run"
    assert set(precios) == set(UNIDADES)


def test_la_tabla_de_equivalencias_cubre_todos_los_conceptos():
    import generar_informe

    assert set(generar_informe.EQUIVALENCIAS) == set(UNIDADES)


def test_el_lote_y_la_web_no_comparten_sku_en_cloud_run(monkeypatch):
    import generar_informe

    class Espia:
        def __init__(self, region):
            self.region = region

        def buscar(self, servicio, contiene, unidad, excluye=None):
            return catalogo_precios.Precio(1.0, unidad, "api", nota=" + ".join(contiene))

    monkeypatch.setattr(generar_informe, "PreciosGCP", Espia)
    precios = generar_informe.precios_gcp("europe-southwest1")

    assert "jobs cpu" in precios["computo_lote_vcpu_h"].nota
    assert "jobs memory" in precios["computo_lote_gb_h"].nota
    assert "services cpu" in precios["computo_web_vcpu_h"].nota
    assert "services memory" in precios["computo_web_gb_h"].nota
    assert "request-based" in precios["computo_web_vcpu_h"].nota


def _catalogo_plano(valor=1.0):
    return {c: catalogo_precios.Precio(valor, u, "api", referencia=c)
            for c, u in UNIDADES.items()}


def test_solo_aws_lleva_descuento_por_capacidad_interrumpible():
    import generar_informe

    perfil = PerfilCarga(fraccion_interrumpible=1.0)
    por_nube = {n: generar_informe.calcular(perfil, _catalogo_plano(), n)
                for n in ("aws", "gcp", "azure")}

    def dto(nube, concepto):
        fila = next(f for f in por_nube[nube]["filas"] if f["concepto"] == concepto)
        return fila["descuento_aplicado"]

    assert dto("aws", "computo_lote_vcpu_h") == pytest.approx(0.70)
    assert dto("gcp", "computo_lote_vcpu_h") == 0.0
    assert dto("azure", "computo_lote_vcpu_h") == 0.0
    for nube in ("aws", "gcp", "azure"):
        assert dto(nube, "computo_web_vcpu_h") == 0.0


def test_una_nube_no_declarada_se_valora_a_precio_de_lista():
    import generar_informe

    resultado = generar_informe.calcular(
        PerfilCarga(fraccion_interrumpible=1.0), _catalogo_plano(), "oracle")
    fila = next(f for f in resultado["filas"] if f["concepto"] == "computo_lote_vcpu_h")
    assert fila["descuento_aplicado"] == 0.0
    assert fila["precio_unitario"] == fila["precio_lista"]


def test_el_descuento_se_aplica_al_precio_y_la_tabla_cuadra():
    import generar_informe

    perfil = PerfilCarga(fraccion_interrumpible=1.0)
    resultado = generar_informe.calcular(perfil, _catalogo_plano(2.0), "aws")
    for fila in resultado["filas"]:
        assert fila["coste"] == pytest.approx(fila["cantidad"] * fila["precio_unitario"], rel=1e-6)


def test_sin_fraccion_interrumpible_no_hay_descuento_ni_en_aws():
    import generar_informe

    perfil = PerfilCarga(fraccion_interrumpible=0.0)
    resultado = generar_informe.calcular(perfil, _catalogo_plano(), "aws")
    fila = next(f for f in resultado["filas"] if f["concepto"] == "computo_lote_vcpu_h")
    assert fila["descuento_aplicado"] == 0.0


def test_el_precio_por_token_no_se_confunde_con_un_recuento_de_peticiones():
    por_millon, fallo = convertir(0.00006, "1K tokens", "millón de tokens")
    assert fallo is None
    assert por_millon == pytest.approx(0.06)


def test_el_lote_de_bedrock_cuesta_la_mitad_y_no_es_el_del_copiloto(monkeypatch):
    import generar_informe

    pedidos = []

    class Espia:
        def __init__(self, region):
            pass

        def buscar(self, oferta, filtros, unidad, excluye=None):
            if oferta == "AmazonBedrock":
                pedidos.append(filtros)
            return catalogo_precios.Precio(1.0, unidad, "api", referencia=oferta)

    monkeypatch.setattr(generar_informe, "PreciosAWS", Espia)
    generar_informe.precios_aws("us-west-2")

    assert len(pedidos) == 2
    for filtros in pedidos:
        assert filtros["feature"] == "On-demand Inference"
        assert filtros["model"] == "Nova Lite"
    assert {f["inferenceType"] for f in pedidos} == {"Input tokens", "Output tokens"}


def test_los_modelos_de_azure_se_piden_a_foundry_models(monkeypatch):
    import generar_informe

    pedidos = []

    class Espia:
        def __init__(self, region):
            pass

        def buscar(self, filtro, unidad, contiene=None, excluye=None):
            pedidos.append((filtro, contiene or []))
            return catalogo_precios.Precio(1.0, unidad, "api", referencia=filtro)

    monkeypatch.setattr(generar_informe, "PreciosAzure", Espia)
    generar_informe.precios_azure("westeurope")

    de_tokens = [(f, c) for f, c in pedidos if any("nano" in t for t in c)]
    assert len(de_tokens) == 2
    for filtro, contiene in de_tokens:
        assert "Foundry Models" in filtro
        assert any(t.startswith("gpt 4.1 nano ") and t.endswith(" glbl") for t in contiene)


def test_los_logs_de_azure_se_piden_a_log_analytics(monkeypatch):
    import generar_informe

    pedidos = []

    class Espia:
        def __init__(self, region):
            pass

        def buscar(self, filtro, unidad, contiene=None, excluye=None):
            pedidos.append((filtro, contiene or []))
            return catalogo_precios.Precio(1.0, unidad, "api", referencia=filtro)

    monkeypatch.setattr(generar_informe, "PreciosAzure", Espia)
    precios = generar_informe.precios_azure("westeurope")

    assert precios["logs_gb"].origen == "api"
    de_logs = [f for f, c in pedidos if any("ingestion" in t for t in c)]
    assert len(de_logs) == 1 and "Log Analytics" in de_logs[0]


def test_el_respaldo_manual_no_borra_el_motivo_del_fallo():
    previo = catalogo_precios.PENDIENTE("GB", "PERMISSION_DENIED: la clave no vale para este catálogo")
    resultado = catalogo_precios.precio_manual({"gcp": {}}, "gcp", "logs_gb", "GB", previo)

    assert resultado.origen == "pendiente"
    assert "PERMISSION_DENIED" in resultado.nota
    assert "precios_manuales.json" in resultado.nota


def test_el_respaldo_manual_sigue_ganando_cuando_hay_valor():
    manuales = {"gcp": {"logs_gb": {"valor_usd": 0.5, "fuente": "https://ejemplo",
                                    "fecha_consulta": "2026-08-30"}}}
    previo = catalogo_precios.PENDIENTE("GB", "lo que sea")
    resultado = catalogo_precios.precio_manual(manuales, "gcp", "logs_gb", "GB", previo)

    assert resultado.origen == "manual"
    assert resultado.valor == 0.5


@pytest.mark.parametrize("crudo", [
    "AIzaSyEJEMPLO",
    "  AIzaSyEJEMPLO  ",
    "\ufeffAIzaSyEJEMPLO",
    "\ufeffAIzaSyEJEMPLO\n",
    '"AIzaSyEJEMPLO"',
    "'AIzaSyEJEMPLO'",
])
def test_la_clave_de_gcp_se_lee_limpia(crudo):
    assert catalogo_precios.PreciosGCP._limpiar_clave(crudo) == "AIzaSyEJEMPLO"


def test_una_clave_con_bom_no_llega_a_la_cabecera(tmp_path, monkeypatch):
    fichero = tmp_path / ".gcp_api_key"
    fichero.write_text("AIzaSyEJEMPLO", encoding="utf-8-sig")

    monkeypatch.delenv("GCP_BILLING_API_KEY", raising=False)
    monkeypatch.setattr(catalogo_precios.PreciosGCP, "FICHERO_CLAVE", str(fichero))

    assert catalogo_precios.PreciosGCP._leer_clave() == "AIzaSyEJEMPLO"
