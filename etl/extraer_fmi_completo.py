import requests
import pandas as pd
import boto3
from io import StringIO
import os

from config_aws import S3_BUCKET, AWS_REGION
S3_KEY = "fuentes_externas/fmi_ports/puertos.json"

def extraer_todo_el_fmi():
    print("Iniciando descarga completa de PortWatch (FMI)...")
    all_features = []
    offset = 0
    batch_size = 1000
    base_url = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services/PortWatch_ports_database/FeatureServer/0/query"

    while True:
        params = {
            "where": "1=1",
            "outFields": "*",
            "f": "json",
            "resultOffset": offset,
            "resultRecordCount": batch_size,
            "outSR": "4326",
            "returnGeometry": "true"
        }

        response = requests.get(base_url, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()

        features = data.get('features', [])
        if not features: break

        for f in features:
            props = f.get('attributes', {})
            props['lon'] = f.get('geometry', {}).get('x')
            props['lat'] = f.get('geometry', {}).get('y')
            all_features.append(props)

        if not data.get('exceededTransferLimit', False): break
        offset += batch_size

    df = pd.DataFrame(all_features)

    columnas_clave = [
        'portname', 'vessel_count_total', 'lon', 'lat',
        'country', 'share_country_maritime_import', 'share_country_maritime_export',
        'vessel_count_container', 'vessel_count_dry_bulk',
        'vessel_count_general_cargo', 'vessel_count_RoRo', 'vessel_count_tanker',
        'industry_top1', 'industry_top2', 'industry_top3'
    ]
    for col in columnas_clave:
        if col in df.columns:
            df[col] = df[col].astype(str)

    json_buffer = StringIO()
    df.to_json(json_buffer, orient='records', lines=True)

    print(f"Subiendo {len(df)} registros a s3://{S3_BUCKET}/{S3_KEY}")
    s3 = boto3.client('s3', region_name=AWS_REGION)
    s3.put_object(
        Bucket=S3_BUCKET, Key=S3_KEY,
        Body=json_buffer.getvalue(), ContentType='application/json'
    )
    print("¡Base de datos del FMI actualizada en S3 con Lat/Lon exactas!")

if __name__ == "__main__":
    extraer_todo_el_fmi()
