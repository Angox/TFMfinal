import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from catalogo_precios import PreciosGCP


def _precio_legible(sku):
    for tarifa in sku.get("pricingInfo", []):
        expresion = tarifa.get("pricingExpression", {})
        unidad = expresion.get("usageUnitDescription") or expresion.get("usageUnit", "")
        for tramo in sorted(expresion.get("tieredRates", []),
                            key=lambda t: float(t.get("startUsageAmount") or 0)):
            valor = (int(tramo["unitPrice"].get("units", 0))
                     + int(tramo["unitPrice"].get("nanos", 0)) / 1e9)
            if valor > 0:
                return f"{valor:.10f} USD/{unidad}"
    return "(sin tramo de pago)"


def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="Explora el catálogo de precios de GCP")
    ap.add_argument("--servicios", nargs="?", const="", metavar="TEXTO",
                    help="lista los servicios cuyo nombre contenga TEXTO")
    ap.add_argument("--servicio", help="nombre visible del servicio, p. ej. 'Cloud Storage'")
    ap.add_argument("--contiene", nargs="*", default=[],
                    help="términos que deben aparecer todos en la descripción del SKU")
    ap.add_argument("--region", default="europe-southwest1")
    ap.add_argument("--todas-las-regiones", action="store_true",
                    help="no filtrar por región (útil para ver si el SKU existe en otra)")
    args = ap.parse_args()

    p = PreciosGCP(args.region)
    if not p.disponible():
        print("Falta la clave: exporta GCP_BILLING_API_KEY o crea estudio_costes/.gcp_api_key")
        return 1

    if args.servicios is not None:
        catalogo = p.servicios()
        filtro = args.servicios.lower()
        encontrados = sorted(n for n in catalogo if filtro in n)
        for nombre in encontrados:
            print(f"{catalogo[nombre]}  {nombre}")
        print(f"\n{len(encontrados)} servicio(s).")
        return 0

    if not args.servicio:
        ap.error("indica --servicios para listar servicios o --servicio para listar sus SKU")

    try:
        skus = p.skus(args.servicio)
    except RuntimeError as e:
        print(f"Error: {e}")
        return 1

    terminos = [t.lower() for t in args.contiene]
    mostrados = 0
    for sku in skus:
        descripcion = sku.get("description", "")
        if not all(t in descripcion.lower() for t in terminos):
            continue
        regiones = sku.get("serviceRegions", [])
        if not args.todas_las_regiones and args.region not in regiones and "global" not in regiones:
            continue
        mostrados += 1
        print(f"{sku.get('skuId','')}  {descripcion}")
        print(f"    {_precio_legible(sku)}   regiones: {', '.join(regiones[:6])}"
              f"{'...' if len(regiones) > 6 else ''}")
    print(f"\n{mostrados} SKU de {len(skus)} en '{args.servicio}'"
          f"{'' if args.todas_las_regiones else f' visibles en {args.region}'}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
