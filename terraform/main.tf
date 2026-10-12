resource "aws_s3_bucket" "datos_curados" {
  bucket        = var.bucket_datos_nombre
  force_destroy = true
}

resource "aws_s3_object" "carpeta_ais" {
  bucket       = aws_s3_bucket.datos_curados.id
  key          = "ais_historico/"
  content_type = "application/x-directory"
}

resource "aws_s3_object" "carpeta_resultados_web" {
  bucket       = aws_s3_bucket.datos_curados.id
  key          = "resultados_web/"
  content_type = "application/x-directory"
}

resource "aws_s3_object" "carpeta_comtrade" {
  bucket       = aws_s3_bucket.datos_curados.id
  key          = "fuentes_externas/comtrade/"
  content_type = "application/x-directory"
}

resource "aws_s3_object" "carpeta_caches_workers" {
  bucket       = aws_s3_bucket.datos_curados.id
  key          = "resultados_web/api/caches/"
  content_type = "application/x-directory"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "datos_curados_sse" {
  bucket = aws_s3_bucket.datos_curados.id
  rule {
    apply_server_side_encryption_by_default {
      kms_master_key_id = aws_kms_key.s3_key.arn
      sse_algorithm     = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_cors_configuration" "datos_curados_cors" {
  bucket = aws_s3_bucket.datos_curados.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = concat(
      ["https://${var.dominio_publico}"],
      var.origenes_cors,
      [google_cloud_run_v2_service.tfm_frontend.uri],
    )
    expose_headers  = ["ETag", "Accept-Ranges", "Content-Range", "Content-Length"]
    max_age_seconds = 3600
  }
}

resource "google_project_service" "cloud_run_api" {
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "cloud_build_api" {
  service            = "cloudbuild.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "artifact_registry_api" {
  service            = "artifactregistry.googleapis.com"
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "tfm_repo" {
  location      = var.gcp_region
  repository_id = "tfm-repo"
  description   = "Repositorio Docker para la API y Frontend del TFM"
  format        = "DOCKER"

  depends_on = [google_project_service.artifact_registry_api]
}

resource "google_cloud_run_v2_service" "tfm_frontend" {
  name     = "tfm-dashboard-hinterland"
  location = var.gcp_region
  ingress = var.cloud_run_ingress

  template {
    session_affinity = true

    timeout = "3600s"

    containers {
      image = var.docker_image
      ports { container_port = 8080 }
      env {
        name = "GEMINI_API_KEY"
        value_source {
          secret_key_ref {
            secret = google_secret_manager_secret.gemini_key.name
            version = "latest"
          }
        }
      }
      env {
        name  = "S3_BUCKET_NAME"
        value = aws_s3_bucket.datos_curados.bucket
      }
      env {
        name = "AWS_ACCESS_KEY_ID"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.aws_access.name
            version = "latest"
          }
        }
      }
      env {
        name = "AWS_SECRET_ACCESS_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.aws_secret.name
            version = "latest"
          }
        }
      }
      resources {
        limits = { cpu = "4000m", memory = "8192Mi" }
      }
    }
  }

  depends_on = [
    google_project_service.cloud_run_api,
    google_project_service.cloud_build_api,
    google_secret_manager_secret_version.gemini_key_version,
    google_secret_manager_secret_version.aws_access_version,
    google_secret_manager_secret_version.aws_secret_version,
    google_secret_manager_secret_iam_member.cr_secrets_access
  ]
}

resource "google_cloud_run_service_iam_member" "public_access" {
  location = google_cloud_run_v2_service.tfm_frontend.location
  service  = google_cloud_run_v2_service.tfm_frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

output "web_url" {
  value = google_cloud_run_v2_service.tfm_frontend.uri
}

resource "aws_s3_object" "carpeta_fmi" {
  bucket       = aws_s3_bucket.datos_curados.id
  key          = "fuentes_externas/fmi_ports/"
  content_type = "application/x-directory"
}

resource "aws_ecr_repository" "etl_repo" {
  name                 = "tfm-etl-grafos"
  image_tag_mutability = "MUTABLE"
  force_delete         = true
}

resource "aws_iam_role" "ecs_task_execution_role" {
  name = "tfm_ecs_task_execution_role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "ecs_s3_restricted_access" {
  name   = "tfm_ecs_s3_least_privilege"
  role   = aws_iam_role.ecs_task_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:ListBucket"
        ]
        Resource = aws_s3_bucket.datos_curados.arn
      },
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject"
        ]
        Resource = "${aws_s3_bucket.datos_curados.arn}/*"
      }
    ]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution_policy" {
  role       = aws_iam_role.ecs_task_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "aws_batch_service_role" {
  name = "tfm_batch_service_role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "batch.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "batch_service_role_policy" {
  role       = aws_iam_role.aws_batch_service_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSBatchServiceRole"
}

resource "aws_batch_compute_environment" "fargate_spot_env" {
  compute_environment_name = "tfm-fargate-batch-spot"

  compute_resources {
    type               = "FARGATE_SPOT"
    max_vcpus          = 256
    subnets            = [aws_subnet.tfm_subnet_publica.id]
    security_group_ids = [aws_security_group.batch_etl.id]
  }

  type         = "MANAGED"
  state        = "ENABLED"
  service_role = aws_iam_role.aws_batch_service_role.arn

  depends_on = [aws_iam_role_policy_attachment.batch_service_role_policy]
}

resource "aws_batch_job_queue" "etl_queue" {
  name                 = "tfm-queue"
  state                = "ENABLED"
  priority             = 1
  compute_environment_order {
    order               = 1
    compute_environment = aws_batch_compute_environment.fargate_spot_env.arn
  }
}

resource "aws_batch_job_definition" "etl_job" {
  name = "tfm-etl-job"
  type = "container"
  platform_capabilities = ["FARGATE"]

  retry_strategy {
    attempts = 3
  }

  container_properties = jsonencode({
    image = "${aws_ecr_repository.etl_repo.repository_url}:latest"

    resourceRequirements = [
      { type = "VCPU", value = "1" },
      { type = "MEMORY", value = "4096" }
    ]

    executionRoleArn = aws_iam_role.ecs_task_execution_role.arn
    jobRoleArn       = aws_iam_role.ecs_task_execution_role.arn

    networkConfiguration = {
      assignPublicIp = "ENABLED"
    }

    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.etl_logs.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "batch"
      }
    }
  })
}

resource "aws_iam_role_policy" "ecs_kms_access" {
  name   = "tfm_ecs_kms_access_policy"
  role   = aws_iam_role.ecs_task_execution_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey"
        ]
        Resource = aws_kms_key.s3_key.arn
      }
    ]
  })
}
resource "aws_cloudwatch_log_group" "etl_logs" {
  name              = "/ecs/tfm-etl"
  retention_in_days = 7
}

resource "aws_s3_bucket_public_access_block" "datos_curados_public_access" {
  bucket = aws_s3_bucket.datos_curados.id

  block_public_acls       = true
  ignore_public_acls      = true
  block_public_policy     = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_policy" "mapa_global_publico" {
  bucket = aws_s3_bucket.datos_curados.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Principal = "*"
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.datos_curados.arn}/resultados_web/mapa_global/*"
      }
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.datos_curados_public_access]
}
