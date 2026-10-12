resource "aws_vpc" "tfm_vpc" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags = { Name = "tfm-vpc-privada" }
}

resource "aws_route_table" "tfm_rt" {
  vpc_id = aws_vpc.tfm_vpc.id
  tags = { Name = "tfm-rt-privada" }
}

resource "aws_vpc_endpoint" "s3_endpoint" {
  vpc_id            = aws_vpc.tfm_vpc.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.tfm_rt.id]
  tags = { Name = "tfm-s3-gateway" }
}

resource "aws_security_group" "batch_etl" {
  name        = "tfm-batch-etl"
  description = "Solo salida para los workers del ETL en Fargate Spot"
  vpc_id      = aws_vpc.tfm_vpc.id

  egress {
    description = "Salida hacia S3, ECR y los datasets publicos de terceros"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "tfm-batch-etl" }
}

resource "google_compute_global_address" "tfm_ip_estatica" {
  name = "tfm-ip-global-estatica"
}
resource "google_project_service" "compute_api" {
  service            = "compute.googleapis.com"
  disable_on_destroy = false
}

resource "google_compute_region_network_endpoint_group" "serverless_neg" {
  name                  = "tfm-serverless-neg"
  network_endpoint_type = "SERVERLESS"
  region                = var.gcp_region
  cloud_run {
    service = google_cloud_run_v2_service.tfm_frontend.name
  }
  depends_on = [google_project_service.compute_api]
}

resource "google_compute_backend_service" "tfm_backend" {
  name                  = "tfm-backend-service"
  protocol              = "HTTPS"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  security_policy       = google_compute_security_policy.cloud_armor_policy.self_link

  backend {
    group = google_compute_region_network_endpoint_group.serverless_neg.id
  }
}

resource "google_compute_managed_ssl_certificate" "tfm_cert" {
  name = "tfm-ssl-cert"
  managed {
    domains = [var.dominio_publico]
  }
}

resource "google_compute_url_map" "tfm_url_map" {
  name            = "tfm-url-map"
  default_service = google_compute_backend_service.tfm_backend.id
}

resource "google_compute_target_https_proxy" "tfm_https_proxy" {
  name             = "tfm-https-proxy"
  url_map          = google_compute_url_map.tfm_url_map.id
  ssl_certificates = [google_compute_managed_ssl_certificate.tfm_cert.id]
}

resource "google_compute_global_forwarding_rule" "tfm_frontend_rule_https" {
  name                  = "tfm-lb-frontend-https"
  target                = google_compute_target_https_proxy.tfm_https_proxy.id
  port_range            = "443"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = google_compute_global_address.tfm_ip_estatica.id
}

resource "google_compute_url_map" "http_redirect" {
  name = "tfm-http-redirect-map"
  default_url_redirect {
    https_redirect         = true
    redirect_response_code = "MOVED_PERMANENTLY_DEFAULT"
    strip_query            = false
  }
}

resource "google_compute_target_http_proxy" "tfm_http_proxy" {
  name    = "tfm-http-proxy-redirect"
  url_map = google_compute_url_map.http_redirect.id
}

resource "google_compute_global_forwarding_rule" "tfm_frontend_rule_http" {
  name                  = "tfm-lb-frontend-http"
  target                = google_compute_target_http_proxy.tfm_http_proxy.id
  port_range            = "80"
  load_balancing_scheme = "EXTERNAL_MANAGED"
  ip_address            = google_compute_global_address.tfm_ip_estatica.id
}

resource "aws_internet_gateway" "tfm_igw" {
  vpc_id = aws_vpc.tfm_vpc.id
  tags   = { Name = "tfm-igw" }
}

resource "aws_subnet" "tfm_subnet_publica" {
  vpc_id                  = aws_vpc.tfm_vpc.id
  cidr_block              = "10.0.1.0/24"
  map_public_ip_on_launch = true
  availability_zone       = "${var.aws_region}a"
  tags                    = { Name = "tfm-subnet-publica" }
}

resource "aws_route" "ruta_internet" {
  route_table_id         = aws_route_table.tfm_rt.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.tfm_igw.id
}

resource "aws_route_table_association" "tfm_subnet_assoc" {
  subnet_id      = aws_subnet.tfm_subnet_publica.id
  route_table_id = aws_route_table.tfm_rt.id
}

output "load_balancer_ip" {
  value       = google_compute_global_address.tfm_ip_estatica.address
  description = "IP pública segura de tu aplicación (Configura tu DNS hacia esta IP)"
}
