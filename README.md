# Observatorio Global de Conectividad Portuaria (Hinterland)

Código del Trabajo Fin de Máster. Plataforma de análisis geoespacial que evalúa la resiliencia de la red terrestre (hinterland) de los puertos comerciales. Para cada puerto construye un grafo de la red viaria y ferroviaria de su entorno, reparte la demanda del puerto entre los destinos industriales y calcula un **Índice de Estrés Logístico** ($I_{EL}$). Una aplicación web permite consultar los resultados y simular cortes de infraestructura y aumentos de demanda.

## Arquitectura

La infraestructura se define con Terraform y se despliega mediante GitHub Actions en dos nubes.

**AWS (us-west-2): procesamiento**

- **ETL en AWS Batch sobre Fargate Spot.** Cada puerto se procesa en un contenedor independiente (imagen en ECR). Los puertos se agrupan por tamaño (S, M, L) con distintos recursos de CPU y memoria.
- **DuckDB** lee los ficheros GeoParquet de Overture Maps directamente desde S3, filtrando por *bounding box* sin descargar el dataset completo.
- **S3** almacena los resultados curados, cifrados con una clave KMS gestionada. El tráfico entre los contenedores y S3 pasa por un VPC Gateway Endpoint.
- **AWS Budgets** genera alertas de facturación.

**Google Cloud (europe-southwest1): aplicación web**

- **Cloud Run** ejecuta la API (FastAPI) y sirve el frontend. La imagen se publica en Artifact Registry.
- **Load Balancer y Cloud Armor** protegen el servicio frente a SQLi, XSS y abuso volumétrico.
- **Firebase Authentication** controla el acceso a la analítica detallada.
- **Frontend** con MapLibre, PMTiles y deck.gl.
- **Copiloto** basado en Gemini (`gemini-2.5-flash-lite`) que responde preguntas sobre el puerto seleccionado y el escenario simulado. El contexto se construye a partir del registro del puerto y de la sesión de simulación, seleccionando los bloques relevantes para cada pregunta. Las reglas van en `system_instruction` y la consulta del usuario se sanea y delimita antes de incluirla (`app/copiloto.py`).

## Fuentes de datos

| Dimensión | Fuente |
|---|---|
| Red viaria, ferroviaria e industrias | Overture Maps (`transportation`, `places`, `buildings`, `base/land_use`) |
| Volumen diario de los puertos | FMI PortWatch (`Daily_Ports_Data` y catálogo de puertos) |
| Perfil sectorial del comercio exterior | UN Comtrade |
| Altimetría | Copernicus DEM (30 m) |
| Densidad de población | Meta High Resolution Settlement Layer (HRSL) |

## Modelo

### Coste de las aristas

La distancia entre nodos se calcula con la fórmula de Haversine. El coste de cada arista es:

$$W_{ij} = d_{ij} \cdot P_{topo} \cdot P_{urb} \cdot F_{vial} \cdot P_{peso}$$

- **$F_{vial}$**: fricción por tipo de vía (autopista 0,4; primaria 0,7; secundaria y terciaria 2,5; ferrocarril 0,1), dividida entre el número de carriles. Si Overture no publica `lanes`, se usa un valor por defecto por clase. Solo se extraen las clases `motorway` a `tertiary`.
- **$P_{topo}$**: penalización por pendiente a partir del DEM, $1 + 10 \cdot \nabla_{ij}$ en subida y 1 en bajada. La pendiente se limita al 15 % en carretera y al 4 % en ferrocarril.
- **$P_{urb}$**: $1 + \rho_{ij}/10\,000$, con $\rho$ la densidad de población (hab/km²) calculada a partir de HRSL en una ventana de 5×5 píxeles.
- **$P_{peso}$**: factor 50 si la vía tiene un límite de peso inferior a 40 t (convirtiendo la unidad declarada). Las vías prohibidas a vehículos pesados no generan arista.

### Reparto de la demanda

Modelo de gravedad con restricción de producción sobre las industrias generadoras de carga (logística, almacenes, fábricas, química, alimentación, etc.). La masa $M_k$ es la superficie edificada del recinto industrial:

$$T_k = V \cdot \frac{M_k \, e^{-\beta C_k}}{\sum_j M_j \, e^{-\beta C_j}}$$

donde $C_k$ es el coste mínimo desde el puerto, $V$ el volumen movible por carretera y $\beta = 0{,}03$. La búsqueda del nodo más cercano a cada industria usa un KD-Tree sobre coordenadas proyectadas a kilómetros. La función de potencia inversa está disponible como alternativa (`funcion_disuasion="potencia"`). Las cuotas sectoriales de UN Comtrade se calculan sobre peso neto e incluyen importación y exportación.

### Índice de Estrés Logístico

$$I_{EL} = 5 \cdot S + 5 \cdot V, \qquad S, V \in [0, 1]$$

**Saturación ($S$).** La serie diaria del puerto se divide en un periodo base y una ventana con los últimos 365 días. $S$ es la fracción de días de la ventana en los que el volumen supera el percentil 95 del periodo base. Para los puertos sin serie diaria se usa un cociente frente a una capacidad de referencia; ese índice no es comparable con el anterior y se marca con `indice_comparable = false`.

**Vulnerabilidad ($V$).** Se eliminan, de una en una, las `n_aristas_criticas` aristas con más tráfico (en ambos sentidos) y se mide el incremento relativo del coste de servir la demanda:

