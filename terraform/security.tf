resource "aws_kms_key" "s3_key" {
  description             = "Clave KMS para encriptar los buckets de datos del TFM"
  deletion_window_in_days = 7
  enable_key_rotation     = true
}

resource "aws_kms_alias" "s3_key_alias" {
  name          = "alias/tfm-s3-key"
  target_key_id = aws_kms_key.s3_key.key_id
}

resource "google_compute_security_policy" "cloud_armor_policy" {
  name        = "tfm-seguridad-global"
  description = "Bloquea tráfico malicioso y ataques web"

  advanced_options_config {
    json_parsing = "STANDARD"
  }

  rule {
    action   = "allow"
    priority = "2147483647"
    match {
      versioned_expr = "SRC_IPS_V1"
      config {
        src_ip_ranges = ["*"]
      }
    }
    description = "Permitir todo por defecto"
  }

  rule {
    action   = "allow"
    priority = "500"
    match {
      expr {
        expression = "request.path.matches('^/api/chat/.*')"
      }
    }
    description = "Exclusión (Bypass) de filtros WAF para el chatbot de IA"
  }

  rule {
    action   = "deny(403)"
    priority = "1000"
    match {
      expr {
        expression = "evaluatePreconfiguredExpr('sqli-v33-stable') || evaluatePreconfiguredExpr('xss-v33-stable')"
      }
    }
    description = "Bloquear ataques SQLi y XSS"
  }
}

resource "google_project_service" "secretmanager_api" {
  service            = "secretmanager.googleapis.com"
  disable_on_destroy = false
}

resource "google_secret_manager_secret" "gemini_key" {
  secret_id = "tfm-gemini-api-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.secretmanager_api]
}

resource "google_secret_manager_secret_version" "gemini_key_version" {
  secret      = google_secret_manager_secret.gemini_key.id
  secret_data = var.gemini_api_key
}

resource "google_secret_manager_secret" "aws_access" {
  secret_id = "tfm-aws-access-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.secretmanager_api]
}

resource "google_secret_manager_secret_version" "aws_access_version" {
  secret      = google_secret_manager_secret.aws_access.id
  secret_data = var.aws_access_key
}

resource "google_secret_manager_secret" "aws_secret" {
  secret_id = "tfm-aws-secret-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.secretmanager_api]
}

resource "google_secret_manager_secret_version" "aws_secret_version" {
  secret      = google_secret_manager_secret.aws_secret.id
  secret_data = var.aws_secret_key
}

data "google_project" "project" {}

resource "google_secret_manager_secret_iam_member" "cr_secrets_access" {
  for_each = {
    "gemini" = google_secret_manager_secret.gemini_key.id,
    "aws_a"  = google_secret_manager_secret.aws_access.id,
    "aws_s"  = google_secret_manager_secret.aws_secret.id
  }

  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${data.google_project.project.number}-compute@developer.gserviceaccount.com"
}
