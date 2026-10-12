# Análisis de sensibilidad y ablación del I_EL

Puertos analizados: **11**. Perturbación OAT: **±30%**.

## 1. Ablaciones de la fricción multidimensional

Cada columna desactiva un componente del modelo. En `baseline_distancia_pura` el coste de una arista es únicamente su distancia.

| Puerto | `completo` | `sin_topografia` | `sin_friccion_urbana` | `sin_ferrocarril` | `sin_restricciones_viarias` | `sin_jerarquia_viaria` | `sin_disuasion_espacial` | `gravedad_potencia_inversa` | `baseline_distancia_pura` |
|---|---|---|---|---|---|---|---|---|---|
| Tsuruga | 0.35 | 0.34 | 0.33 | 0.35 | 0.35 | 0.35 | 0.31 | 0.33 | 0.31 |
| Sibolga | 1.31 | 1.08 | 0.25 | 1.31 | 1.31 | 1.28 | 1.31 | 1.31 | 0.54 |
| Bluff Harbor | 5.22 | 5.22 | 5.22 | 5.22 | 5.22 | 5.22 | 5.20 | 5.22 | 5.22 |
| Tynemouth | 0.90 | 0.87 | 0.78 | 0.90 | 0.90 | 1.04 | 0.75 | 0.97 | 0.85 |
| Penglai | 1.65 | 1.69 | 1.65 | 1.65 | 1.65 | 0.72 | 1.65 | 1.65 | 0.72 |
| Khorramshahr | 5.14 | 5.14 | 5.14 | 5.14 | 5.14 | 5.14 | 5.14 | 5.14 | 5.14 |
| Uno | 0.06 | 0.06 | 0.04 | 0.06 | 0.06 | 0.21 | 0.05 | 0.07 | 0.26 |
| Fangcheng | 1.42 | 1.42 | 1.42 | 1.42 | 1.42 | 0.68 | 1.41 | 1.46 | 0.67 |
| Misrata | 5.09 | 5.08 | 5.08 | 5.09 | 5.09 | 3.21 | 5.07 | 5.21 | 3.13 |
| Dongjiakou | 1.84 | 1.86 | 1.84 | 1.84 | 1.84 | 0.23 | 1.71 | 1.94 | 0.22 |
| Qingdao Port | 0.69 | 0.68 | 0.69 | 0.69 | 0.69 | 0.80 | 0.69 | 0.69 | 0.84 |

### 1.1 Desglose por componente

