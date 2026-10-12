import math

RADIO_TIERRA_KM = 6371.0

NULOS_FMI = ("none", "nan", "null", "")


def safe_float(val, default=0.0):
    if val is None or str(val).strip().lower() in NULOS_FMI:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def calcular_distancia_haversine(lon1, lat1, lon2, lat2):
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2.0) ** 2 + \
        math.cos(phi1) * math.cos(phi2) * \
        math.sin(delta_lambda / 2.0) ** 2

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return RADIO_TIERRA_KM * c


def clasificar_por_categoria_overture(categoria, mapeo_sectores, por_defecto=None):
    cat = str(categoria or "").lower()
    if not cat:
        return por_defecto

    for sector, config in mapeo_sectores.items():
        categorias = config["overture_cats"] if isinstance(config, dict) else config
        if any(clave in cat for clave in categorias):
            return sector
    return por_defecto


def clasificar_por_codigo_hs(cmd_code, mapeo_sectores, por_defecto="generico_logistica"):
    if cmd_code is None:
        return por_defecto

    codigo = str(cmd_code).strip()
    if codigo.isdigit() and len(codigo) == 1:
        codigo = codigo.zfill(2)

    for sector, hs_codes in mapeo_sectores.items():
        codigos = hs_codes["hs_codes"] if isinstance(hs_codes, dict) else hs_codes
        if codigo in codigos:
            return sector
    return por_defecto


def ruta_tesela_dem(lat, lon, bucket="copernicus-dem-30m"):
    lat_i, lon_i = math.floor(lat), math.floor(lon)
    ns = "N" if lat_i >= 0 else "S"
    ew = "E" if lon_i >= 0 else "W"
    nombre = (f"Copernicus_DSM_COG_10_{ns}{abs(lat_i):02d}_00"
              f"_{ew}{abs(lon_i):03d}_00_DEM")
    return f"s3://{bucket}/{nombre}/{nombre}.tif"


FACTORES_A_TONELADA = {
    "t": 1.0, "tonne": 1.0, "tonnes": 1.0, "ton": 1.0, "mt": 1.0,
    "kg": 0.001, "kilogram": 0.001, "kilograms": 0.001,
    "lb": 0.000453592, "lbs": 0.000453592, "pound": 0.000453592,
    "pounds": 0.000453592,
    "st": 0.907185, "short_ton": 0.907185, "shortton": 0.907185,
}


def normalizar_tonelaje(valor, unidad=None, por_defecto=None):
    if valor is None:
        return por_defecto
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return por_defecto
    if numero <= 0:
        return por_defecto

    if unidad is None or str(unidad).strip() == "":
        return numero

    factor = FACTORES_A_TONELADA.get(str(unidad).strip().lower())
    if factor is None:
        return por_defecto
    return numero * factor


def pendiente_entre_nodos(alt1, alt2, distancia_km, pendiente_maxima=None):
    if alt1 is None or alt2 is None:
        return 0.0
    if distancia_km is None or distancia_km <= 0:
        return 0.0
    pendiente = ((alt2 - alt1) / 1000.0) / distancia_km
    if pendiente_maxima is not None:
        pendiente = max(-pendiente_maxima, min(pendiente_maxima, pendiente))
    return pendiente


def penalizacion_topografica(pendiente, factor):
    if pendiente <= 0:
        return 1.0
    return 1.0 + factor * pendiente


def proyectar_local(lon, lat, lon_ref, lat_ref):
    factor_lon = math.cos(math.radians(lat_ref))
    x = (lon - lon_ref) * factor_lon * (math.pi / 180.0) * RADIO_TIERRA_KM
    y = (lat - lat_ref) * (math.pi / 180.0) * RADIO_TIERRA_KM
    return x, y


def vulnerabilidad_normalizada(incremento_relativo, lam):
    if incremento_relativo is None or incremento_relativo <= 0:
        return 0.0
    if lam is None or lam <= 0:
        return 0.0
    return 1.0 - math.exp(-lam * float(incremento_relativo))


def indice_compuesto(saturacion, vulnerabilidad, peso_saturacion=5.0,
                     peso_vulnerabilidad=5.0):
    sat = min(max(float(saturacion or 0.0), 0.0), 1.0)
    vul = min(max(float(vulnerabilidad or 0.0), 0.0), 1.0)
    total = sat * peso_saturacion + vul * peso_vulnerabilidad
    return min(max(total, 0.0), peso_saturacion + peso_vulnerabilidad)


def saturacion_con_shock(saturacion, multiplicador):
    return min(max(float(saturacion or 0.0) * float(multiplicador), 0.0), 1.0)


def estres_con_aislamiento(estres_red, fraccion_aislada, maximo=10.0):
    fraccion = min(max(float(fraccion_aislada or 0.0), 0.0), 1.0)
    base = min(max(float(estres_red or 0.0), 0.0), maximo)
    return min(max(base + fraccion * (maximo - base), 0.0), maximo)


FUNCIONES_DISUASION = ("exponencial", "potencia")


def fuerza_gravitatoria(masa, coste, funcion="exponencial", exponente=2.0,
                        beta=0.03):
    if masa is None or masa <= 0:
        return None
    if coste is None or coste < 0:
        return None

    if funcion == "potencia":
        if coste <= 0:
            return None
        return masa / (coste ** exponente)

    if funcion != "exponencial":
        raise ValueError(f"función de disuasión desconocida: {funcion!r}")
    return masa * math.exp(-beta * coste)


def semivida_disuasion(beta):
    if beta is None or beta <= 0:
        return float("inf")
    return math.log(2.0) / beta


def percentil_trafico(valores, q=0.95):
    positivos = sorted(v for v in valores if v > 0)
    if not positivos:
        return 0.0
    indice = min(int(len(positivos) * q), len(positivos) - 1)
    return positivos[indice]


def intensidad_visual(traficos_de_tramos, denominador):
    if not traficos_de_tramos or not denominador or denominador <= 0:
        return 0.0
    return min(max(traficos_de_tramos) / denominador * 100.0, 100.0)
