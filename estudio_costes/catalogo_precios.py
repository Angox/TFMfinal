import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

BASE_AWS = "https://pricing.us-east-1.amazonaws.com"
BASE_AZURE = "https://prices.azure.com/api/retail/prices"
BASE_GCP = "https://cloudbilling.googleapis.com/v1"

CABECERAS = {"User-Agent": "TFM-Hinterland-EstudioCostes/1.0"}
DIR_ACTUAL = os.path.dirname(os.path.abspath(__file__))


def _leer_json(url, timeout=180, cabeceras=None):
    req = urllib.request.Request(url, headers={**CABECERAS, **(cabeceras or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


class Precio:
    def __init__(self, valor, unidad, origen, referencia="", nota="", unidad_api=""):
        self.valor = valor
        self.unidad = unidad
        self.origen = origen
        self.referencia = referencia
        self.nota = nota
        self.unidad_api = unidad_api

    def a_dict(self):
        return {
            "valor_usd": self.valor,
            "unidad": self.unidad,
            "origen": self.origen,
            "referencia": self.referencia,
            "unidad_facturacion": self.unidad_api,
            "nota": self.nota,
        }

    def __repr__(self):
        return f"Precio({self.valor} USD/{self.unidad}, {self.origen})"


PENDIENTE = lambda unidad, nota: Precio(None, unidad, "pendiente", nota=nota)


FACTORES_MAGNITUD = {"k": 1_000, "m": 1_000_000}

SEGUNDO, HORA, GB_MES, GB, PETICION, TOKEN = "s", "h", "gb_mes", "gb", "peticion", "token"


def _parsear_unidad(texto):
    if not texto:
        return None, None
    t = str(texto).strip().lower()

    factor = 1.0
    resto = t
    partes = t.split(None, 1)
    if partes:
        cabeza = partes[0]
        num = ""
        for c in cabeza:
            if c.isdigit() or c == ".":
                num += c
            else:
                break
        if num:
            factor = float(num)
            sufijo = cabeza[len(num):]
            if sufijo in FACTORES_MAGNITUD:
                factor *= FACTORES_MAGNITUD[sufijo]
                resto = partes[1] if len(partes) > 1 else ""
            else:
                resto = partes[1] if len(partes) > 1 else sufijo

    resto = resto.strip()
    if "month" in resto or resto in ("gb-mo", "giby.mo", "gb/month"):
        return factor, GB_MES
    if "second" in resto or resto in ("s", "seconds"):
        return factor, SEGUNDO
    if "hour" in resto or resto in ("h", "hrs", "hours"):
        return factor, HORA
    if "token" in resto:
        return factor, TOKEN
    if "request" in resto or "operation" in resto or resto in ("", "count", "requests"):
        return factor, PETICION
    if "gb" in resto or "giby" in resto or "gibibyte" in resto or "gigabyte" in resto:
        return factor, GB
    return factor, None


def convertir(valor, unidad_api, unidad_destino):
    factor, familia = _parsear_unidad(unidad_api)
    if familia is None:
        return None, f"unidad no reconocida: '{unidad_api}'"
    if factor in (None, 0):
        return None, f"factor inválido en '{unidad_api}'"

    if unidad_destino in ("vCPU·h", "GB·h"):
        if familia == SEGUNDO:
            return valor * 3600.0 / factor, None
        if familia == HORA:
            return valor / factor, None
        return None, f"no se puede pasar de '{unidad_api}' a {unidad_destino}"

    if unidad_destino == "GB·mes":
        if familia == GB_MES:
            return valor / factor, None
        return None, f"no se puede pasar de '{unidad_api}' a GB·mes"

    if unidad_destino == "GB":
        if familia == GB:
            return valor / factor, None
        return None, f"no se puede pasar de '{unidad_api}' a GB"

    if unidad_destino == "millar":
        if familia == PETICION:
            return valor * 1000.0 / factor, None
        return None, f"no se puede pasar de '{unidad_api}' a millar"

    if unidad_destino == "millón de tokens":
        if familia in (TOKEN, PETICION):
            return valor * 1_000_000.0 / factor, None
        return None, f"no se puede pasar de '{unidad_api}' a millón de tokens"

    return None, f"unidad de destino desconocida: {unidad_destino}"


class PreciosAWS:
    def __init__(self, region="us-west-2"):
        self.region = region
        self._cache = {}

    def _oferta(self, codigo):
        if codigo not in self._cache:
            indice = _leer_json(f"{BASE_AWS}/offers/v1.0/aws/{codigo}/current/region_index.json")
            if self.region not in indice["regions"]:
                raise KeyError(f"{codigo} no publica precios para {self.region}")
            self._cache[codigo] = _leer_json(BASE_AWS + indice["regions"][self.region]["currentVersionUrl"])
        return self._cache[codigo]

    def buscar(self, codigo_oferta, filtros, unidad, excluye=None):
        try:
            datos = self._oferta(codigo_oferta)
        except Exception as e:
            return PENDIENTE(unidad, f"no se pudo descargar {codigo_oferta}: {e}")

        motivo = f"sin coincidencias en {codigo_oferta} con {filtros}"
        for sku, producto in datos["products"].items():
            atributos = producto.get("attributes", {})
            if not all(str(atributos.get(k, "")).find(v) >= 0 for k, v in filtros.items()):
                continue
            terminos = datos.get("terms", {}).get("OnDemand", {}).get(sku)
            if not terminos:
                continue
            for termino in terminos.values():
                dimensiones = sorted(
                    termino["priceDimensions"].values(),
                    key=lambda d: float(d.get("beginRange") or 0),
                )
                for dimension in dimensiones:
                    precio = float(dimension["pricePerUnit"]["USD"])
                    if precio <= 0:
                        continue
                    descripcion = dimension.get("description", "")
                    if excluye and any(t.lower() in descripcion.lower() for t in excluye):
                        continue
                    unidad_api = dimension.get("unit", "")
                    convertido, fallo = convertir(precio, unidad_api, unidad)
                    if convertido is None:
                        motivo = f"{codigo_oferta}/{sku}: {fallo}"
                        continue
                    return Precio(
                        convertido, unidad, "api",
                        referencia=f"{codigo_oferta}/{sku}",
                        nota=descripcion[:120], unidad_api=unidad_api,
                    )
        return PENDIENTE(unidad, motivo)


class PreciosAzure:
    MAX_PAGINAS = 12

    def __init__(self, region="westeurope"):
        self.region = region

    def buscar(self, filtro_odata, unidad, contiene=None, excluye=None):
        url = BASE_AZURE + "?" + urllib.parse.urlencode({
            "$filter": filtro_odata.format(region=self.region),
            "currencyCode": "USD",
        })
        items = []
        try:
            for _ in range(self.MAX_PAGINAS):
                datos = _leer_json(url, timeout=120)
                items.extend(datos.get("Items", []))
                url = datos.get("NextPageLink")
                if not url:
                    break
        except Exception as e:
            if not items:
                return PENDIENTE(unidad, f"error consultando Azure: {e}")

        motivo = f"sin coincidencias en Azure para {filtro_odata}"
        for item in items:
            if item.get("type") != "Consumption":
                continue
            if float(item.get("retailPrice", 0)) <= 0:
                continue
            nombre = f"{item.get('productName', '')} {item.get('meterName', '')}"
            if contiene and not all(t.lower() in nombre.lower() for t in contiene):
                continue
            if excluye and any(t.lower() in nombre.lower() for t in excluye):
                continue
            unidad_api = item.get("unitOfMeasure", "")
            convertido, fallo = convertir(float(item["retailPrice"]), unidad_api, unidad)
            if convertido is None:
                motivo = f"{item.get('meterName','')}: {fallo}"
                continue
            return Precio(
                convertido, unidad, "api",
                referencia=item.get("meterId", ""),
                nota=f"{item.get('productName','')} / {item.get('meterName','')}",
                unidad_api=unidad_api,
            )
        return PENDIENTE(unidad, motivo)


IDS_GCP_RESPALDO = {
    "cloud run": "152E-C115-5142",
    "cloud storage": "95FF-2EF5-5EA1",
}


class PreciosGCP:
    MAX_PAGINAS = 20
    FICHERO_CLAVE = os.path.join(DIR_ACTUAL, ".gcp_api_key")

    EXCLUSIONES_SIEMPRE = ("commitment", "committed use", "promotional")

    def __init__(self, region="europe-southwest1"):
        self.region = region
        self.clave = self._leer_clave()
        self._servicios = None
        self._skus = {}

    @staticmethod
    def _limpiar_clave(texto):
        limpio = (texto or "").strip().strip("\ufeff\u200b").strip()
        if len(limpio) >= 2 and limpio[0] == limpio[-1] and limpio[0] in "\"'":
            limpio = limpio[1:-1].strip()
        return limpio

    @classmethod
    def _leer_clave(cls):
        clave = cls._limpiar_clave(os.getenv("GCP_BILLING_API_KEY"))
        if clave:
            return clave
        if os.path.isfile(cls.FICHERO_CLAVE):
            with open(cls.FICHERO_CLAVE, encoding="utf-8-sig") as f:
                return cls._limpiar_clave(f.read())
        return ""

    def disponible(self):
        return bool(self.clave)

    def _pedir(self, ruta):
        try:
            return _leer_json(BASE_GCP + ruta, timeout=120,
                              cabeceras={"X-Goog-Api-Key": self.clave})
        except urllib.error.HTTPError as e:
            detalle = ""
            try:
                detalle = json.loads(e.read().decode()).get("error", {}).get("message", "")
            except Exception:
                pass
            if e.code in (401, 403):
                raise RuntimeError(
                    f"la clave no puede leer el catálogo (HTTP {e.code}). {detalle} "
                    "Comprueba que la Cloud Billing API esté habilitada en el proyecto y "
                    "que, si la clave tiene restricción de API, la incluya.")
            raise RuntimeError(f"HTTP {e.code} consultando el catálogo de GCP. {detalle}")
        except Exception as e:
            raise RuntimeError(f"error consultando el catálogo de GCP: {e}")

    def _paginar(self, ruta, campo):
        elementos, token = [], None
        for _ in range(self.MAX_PAGINAS):
            sufijo = f"&pageToken={urllib.parse.quote(token)}" if token else ""
            datos = self._pedir(ruta + sufijo)
            elementos.extend(datos.get(campo, []))
            token = datos.get("nextPageToken")
            if not token:
                break
        return elementos

    def servicios(self):
        if self._servicios is None:
            self._servicios = {
                s.get("displayName", "").strip().lower(): s.get("serviceId")
                for s in self._paginar("/services?pageSize=5000", "services")
            }
        return self._servicios

    def id_servicio(self, *nombres):
        catalogo = self.servicios()
        for nombre in nombres:
            clave = nombre.strip().lower()
            id_servicio = catalogo.get(clave) or IDS_GCP_RESPALDO.get(clave)
            if id_servicio:
                return id_servicio
        raise RuntimeError("ningún servicio del catálogo se llama " + " / ".join(nombres))

    def skus(self, *nombres_servicio):
        id_servicio = self.id_servicio(*nombres_servicio)
        if id_servicio not in self._skus:
            self._skus[id_servicio] = self._paginar(
                f"/services/{id_servicio}/skus?currencyCode=USD&pageSize=5000", "skus")
        return self._skus[id_servicio]

    def _candidatos(self, skus, terminos, excluye):
        exactos, globales = [], []
        fuera = tuple(t.lower() for t in (excluye or ())) + self.EXCLUSIONES_SIEMPRE
        for sku in skus:
            descripcion = sku.get("description", "").lower()
            if not all(t.lower() in descripcion for t in terminos):
                continue
            if any(t in descripcion for t in fuera):
                continue
            regiones = sku.get("serviceRegions", [])
            if self.region in regiones:
                exactos.append(sku)
            elif "global" in regiones:
                globales.append(sku)
        return exactos + globales

    def buscar(self, servicio, contiene, unidad, excluye=None):
        if not self.clave:
            return PENDIENTE(unidad, "define GCP_BILLING_API_KEY (o crea "
                                     "estudio_costes/.gcp_api_key) para consultar el catálogo de GCP")
        nombres = (servicio,) if isinstance(servicio, str) else tuple(servicio)
        try:
            skus = self.skus(*nombres)
        except RuntimeError as e:
            return PENDIENTE(unidad, str(e))

        motivo = f"sin coincidencias en '{nombres[0]}' ({self.region}) para {contiene}"
        for sku in self._candidatos(skus, contiene, excluye):
            for tarifa in sku.get("pricingInfo", []):
                expresion = tarifa.get("pricingExpression", {})
                unidad_api = expresion.get("usageUnitDescription") or expresion.get("usageUnit", "")
                tramos = sorted(expresion.get("tieredRates", []),
                                key=lambda t: float(t.get("startUsageAmount") or 0))
                for tramo in tramos:
                    unidades = int(tramo["unitPrice"].get("units", 0))
                    nanos = int(tramo["unitPrice"].get("nanos", 0))
                    precio = unidades + nanos / 1e9
                    if precio <= 0:
                        continue
                    convertido, fallo = convertir(precio, unidad_api, unidad)
                    if convertido is None:
                        motivo = f"{sku.get('skuId', '')}: {fallo}"
                        continue
                    return Precio(convertido, unidad, "api",
                                  referencia=sku.get("skuId", ""),
                                  nota=sku.get("description", "")[:120],
                                  unidad_api=unidad_api)
        return PENDIENTE(unidad, motivo)


def cargar_precios_manuales():
    ruta = os.path.join(DIR_ACTUAL, "precios_manuales.json")
    if not os.path.isfile(ruta):
        return {}
    with open(ruta, encoding="utf-8") as f:
        return json.load(f)


def precio_manual(manuales, proveedor, concepto, unidad, pendiente_previo=None):
    entrada = manuales.get(proveedor, {}).get(concepto)
    if not entrada or entrada.get("valor_usd") is None:
        motivo = "sin precio: rellénalo en precios_manuales.json con su fuente"
        previo = getattr(pendiente_previo, "nota", "")
        if previo and previo != motivo:
            motivo = f"{previo} | {motivo}"
        return PENDIENTE(unidad, motivo)
    return Precio(
        float(entrada["valor_usd"]), unidad, "manual",
        referencia=entrada.get("fuente", ""),
        nota=f"consultado el {entrada.get('fecha_consulta', '?')}",
    )


def hoy():
    return date.today().isoformat()