| Puerto | Escenario | Saturacion | Vulnerabilidad | Incremento interdiccion | Puertas |
|---|---|---|---|---|---|
| Tsuruga | `completo` | 0.057 | 0.013 | 0.0042 | 6 (respaldo_radio) |
| Tsuruga | `sin_topografia` | 0.057 | 0.012 | 0.0041 | 6 (respaldo_radio) |
| Tsuruga | `sin_friccion_urbana` | 0.057 | 0.010 | 0.0033 | 6 (respaldo_radio) |
| Tsuruga | `sin_ferrocarril` | 0.057 | 0.013 | 0.0042 | 6 (respaldo_radio) |
| Tsuruga | `sin_restricciones_viarias` | 0.057 | 0.013 | 0.0042 | 6 (respaldo_radio) |
| Tsuruga | `sin_jerarquia_viaria` | 0.057 | 0.013 | 0.0043 | 6 (respaldo_radio) |
| Tsuruga | `sin_disuasion_espacial` | 0.057 | 0.005 | 0.0015 | 6 (respaldo_radio) |
| Tsuruga | `gravedad_potencia_inversa` | 0.057 | 0.010 | 0.0034 | 6 (respaldo_radio) |
| Tsuruga | `baseline_distancia_pura` | 0.057 | 0.004 | 0.0015 | 6 (respaldo_radio) |
| Sibolga | `completo` | 0.033 | 0.228 | 0.0861 | 6 (respaldo_radio) |
| Sibolga | `sin_topografia` | 0.033 | 0.183 | 0.0676 | 6 (respaldo_radio) |
| Sibolga | `sin_friccion_urbana` | 0.033 | 0.016 | 0.0054 | 6 (respaldo_radio) |
| Sibolga | `sin_ferrocarril` | 0.033 | 0.228 | 0.0861 | 6 (respaldo_radio) |
| Sibolga | `sin_restricciones_viarias` | 0.033 | 0.228 | 0.0861 | 6 (respaldo_radio) |
| Sibolga | `sin_jerarquia_viaria` | 0.033 | 0.223 | 0.0841 | 6 (respaldo_radio) |
| Sibolga | `sin_disuasion_espacial` | 0.033 | 0.228 | 0.0861 | 6 (respaldo_radio) |
| Sibolga | `gravedad_potencia_inversa` | 0.033 | 0.228 | 0.0861 | 6 (respaldo_radio) |
| Sibolga | `baseline_distancia_pura` | 0.033 | 0.074 | 0.0257 | 6 (respaldo_radio) |
| Bluff Harbor | `completo` | 0.045 | 0.998 | 2.1034 | 6 (respaldo_radio) |
| Bluff Harbor | `sin_topografia` | 0.045 | 0.998 | 2.1150 | 6 (respaldo_radio) |
| Bluff Harbor | `sin_friccion_urbana` | 0.045 | 0.998 | 2.0913 | 6 (respaldo_radio) |
| Bluff Harbor | `sin_ferrocarril` | 0.045 | 0.998 | 2.1034 | 6 (respaldo_radio) |
| Bluff Harbor | `sin_restricciones_viarias` | 0.045 | 0.998 | 2.1034 | 6 (respaldo_radio) |
| Bluff Harbor | `sin_jerarquia_viaria` | 0.045 | 0.999 | 2.4298 | 6 (respaldo_radio) |
| Bluff Harbor | `sin_disuasion_espacial` | 0.045 | 0.996 | 1.8228 | 6 (respaldo_radio) |
| Bluff Harbor | `gravedad_potencia_inversa` | 0.045 | 1.000 | 2.5377 | 6 (respaldo_radio) |
| Bluff Harbor | `baseline_distancia_pura` | 0.045 | 0.999 | 2.4298 | 6 (respaldo_radio) |
| Tynemouth | `completo` | 0.064 | 0.117 | 0.0413 | 6 (respaldo_radio) |
| Tynemouth | `sin_topografia` | 0.064 | 0.110 | 0.0390 | 6 (respaldo_radio) |
| Tynemouth | `sin_friccion_urbana` | 0.064 | 0.093 | 0.0324 | 6 (respaldo_radio) |
| Tynemouth | `sin_ferrocarril` | 0.064 | 0.117 | 0.0413 | 6 (respaldo_radio) |
| Tynemouth | `sin_restricciones_viarias` | 0.064 | 0.117 | 0.0415 | 6 (respaldo_radio) |
| Tynemouth | `sin_jerarquia_viaria` | 0.064 | 0.144 | 0.0517 | 6 (respaldo_radio) |
| Tynemouth | `sin_disuasion_espacial` | 0.064 | 0.087 | 0.0303 | 6 (respaldo_radio) |
| Tynemouth | `gravedad_potencia_inversa` | 0.064 | 0.131 | 0.0466 | 6 (respaldo_radio) |
| Tynemouth | `baseline_distancia_pura` | 0.064 | 0.106 | 0.0372 | 6 (respaldo_radio) |
| Penglai | `completo` | 0.143 | 0.188 | 0.0695 | 6 (respaldo_radio) |
| Penglai | `sin_topografia` | 0.143 | 0.195 | 0.0723 | 6 (respaldo_radio) |
| Penglai | `sin_friccion_urbana` | 0.143 | 0.188 | 0.0695 | 6 (respaldo_radio) |
| Penglai | `sin_ferrocarril` | 0.143 | 0.188 | 0.0695 | 6 (respaldo_radio) |
| Penglai | `sin_restricciones_viarias` | 0.143 | 0.188 | 0.0695 | 6 (respaldo_radio) |
| Penglai | `sin_jerarquia_viaria` | 0.143 | 0.002 | 0.0007 | 6 (respaldo_radio) |
| Penglai | `sin_disuasion_espacial` | 0.143 | 0.188 | 0.0695 | 6 (respaldo_radio) |
| Penglai | `gravedad_potencia_inversa` | 0.143 | 0.188 | 0.0695 | 6 (respaldo_radio) |
| Penglai | `baseline_distancia_pura` | 0.143 | 0.002 | 0.0006 | 6 (respaldo_radio) |
| Khorramshahr | `completo` | 0.028 | 1.000 | 9.0000 | 6 (respaldo_radio) |
| Khorramshahr | `sin_topografia` | 0.028 | 1.000 | 9.0000 | 6 (respaldo_radio) |
| Khorramshahr | `sin_friccion_urbana` | 0.028 | 1.000 | 9.0000 | 6 (respaldo_radio) |
| Khorramshahr | `sin_ferrocarril` | 0.028 | 1.000 | 9.0000 | 6 (respaldo_radio) |
| Khorramshahr | `sin_restricciones_viarias` | 0.028 | 1.000 | 9.0000 | 6 (respaldo_radio) |
| Khorramshahr | `sin_jerarquia_viaria` | 0.028 | 1.000 | 9.0000 | 6 (respaldo_radio) |
| Khorramshahr | `sin_disuasion_espacial` | 0.028 | 1.000 | 9.0000 | 6 (respaldo_radio) |
| Khorramshahr | `gravedad_potencia_inversa` | 0.028 | 1.000 | 9.0000 | 6 (respaldo_radio) |
| Khorramshahr | `baseline_distancia_pura` | 0.028 | 1.000 | 9.0000 | 6 (respaldo_radio) |
| Uno | `completo` | 0.000 | 0.011 | 0.0037 | 6 (respaldo_radio) |
| Uno | `sin_topografia` | 0.000 | 0.011 | 0.0037 | 6 (respaldo_radio) |
| Uno | `sin_friccion_urbana` | 0.000 | 0.007 | 0.0024 | 6 (respaldo_radio) |
| Uno | `sin_ferrocarril` | 0.000 | 0.011 | 0.0037 | 6 (respaldo_radio) |
| Uno | `sin_restricciones_viarias` | 0.000 | 0.011 | 0.0037 | 6 (respaldo_radio) |
| Uno | `sin_jerarquia_viaria` | 0.000 | 0.042 | 0.0144 | 6 (respaldo_radio) |
| Uno | `sin_disuasion_espacial` | 0.000 | 0.010 | 0.0032 | 6 (respaldo_radio) |
| Uno | `gravedad_potencia_inversa` | 0.000 | 0.015 | 0.0050 | 6 (respaldo_radio) |
| Uno | `baseline_distancia_pura` | 0.000 | 0.052 | 0.0179 | 6 (respaldo_radio) |
| Fangcheng | `completo` | 0.086 | 0.198 | 0.0736 | 6 (respaldo_radio) |
| Fangcheng | `sin_topografia` | 0.086 | 0.197 | 0.0733 | 6 (respaldo_radio) |
| Fangcheng | `sin_friccion_urbana` | 0.086 | 0.198 | 0.0736 | 6 (respaldo_radio) |
| Fangcheng | `sin_ferrocarril` | 0.086 | 0.198 | 0.0736 | 6 (respaldo_radio) |
| Fangcheng | `sin_restricciones_viarias` | 0.086 | 0.198 | 0.0736 | 6 (respaldo_radio) |
| Fangcheng | `sin_jerarquia_viaria` | 0.086 | 0.049 | 0.0167 | 6 (respaldo_radio) |
| Fangcheng | `sin_disuasion_espacial` | 0.086 | 0.196 | 0.0727 | 6 (respaldo_radio) |
| Fangcheng | `gravedad_potencia_inversa` | 0.086 | 0.207 | 0.0771 | 6 (respaldo_radio) |
| Fangcheng | `baseline_distancia_pura` | 0.086 | 0.047 | 0.0160 | 6 (respaldo_radio) |
| Misrata | `completo` | 0.062 | 0.956 | 1.0398 | 5 (respaldo_radio) |
| Misrata | `sin_topografia` | 0.062 | 0.953 | 1.0207 | 5 (respaldo_radio) |
| Misrata | `sin_friccion_urbana` | 0.062 | 0.953 | 1.0211 | 5 (respaldo_radio) |
| Misrata | `sin_ferrocarril` | 0.062 | 0.956 | 1.0398 | 5 (respaldo_radio) |
| Misrata | `sin_restricciones_viarias` | 0.062 | 0.956 | 1.0398 | 5 (respaldo_radio) |
| Misrata | `sin_jerarquia_viaria` | 0.062 | 0.581 | 0.2897 | 5 (respaldo_radio) |
| Misrata | `sin_disuasion_espacial` | 0.062 | 0.952 | 1.0136 | 5 (respaldo_radio) |
| Misrata | `gravedad_potencia_inversa` | 0.062 | 0.979 | 1.2880 | 5 (respaldo_radio) |
| Misrata | `baseline_distancia_pura` | 0.062 | 0.564 | 0.2767 | 5 (respaldo_radio) |
| Dongjiakou | `completo` | 0.035 | 0.332 | 0.1344 | 5 (respaldo_radio) |
| Dongjiakou | `sin_topografia` | 0.035 | 0.336 | 0.1363 | 5 (respaldo_radio) |
| Dongjiakou | `sin_friccion_urbana` | 0.035 | 0.332 | 0.1344 | 5 (respaldo_radio) |
| Dongjiakou | `sin_ferrocarril` | 0.035 | 0.332 | 0.1344 | 5 (respaldo_radio) |
| Dongjiakou | `sin_restricciones_viarias` | 0.035 | 0.332 | 0.1344 | 5 (respaldo_radio) |
| Dongjiakou | `sin_jerarquia_viaria` | 0.035 | 0.010 | 0.0033 | 5 (respaldo_radio) |
| Dongjiakou | `sin_disuasion_espacial` | 0.035 | 0.306 | 0.1216 | 5 (respaldo_radio) |
| Dongjiakou | `gravedad_potencia_inversa` | 0.035 | 0.353 | 0.1454 | 5 (respaldo_radio) |
| Dongjiakou | `baseline_distancia_pura` | 0.035 | 0.008 | 0.0028 | 5 (respaldo_radio) |
| Qingdao Port | `completo` | 0.120 | 0.017 | 0.0058 | 6 (respaldo_radio) |
| Qingdao Port | `sin_topografia` | 0.120 | 0.016 | 0.0053 | 6 (respaldo_radio) |
| Qingdao Port | `sin_friccion_urbana` | 0.120 | 0.017 | 0.0058 | 6 (respaldo_radio) |
| Qingdao Port | `sin_ferrocarril` | 0.120 | 0.017 | 0.0058 | 6 (respaldo_radio) |
| Qingdao Port | `sin_restricciones_viarias` | 0.120 | 0.017 | 0.0058 | 6 (respaldo_radio) |
| Qingdao Port | `sin_jerarquia_viaria` | 0.120 | 0.039 | 0.0132 | 6 (respaldo_radio) |
| Qingdao Port | `sin_disuasion_espacial` | 0.120 | 0.018 | 0.0060 | 6 (respaldo_radio) |
| Qingdao Port | `gravedad_potencia_inversa` | 0.120 | 0.017 | 0.0057 | 6 (respaldo_radio) |
| Qingdao Port | `baseline_distancia_pura` | 0.120 | 0.046 | 0.0159 | 6 (respaldo_radio) |

