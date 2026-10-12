FROM python:3.10.21-slim

WORKDIR /app

RUN pip install --upgrade pip

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--ws-ping-interval", "30", "--ws-ping-timeout", "300", "--ws-max-queue", "256"]
