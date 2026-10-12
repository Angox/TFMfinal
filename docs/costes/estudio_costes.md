# Estudio comparativo de costes: AWS vs GCP vs Azure

_Generado el 2026-08-31._

## Metodología

Comparación modelada: se aplican las listas de precios públicas de cada proveedor a un perfil de carga común. Complementa al coste medido en AWS Cost Explorer y en la facturación de GCP, y estima el coste que habría tenido el despliegue en otra nube. En cada desglose, coste = cantidad × precio efectivo.

### Capacidad interrumpible

El descuento por capacidad interrumpible solo se aplica donde el proveedor lo ofrece para el servicio utilizado:

| Proveedor | Descuento aplicado | Motivo |
|---|---|---|
| AWS | 70% | Fargate Spot, configuración desplegada. Porcentaje estimado. |
| GCP | 0% | Ninguno de los 703 SKU de Cloud Run es spot o preemptible. Precio de lista. |
| Azure | 0% | Container Apps no publica tarifa spot ni low-priority en esta región. Precio de lista. |

### Partidas con modelo de precios no equivalente

Diferencias en el modelo de precios que no se reflejan en el precio unitario de la tabla:

- **AZURE · `registro_contenedores_gb_mes`** — Azure Container Registry cobra una cuota fija por registro y día además del $/GB·mes de la tabla: 0,1666 $/día en Basic (~5,07 $/mes), 0,6666 en Standard y 1,6666 en Premium. La cuota incluye 10 GB de almacenamiento en Basic, por lo que con los 6 GB de este perfil solo se paga la cuota fija. ECR y Artifact Registry cobran únicamente por GB·mes, de modo que el registro cuesta ~5,07 $/mes en Azure frente a 0,60 $/mes en AWS y GCP.

## Perfil de carga

| Magnitud | Valor |
|---|---|
| puertos_procesados_mes | 40 |
| puertos_por_talla | {'S': 30, 'M': 8, 'L': 2} |
| horas_contenedor_etl | 27.0 |
| vcpu_hora_lote | 47.0 |
| gb_hora_lote | 188.0 |
| fraccion_interrumpible | 1.0 |

## Equivalencia de servicios

| Concepto | AWS | GCP | Azure |
|---|---|---|---|
| `computo_lote_vcpu_h` | AWS Batch sobre Fargate Spot | Cloud Run Jobs | Container Apps Jobs |
| `computo_lote_gb_h` | AWS Batch sobre Fargate Spot | Cloud Run Jobs | Container Apps Jobs |
| `computo_web_vcpu_h` | ECS Fargate | Cloud Run | Container Apps |
| `computo_web_gb_h` | ECS Fargate | Cloud Run | Container Apps |
| `almacenamiento_gb_mes` | S3 Standard | Cloud Storage Standard | Blob Storage Hot |
| `salida_internet_gb` | S3 Data Transfer Out | Network Egress | Bandwidth Data Transfer Out |
| `peticiones_escritura_millar` | S3 PUT | Cloud Storage Class A | Blob Write Operations |
| `peticiones_lectura_millar` | S3 GET | Cloud Storage Class B | Blob Read Operations |
| `registro_contenedores_gb_mes` | ECR | Artifact Registry | Container Registry |
| `logs_gb` | CloudWatch Logs | Cloud Logging | Azure Monitor Logs |
| `llm_tokens_entrada_millon` | Bedrock · Nova Lite | Gemini API · gemini-2.5-flash-lite | Foundry Models · gpt-4.1-nano |
| `llm_tokens_salida_millon` | Bedrock · Nova Lite | Gemini API · gemini-2.5-flash-lite | Foundry Models · gpt-4.1-nano |

## Coste mensual estimado

| Proveedor | Región | Coste mensual (USD) | Coste por puerto (USD) | Conceptos sin precio |
|---|---|---|---|---|
| AWS | us-west-2 | 31.92 | 0.7980 | — |
| GCP | europe-southwest1 | 63.35 | 1.5837 | — |
| AZURE | westeurope | 93.09 | 2.3273 | — |