| Puerto | Δ I_EL completo vs. distancia pura | Δ relativa |
|---|---|---|
| Tsuruga | +0.04 | +12.9% |
| Sibolga | +0.77 | +142.6% |
| Bluff Harbor | +0.00 | +0.0% |
| Tynemouth | +0.05 | +5.9% |
| Penglai | +0.93 | +129.2% |
| Khorramshahr | +0.00 | +0.0% |
| Uno | -0.20 | -76.9% |
| Fangcheng | +0.75 | +111.9% |
| Misrata | +1.96 | +62.6% |
| Dongjiakou | +1.62 | +736.4% |
| Qingdao Port | -0.15 | -17.9% |

## 2. Sensibilidad de un factor cada vez (±30%)

La elasticidad es la variación relativa del I_EL por unidad de variación relativa del parámetro. Un valor próximo a 0 indica que el resultado es poco sensible a ese parámetro.

| Parámetro | Valor base | Rango ensayado | Elasticidad media | |Elasticidad| |
|---|---|---|---|---|
| `percentil_capacidad` | 0.95 | 0.9 → 0.99 | -9.6554 | 9.6554 |
| `peso_cuello_botella` | 5.0 | 3.5 → 6.5 | +0.6956 | 0.6956 |
| `lambda_vulnerabilidad` | 3.0 | 2.0999999999999996 → 3.9000000000000004 | +0.4105 | 0.4105 |
| `peso_saturacion` | 5.0 | 3.5 → 6.5 | +0.2828 | 0.2828 |
| `dias_ventana_carga` | 365 | 255.49999999999997 → 474.5 | +0.2667 | 0.2667 |
| `radio_buffer_puertas_km` | 3.0 | 2.0999999999999996 → 3.9000000000000004 | +0.2284 | 0.2284 |
| `friccion_secundaria` | 2.5 | 1.75 → 3.25 | +0.1124 | 0.1124 |
| `divisor_poblacion` | 10000.0 | 7000.0 → 13000.0 | -0.1077 | 0.1077 |
| `friccion_autopista` | 0.4 | 0.27999999999999997 → 0.52 | -0.0967 | 0.0967 |
| `beta_disuasion` | 0.03 | 0.020999999999999998 → 0.039 | +0.0481 | 0.0481 |
| `factor_pendiente_camion` | 10.0 | 7.0 → 13.0 | +0.0410 | 0.0410 |
| `friccion_primaria` | 0.7 | 0.48999999999999994 → 0.9099999999999999 | +0.0379 | 0.0379 |
| `pendiente_maxima_camion` | 0.15 | 0.105 → 0.195 | -0.0243 | 0.0243 |
| `masa_puerto_seco` | 50000.0 | 35000.0 → 65000.0 | -0.0043 | 0.0043 |
| `friccion_ultima_milla` | 2.5 | 1.75 → 3.25 | -0.0016 | 0.0016 |
| `teus_por_buque_roro` | 2.5 | 1.75 → 3.25 | +0.0000 | 0.0000 |
| `teus_por_buque_container` | 2.0 | 1.4 → 2.6 | +0.0000 | 0.0000 |
| `penalizacion_tonelaje_limitado` | 50.0 | 35.0 → 65.0 | +0.0000 | 0.0000 |
| `penalizacion_sin_pavimentar` | 3.5 | 2.4499999999999997 → 4.55 | +0.0000 | 0.0000 |
| `friccion_rail` | 0.1 | 0.06999999999999999 → 0.13 | +0.0000 | 0.0000 |
| `factor_pendiente_tren` | 50.0 | 35.0 → 65.0 | +0.0000 | 0.0000 |
| `cuota_tren` | 0.2 | 0.13999999999999999 → 0.26 | +0.0000 | 0.0000 |
| `capacidad_fallback_por_puerta` | 8000.0 | 5600.0 → 10400.0 | +0.0000 | 0.0000 |

> Una elasticidad nula no implica necesariamente robustez: también puede indicar que el término no interviene en el resultado con la configuración por defecto.
