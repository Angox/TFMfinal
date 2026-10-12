# Resultados

Generado el 2026-08-29 a partir de `s3://tfm-datos-curados-hinterland-26`.

## 1. Cobertura del procesamiento

| Métrica | Valor |
|---|---|
| Puertos con resultados | 1824 |
| Puertos fallidos | 3 |
| Tasa de éxito | 99.8 % |
| Países representados | 178 |

**Motivos de fallo**

| Motivo | Puertos |
|---|---|
| `sin_vias_en_overture` | 3 |

## 2. Distribución del Índice de Estrés Logístico

> El I_EL de un puerto con volumen medido usa como saturación la frecuencia con la que ha superado su capacidad demostrada; el de un puerto con volumen estimado usa un cociente contra una constante de 8.000. Las dos escalas no son comparables y se separan en el apartado 2.1.

| Estadístico | I_EL | Riesgo macroeconómico | Volumen diario |
|---|---|---|---|
| n | 1824 | 1824 | 1824 |
| min | 0.0 | 0.0 | 0 |
| p25 | 0.49 | 0.0 | 5149.5 |
| mediana | 1.82 | 0.01 | 17906.5 |
| p75 | 4.4 | 0.09 | 44823.5 |
| max | 10.0 | 6.33 | 2376193 |
| media | 2.352 | 0.267 | 47605.779 |
| desviacion | 2.004 | 0.811 | 126973.505 |

**Clasificación de riesgo**

| Nivel | Puertos | % |
|---|---|---|
| BAJO | 1308 | 71.7 % |
| MODERADO | 509 | 27.9 % |
| ALTO | 7 | 0.4 % |

**Procedencia del volumen**

| Origen | Puertos | % |
|---|---|---|
| Medido (FMI Daily_Ports_Data, toneladas) | 1679 | 92.1 % |
| Estimado por recuento de escalas | 145 | 7.9 % |

### 2.1 Distribución por escala

| Estadístico | I_EL comparable (medido) | I_EL estimado |
|---|---|---|
| n | 1264 | 560 |
| min | 0.0 | 0.0 |
| p25 | 0.72 | 0.0 |
| mediana | 2.0 | 1.25 |
| p75 | 4.36 | 4.607 |
| max | 6.78 | 10.0 |
| media | 2.456 | 2.119 |
| desviacion | 1.883 | 2.236 |

### 2.2 Composición del índice

| Estadístico | Saturación [0-1] | Vulnerabilidad [0-1] |
|---|---|---|
| n | 1824 | 1824 |
| min | 0.0 | 0.0 |
| p25 | 0.003 | 0.029 |
| mediana | 0.044 | 0.301 |
| p75 | 0.076 | 0.816 |
| max | 1.0 | 1.0 |
| media | 0.059 | 0.411 |
| desviacion | 0.08 | 0.386 |

**Método de detección de las puertas del puerto**

| Origen | Puertos |
|---|---|
| `respaldo_radio` | 1703 |
| `nodo_artificial` | 121 |

> Con `nodo_artificial` todo el flujo sale de un único punto sintético y el término de vulnerabilidad no refleja la red viaria real.

## 3. Puertos con mayor estrés logístico

### 3.1 Volumen medido (escala comparable)

| # | Puerto | País | I_EL | Saturación | Vulnerabilidad | Volumen/día | Capacidad | Vías |
|---|---|---|---|---|---|---|---|---|
| 1 | Fujairah | United Arab Emirates | 6.78 | 0.4731 | 0.8819 | 210783 | 12160 | 11565 |
| 2 | Rørvik | Norway | 6.6 | 0.3194 | 1.0 | 8944 | 2732 | 1009 |
| 3 | Kamsar | Guinea | 6.46 | 0.2917 | 0.9997 | 65231 | 8121 | 1094 |
| 4 | Kâmpóng Saôm | Cambodia | 6.33 | 0.2667 | 1.0 | 21733 | 14502 | 2120 |
| 5 | Funchal, Madeira | Portugal | 6.26 | 0.3444 | 0.9077 | 10945 | 4133 | 5206 |
| 6 | Luwuk | Indonesia | 6.25 | 0.25 | 1.0 | 2551 | 1932 | 1289 |
| 7 | Taressa | Guinea | 6.08 | 0.215 | 1.0 | 7906 | 4385 | 1049 |
| 8 | Lobito | Angola | 6.04 | 0.2083 | 1.0 | 12571 | 7274 | 1846 |
| 9 | Lekki | Nigeria | 6.0 | 0.2 | 1.0 | 44069 | 16567 | 3750 |
| 10 | Iligan | Philippines | 5.88 | 0.2 | 0.9764 | 28188 | 4259 | 8449 |
| 11 | Waingapu | Indonesia | 5.88 | 0.1892 | 0.987 | 2000 | 1769 | 1177 |
| 12 | Walvis Bay | Namibia | 5.88 | 0.1811 | 0.9958 | 32687 | 14697 | 1337 |
| 13 | Tema | Ghana | 5.86 | 0.2401 | 0.9323 | 70584 | 50528 | 17264 |
| 14 | Augusta | Italy | 5.77 | 0.1622 | 0.9915 | 71640 | 6678 | 33592 |
| 15 | Monrovia | Liberia | 5.76 | 0.1515 | 1.0 | 33854 | 9930 | 3573 |