## Desglose · AWS

| Concepto | Cantidad | Unidad | Precio lista (USD) | Dto. | Precio efectivo (USD) | Coste (USD) | Origen | Referencia |
|---|---|---|---|---|---|---|---|---|
| `computo_lote_vcpu_h` | 47.0 | vCPU·h | 0.040480 | 70% | 0.012144 | 0.5708 | api | AmazonECS/EKCCQUSFCBDDTKTS |
| `computo_lote_gb_h` | 188.0 | GB·h | 0.004445 | 70% | 0.001334 | 0.2507 | api | AmazonECS/NTC2QZFJW79R5XVK |
| `computo_web_vcpu_h` | 480.0 | vCPU·h | 0.040480 | 0% | 0.040480 | 19.4304 | api | AmazonECS/EKCCQUSFCBDDTKTS |
| `computo_web_gb_h` | 960.0 | GB·h | 0.004445 | 0% | 0.004445 | 4.2672 | api | AmazonECS/NTC2QZFJW79R5XVK |
| `almacenamiento_gb_mes` | 60.0 | GB·mes | 0.023000 | 0% | 0.023000 | 1.3800 | api | AmazonS3/Z3FQZG73HYSPVABR |
| `salida_internet_gb` | 40.0 | GB | 0.090000 | 0% | 0.090000 | 3.6000 | api | AWSDataTransfer/5M4327XEUKBBTWAT |
| `peticiones_escritura_millar` | 60.0 | millar | 0.005000 | 0% | 0.005000 | 0.3000 | api | AmazonS3/D4PMUVH6F64HK2D6 |
| `peticiones_lectura_millar` | 400.0 | millar | 0.000400 | 0% | 0.000400 | 0.1600 | api | AmazonS3/E77AQEM2DC4VV3FC |
| `registro_contenedores_gb_mes` | 6.0 | GB·mes | 0.100000 | 0% | 0.100000 | 0.6000 | api | AmazonECR/2BSQ677HKG6WUUKA |
| `logs_gb` | 2.0 | GB | 0.500000 | 0% | 0.500000 | 1.0000 | api | AmazonCloudWatch/CWY7X4MZ4F3MP5SD |
| `llm_tokens_entrada_millon` | 4.0 | millón de tokens | 0.060000 | 0% | 0.060000 | 0.2400 | api | AmazonBedrock/HJN3FHKSCN79D72P |
| `llm_tokens_salida_millon` | 0.5 | millón de tokens | 0.240000 | 0% | 0.240000 | 0.1200 | api | AmazonBedrock/KCCADSF94FEZMYTQ |

## Desglose · GCP