$$\Delta = \max_e \frac{C(G \setminus e) - C(G)}{C(G)}, \qquad V = 1 - e^{-\lambda \Delta}, \quad \lambda = 3$$

La demanda que queda desconectada se valora a `penalizacion_desconexion` veces su coste medio en la red intacta.

**Puertas del puerto.** El origen de los caminos mínimos son los accesos del recinto portuario a la red. Se obtienen del polígono portuario de Overture (`perimetro_overture`), de las vías en un radio de 3 km (`respaldo_radio`) o, en último caso, de un nodo artificial (`nodo_artificial`).

**Simulación.** Al cortar vías, la fracción $A$ de demanda que queda aislada eleva el índice: $I_{EL}^{sim} = I_{EL} + A \cdot (10 - I_{EL})$. El multiplicador de demanda solo afecta a la saturación.

La definición del índice y del mapa de calor está en `etl/calculos.py`, con una copia idéntica en `app/` comprobada por `tests/test_sincronizacion.py`. Todos los parámetros del modelo están en el diccionario `PARAMETROS` de `etl/etl_procesamiento.py`.

### Mapa de calor

La intensidad de cada vía es el tráfico de su tramo más cargado dividido entre el percentil 95 del tráfico de las aristas viarias del puerto (máximo 100). La escala es relativa a cada puerto, por lo que los colores de dos puertos distintos no son comparables.

## Simulación interactiva

La aplicación permite:

1. **Shock de demanda**: aplicar un multiplicador al volumen del puerto.
2. **Corte de vías**: trazar una línea sobre el mapa. Las aristas que cruza se desactivan, el tráfico se recalcula y se muestra qué vías absorben el desvío y qué parte de la demanda queda aislada.

Ambas operaciones usan un WebSocket. El servicio de Cloud Run tiene un `timeout` de 3600 s para que las sesiones largas no se corten, y el frontend vuelve a aplicar los cortes de la sesión si la conexión se reinicia.

## Estructura del repositorio

| Ruta | Contenido |
|---|---|
| `app/` | API (FastAPI), copiloto y frontend (`static/index.html`) |
| `etl/` | Extracción, construcción del grafo, cálculo del índice y generación de informes |
| `estudio_costes/` | Comparativa de costes AWS / GCP / Azure |
| `terraform/` | Infraestructura en AWS y GCP |
| `.github/workflows/` | Despliegue, ETL, informes y tests |
| `tests/` | Tests unitarios (pytest) |
| `docs/` | Informes generados (resultados, cobertura, volumen, sensibilidad y costes) |
| `config.env` | Nombres de buckets y región de AWS |

## Configuración

Los nombres de los buckets y la región están en `config.env`; el resto del código los lee de ahí (o de variables de entorno con el mismo nombre):

```env
S3_BUCKET_NAME=<bucket de datos curados>
TF_STATE_BUCKET=<bucket del estado de Terraform>
AWS_REGION=<región>
```

Los workflows necesitan además los secretos de GitHub con las credenciales de AWS y GCP y las claves de las APIs (Gemini, UN Comtrade).

## Ejecución

| Workflow | Función |
|---|---|
| `pipeline_completo.yml` | Ejecuta la cadena completa: despliegue, imagen del ETL, ETL, mapa global, informes y, opcionalmente, destrucción |
| `terraform.yml` | Construye la imagen de la API y despliega la infraestructura |
| `compilar_docker_base.yml` | Construye la imagen del ETL y la sube a ECR |
| `etl_python.yml` | Selecciona la muestra de puertos y lanza los trabajos de Batch |
| `compilar_pmtiles.yml` | Genera el mapa global en formato PMTiles |
| `cobertura.yml`, `resultados.yml`, `sensibilidad.yml`, `costes.yml` | Generan los informes de `docs/` |
| `destroy.yml` | Destruye la infraestructura con Terraform |
| `tests.yml` | Ejecuta los tests en cada push |

Tests en local:

```bash
pip install -r requirements-dev.txt
python -m pytest tests/
```

## Informes

| Informe | Generador |
|---|---|
| [`docs/resultados/`](docs/resultados/) | `etl/generar_resultados.py` |
| [`docs/cobertura/`](docs/cobertura/) | `etl/comprobar_cobertura.py` |
| [`docs/volumen/`](docs/volumen/) | `etl/medir_volumen.py` |
| [`docs/sensibilidad/`](docs/sensibilidad/) | `etl/analisis_sensibilidad.py` |
| [`docs/costes/`](docs/costes/) | `estudio_costes/generar_informe.py` |

Cada resultado registra la release de Overture utilizada (`overture_release`), ya que Overture conserva cada release unos 60 días.

## Limitaciones

- Los coeficientes de fricción, los factores de pendiente, el divisor de densidad urbana, la cuota ferroviaria, $\beta$, $\lambda$ y la penalización por desconexión son parámetros del modelo; su influencia se mide en el análisis de sensibilidad.
- El índice de los puertos con volumen estimado no es comparable con el de los puertos con serie diaria, y se presentan por separado.
- En los puertos de granel puro el volumen movible por carretera es nulo y el modelo no es aplicable.
- Se excluyen las terminales offshore (`portid` con prefijo `fso`), que no tienen red viaria asociada.
