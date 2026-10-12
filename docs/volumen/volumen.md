# Volumen de datos procesado

Release de Overture Maps: **2026-08-19.0**  
Medición realizada el 2026-08-28.

> Overture conserva cada release unos 60 días, por lo que el ETL usa la versión más reciente disponible en el momento de la ejecución.

## 1. Universo de datos consultado

| Tema Overture | Tamaño | Ficheros Parquet |
|---|---|---|
| `transportation/segment` | 71.82 GB | 128 |
| `places/place` | 10.48 GB | 16 |
| `buildings/building` | 276.84 GB | 512 |
| `base/land_use` | 18.69 GB | 32 |
| **Total** | **377.83 GB** | **688** |

## 2. Volumen realmente leído por puerto

| Puerto | Descargado | Peticiones HTTP | Tiempo | Vías | Industrias |
|---|---|---|---|---|---|
| San Nicolas | 933.31 MB | 1531 | 241.39 s | 7907 | 31 |
| Tocopilla | 12.87 MB | 32 | 11.41 s | 474 | 0 |
| Port Vale Knights | 8.9 MB | 46 | 15.56 s | 415 | 0 |
| Roseau | 24.78 MB | 81 | 21.19 s | 883 | 3 |
| Saint George's | 15.51 MB | 56 | 19.6 s | 1108 | 4 |
| Pomalaa | 42.17 MB | 97 | 22.77 s | 1491 | 2 |
| Pemba | 14.87 MB | 44 | 20.19 s | 732 | 0 |
| Esmeraldas | 53.9 MB | 124 | 24.73 s | 1815 | 1 |
| Tg Mani | 37.65 MB | 94 | 22.96 s | 1698 | 2 |
| Limboh | 49.92 MB | 167 | 25.32 s | 2823 | 4 |

## 3. Eficiencia del *predicate pushdown*

| Métrica | Valor |
|---|---|
| Universo de datos | 377.83 GB |
| Media leída por puerto | 119.39 MB |
| Fracción leída | 0.0316 % |
| Factor de reducción | **3,165×** |

Por puerto se descarga aproximadamente 1 de cada 3,165 bytes del universo de datos. DuckDB filtra por *bounding box* usando las estadísticas de los grupos de filas del Parquet y solo descarga los grupos que intersectan con el área del puerto.