### 3.2 Volumen estimado por escalas (escala no comparable con 3.1)

| # | Puerto | País | I_EL | Saturación | Vulnerabilidad | Volumen/día | Capacidad | Vías |
|---|---|---|---|---|---|---|---|---|
| 1 | Yawatahama | Japan | 10.0 | 1.0 | 1.0 | 1741 | 110 | 16676 |
| 2 | Amlan | Philippines | 7.5 | 0.5 | 1.0 | 29417 | 4709 | 4895 |
| 3 | Bayovar | Peru | 7.5 | 0.5 | 1.0 | 60755 | 20569 | 1884 |
| 4 | Carinhoso | Brazil | 7.5 | 0.5 | 1.0 | 27212 | 12800 | 8342 |
| 5 | Malau | Fiji | 7.5 | 0.5 | 1.0 | 7089 | 5610 | 713 |
| 6 | Trombetas | Brazil | 7.5 | 0.5 | 1.0 | 71754 | 10505 | 139 |
| 7 | Port Giles | Australia | 7.14 | 0.5 | 0.9287 | 52783 | 15377 | 473 |
| 8 | Dhamra Port | India | 6.67 | 0.3333 | 1.0 | 104700 | 18433 | 897 |
| 9 | Goose Bay | Canada | 6.67 | 0.3333 | 1.0 | 12635 | 5100 | 119 |
| 10 | Kårstø | Norway | 6.67 | 0.3333 | 1.0 | 19040 | 896 | 9929 |
| 11 | Karaikal | India | 6.66 | 0.3333 | 0.9983 | 69503 | 7625 | 14883 |
| 12 | Bullen Baai | Curaçao | 6.64 | 0.3333 | 0.9952 | 89594 | 52848 | 3227 |
| 13 | Calabar | Nigeria | 6.51 | 0.3333 | 0.9678 | 17672 | 2834 | 8085 |
| 14 | Trincomalee | Sri Lanka | 6.36 | 0.2727 | 1.0 | 50439 | 19548 | 2804 |
| 15 | Gisborne | New Zealand | 6.25 | 0.25 | 1.0 | 32857 | 13657 | 850 |

## 4. Agregado por país

| País | Puertos | I_EL medio | TEU/día total |
|---|---|---|---|
| Japan | 146 | 1.66 | 3002247 |
| United States | 111 | 1.87 | 5902284 |
| China | 102 | 1.66 | 18931585 |
| Indonesia | 86 | 3.06 | 2481069 |
| United Kingdom | 71 | 2.18 | 1310638 |
| Brazil | 58 | 2.55 | 3857687 |
| Norway | 51 | 3.48 | 751976 |
| Australia | 49 | 2.85 | 5296195 |
| Italy | 43 | 2.45 | 1250642 |
| Canada | 43 | 2.7 | 1656019 |
| Russian Federation | 41 | 2.19 | 1744368 |
| Spain | 37 | 2.74 | 1367697 |
| Türkiye | 37 | 2.48 | 1665547 |
| France | 32 | 2.03 | 714997 |
| Sweden | 32 | 2.43 | 363319 |
| India | 29 | 3.33 | 2484855 |
| Philippines | 25 | 3.53 | 542381 |
| Finland | 24 | 2.63 | 245899 |
| Greece | 23 | 2.37 | 420378 |
| Malaysia | 23 | 2.77 | 1239115 |

## 5. Calidad de los datos

| Métrica | Valor |
|---|---|
| Vías recibidas de Overture | 33,671,150 |
| Vías descartadas | 0 (0.0 %) |
| — por geometría inválida | 0 |
| — sin aristas utilizables | 0 |
| Industrias recibidas | 166,000 |
| Teselas DEM inaccesibles | 9 |
| Teselas HRSL inaccesibles | 1 |

## 6. Reparto sectorial medio (UN Comtrade)

| Sector | Cuota media |
|---|---|
| generico_logistica | 53.9 % |
| tecnologia_maquinaria | 12.7 % |
| energia_combustibles | 8.7 % |
| agroalimentario | 8.0 % |
| automocion_transporte | 5.5 % |
| materiales_construccion | 4.7 % |
| quimica_pharma | 4.4 % |
| textil_moda | 2.1 % |

---

Datos por puerto en `resultados.csv` (1824 filas).
