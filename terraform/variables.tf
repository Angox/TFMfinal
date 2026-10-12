variable "aws_region" {
  description = "Región principal de AWS (se define en config.env, raíz del repo)"
  type        = string
}

variable "gcp_project_id" {
  description = "El ID de tu proyecto en Google Cloud"
  type        = string
  default     = "proyecto-tfm-489108"
}

variable "gcp_region" {
  description = "Región principal para los servicios de GCP"
  type        = string
  default     = "europe-southwest1"
}

variable "email_alertas" {
  description = "Correo electrónico para recibir avisos de facturación de AWS"
  type        = string
  default     = "alertas@example.com"
}

variable "gemini_api_key" {
  description = "API Key para Google Gemini"
  type        = string
  sensitive   = true
}

variable "aws_access_key" {
  description = "AWS Access Key para que Cloud Run acceda a S3"
  type        = string
  sensitive   = true
}

variable "aws_secret_key" {
  description = "AWS Secret Key para que Cloud Run acceda a S3"
  type        = string
  sensitive   = true
}

variable "comtrade_api_key" {
  description = "API Key para acceder a UN Comtrade v2"
  type        = string
  sensitive   = true
}

variable "docker_image" {
  description = "Ruta de la imagen Docker en Artifact Registry para Cloud Run"
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "dominio_publico" {
  description = "Dominio por el que se sirve la aplicación a través del balanceador"
  type        = string
  default     = "hinderland.duckdns.org"
}

variable "cloud_run_ingress" {
  description = "Política de entrada de Cloud Run (ALL abre la URL run.app y anula Cloud Armor)"
  type        = string
  default     = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"

  validation {
    condition = contains([
      "INGRESS_TRAFFIC_ALL",
      "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER",
      "INGRESS_TRAFFIC_INTERNAL_ONLY",
    ], var.cloud_run_ingress)
    error_message = "Valor no admitido para cloud_run_ingress."
  }
}

variable "origenes_cors" {
  description = "Orígenes adicionales permitidos en el CORS del bucket de datos curados"
  type        = list(string)
  default     = []
}

variable "bucket_datos_nombre" {
  description = "Nombre del bucket S3 de datos curados (se define en config.env)"
  type        = string
}
