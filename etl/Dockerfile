FROM python:3.10.21-slim

WORKDIR /etl

RUN apt-get update && apt-get install -y \
    gcc g++ libgdal-dev curl unzip \
    make sqlite3 libsqlite3-dev zlib1g-dev git && \
    curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o "awscliv2.zip" && \
    unzip awscliv2.zip && \
    ./aws/install && \
    rm -rf awscliv2.zip aws && \
    git clone https://github.com/felt/tippecanoe.git && \
    cd tippecanoe && make -j && make install && \
    cd .. && rm -rf tippecanoe && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY extraer_fmi_completo.py .
COPY config_aws.py .
COPY calculos.py .
COPY portwatch.py .
COPY grafos.py .


CMD ["sh", "-c", "aws s3 cp s3://${S3_BUCKET_NAME}/scripts/etl_procesamiento.py . && python etl_procesamiento.py"]