| Concepto | Cantidad | Unidad | Precio lista (USD) | Dto. | Precio efectivo (USD) | Coste (USD) | Origen | Referencia |
|---|---|---|---|---|---|---|---|---|
| `computo_lote_vcpu_h` | 47.0 | vCPU·h | 0.064800 | 0% | 0.064800 | 3.0456 | api | 4135-2C0E-5486 |
| `computo_lote_gb_h` | 188.0 | GB·h | 0.007200 | 0% | 0.007200 | 1.3536 | api | 32FA-1494-0648 |
| `computo_web_vcpu_h` | 480.0 | vCPU·h | 0.086400 | 0% | 0.086400 | 41.4720 | api | 4856-B847-F1EB |
| `computo_web_gb_h` | 960.0 | GB·h | 0.009000 | 0% | 0.009000 | 8.6400 | api | 02A2-9231-36A6 |
| `almacenamiento_gb_mes` | 60.0 | GB·mes | 0.023000 | 0% | 0.023000 | 1.3800 | api | 5596-85FF-7F53 |
| `salida_internet_gb` | 40.0 | GB | 0.120000 | 0% | 0.120000 | 4.8000 | api | 22EB-AAE8-FBCD |
| `peticiones_escritura_millar` | 60.0 | millar | 0.005000 | 0% | 0.005000 | 0.3000 | api | 4DBF-185F-A415 |
| `peticiones_lectura_millar` | 400.0 | millar | 0.000400 | 0% | 0.000400 | 0.1600 | api | 7870-010B-2763 |
| `registro_contenedores_gb_mes` | 6.0 | GB·mes | 0.100000 | 0% | 0.100000 | 0.6000 | api | 8502-299A-ABAF |
| `logs_gb` | 2.0 | GB | 0.500000 | 0% | 0.500000 | 1.0000 | api | 143F-A1B0-E0BE |
| `llm_tokens_entrada_millon` | 4.0 | millón de tokens | 0.100000 | 0% | 0.100000 | 0.4000 | manual | https://ai.google.dev/gemini-api/docs/pricing |
| `llm_tokens_salida_millon` | 0.5 | millón de tokens | 0.400000 | 0% | 0.400000 | 0.2000 | manual | https://ai.google.dev/gemini-api/docs/pricing |

## Desglose · AZURE

| Concepto | Cantidad | Unidad | Precio lista (USD) | Dto. | Precio efectivo (USD) | Coste (USD) | Origen | Referencia |
|---|---|---|---|---|---|---|---|---|
| `computo_lote_vcpu_h` | 47.0 | vCPU·h | 0.122400 | 0% | 0.122400 | 5.7528 | api | 0426badc-b719-5201-b141-b2d5c4943b7d |
| `computo_lote_gb_h` | 188.0 | GB·h | 0.014400 | 0% | 0.014400 | 2.7072 | api | 3ba64b1c-cb46-5ee0-b086-a68736392ac0 |
| `computo_web_vcpu_h` | 480.0 | vCPU·h | 0.122400 | 0% | 0.122400 | 58.7520 | api | 0426badc-b719-5201-b141-b2d5c4943b7d |
| `computo_web_gb_h` | 960.0 | GB·h | 0.014400 | 0% | 0.014400 | 13.8240 | api | 3ba64b1c-cb46-5ee0-b086-a68736392ac0 |
| `almacenamiento_gb_mes` | 60.0 | GB·mes | 0.019600 | 0% | 0.019600 | 1.1760 | api | 10e5ee74-8fd6-4972-909f-65a83f92f0ce |
| `salida_internet_gb` | 40.0 | GB | 0.080000 | 0% | 0.080000 | 3.2000 | api | 6bd64e8e-5cb9-49d3-893d-800c9b28dca3 |
| `peticiones_escritura_millar` | 60.0 | millar | 0.005400 | 0% | 0.005400 | 0.3240 | api | 15adff7b-0dab-4c00-889d-caa6d4fb31bb |
| `peticiones_lectura_millar` | 400.0 | millar | 0.000430 | 0% | 0.000430 | 0.1720 | api | 36c961e5-3c53-4481-b339-a10c6fe0f491 |
| `registro_contenedores_gb_mes` | 6.0 | GB·mes | 0.100000 | 0% | 0.100000 | 0.6000 | api | 6331e61c-1b44-4a10-9fb1-e9c0b470c4d5 |
| `logs_gb` | 2.0 | GB | 2.990000 | 0% | 2.990000 | 5.9800 | api | e5626349-2f1f-4563-babc-dc9219884716 |
| `llm_tokens_entrada_millon` | 4.0 | millón de tokens | 0.100000 | 0% | 0.100000 | 0.4000 | api | 1effcc69-0db0-5dac-bae3-2c535666a69a |
| `llm_tokens_salida_millon` | 0.5 | millón de tokens | 0.400000 | 0% | 0.400000 | 0.2000 | api | 23ecd3a3-fb6d-5e97-8366-7d85b9a570bc |
