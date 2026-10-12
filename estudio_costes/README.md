# Estudio comparativo de costes: AWS vs GCP vs Azure

Valora el mismo sistema en AWS, GCP y Azure a partir de las listas de precios públicas y genera el informe de `docs/costes/`.

```bash
python estudio_costes/generar_informe.py --salida docs/costes
```

## Metodología

- `perfil_carga.py` describe el consumo mensual en magnitudes independientes del proveedor (vCPU·h, GB·h, GB·mes, GB de salida, millares de peticiones, millones de tokens). Las tres nubes se valoran sobre las mismas cantidades.
- `catalogo_precios.py` consulta los catálogos oficiales: AWS Price List, Azure Retail Prices y Cloud Billing Catalog de GCP.
- `generar_informe.py` calcula el coste de cada concepto y escribe el informe en Markdown y JSON.

Cada precio indica su origen:

| Origen | Significado |
|---|---|
| `api` | Obtenido del catálogo oficial, con el identificador del SKU |
| `manual` | Tomado de `precios_manuales.json`, con fuente y fecha de consulta |
| `pendiente` | No resuelto; el total del proveedor queda incompleto |

El descuento por capacidad interrumpible (`DESCUENTO_INTERRUMPIBLE`) solo se aplica a AWS (Fargate Spot, 70 %). Cloud Run y Container Apps no publican tarifas spot y se valoran a precio de lista.

## Notas sobre los catálogos

La selección de cada SKU está cubierta por `tests/test_costes.py`.

1. Las unidades de facturación difieren (Azure cobra Container Apps por segundo y las operaciones de Blob por bloques de 10.000). Todas se normalizan con `convertir()`.
2. El egress de AWS está en `AWSDataTransfer` (0,09 $/GB). En `AmazonS3` solo aparece el de Multi-Region Access Point (0,0033 $/GB).
3. La Retail API de Azure y el catálogo de GCP están paginados (`NextPageLink`, `nextPageToken`).
4. En Azure Blob Storage la redundancia aparece en unos meters y no en otros (`Hot LRS Write Operations` frente a `Hot Read Operations`), por lo que cada concepto usa su propio término de búsqueda.
5. Azure Container Registry cobra una cuota fija diaria (Basic: 0,1666 $/día) que incluye 10 GB. La tabla usa el meter `Data Stored` y la diferencia se detalla aparte (`ARQUITECTURA_NO_COMPARABLE`).
6. En GCP cada concepto se busca en su servicio: Artifact Registry para el registro de contenedores y Cloud Logging para los logs. Las unidades vienen en palabras (`gibibyte`).
7. En Cloud Run, `Jobs CPU` (0,000018 $/s) y `Services CPU` (0,000024 $/s) tienen precios distintos; el ETL se valora con la tarifa de Jobs.
8. Los términos de búsqueda de GCP son los nombres literales del catálogo, ya que en Cloud Run conviven `Services CPU` e `Instances CPU` con una diferencia de precio de 66×. Si un SKU cambia de nombre, el concepto aparece como pendiente.
9. En Azure, los logs equivalentes a CloudWatch Logs están en `Log Analytics` (`Analytics Logs Data Ingestion`), y los modelos de lenguaje en `Foundry Models`. Se toma el precio marginal, sin capa gratuita.
10. En AWS las tarifas por token con identificación del modelo están en el catálogo `AmazonBedrock`. Se filtra por inferencia bajo demanda, ya que la inferencia en lote tiene otro precio.

## Requisitos

- AWS y Azure: no requieren credenciales.
- GCP: requiere una clave de API con la Cloud Billing API habilitada, en la variable `GCP_BILLING_API_KEY` o en el fichero `estudio_costes/.gcp_api_key` (excluido del repositorio). La clave se envía en la cabecera `X-Goog-Api-Key`. Sin clave, los conceptos de GCP quedan pendientes.
- La tarifa de la Gemini API (`gemini-2.5-flash-lite`) no está en la Cloud Billing API y se toma de `precios_manuales.json`.

Para localizar el nombre de un SKU de GCP:

```bash
python estudio_costes/explorar_gcp.py --servicios logging
python estudio_costes/explorar_gcp.py --servicio "Cloud Run" --contiene cpu
```
