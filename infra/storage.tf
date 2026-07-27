# Incident store and report archive.

resource "aws_dynamodb_table" "incidents" {
  name         = "${var.name_prefix}-incidents"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "id"

  attribute {
    name = "id"
    type = "S"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = var.tags
}

resource "aws_s3_bucket" "reports" {
  bucket = "${var.name_prefix}-reports-${data.aws_caller_identity.current.account_id}"
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "reports" {
  bucket                  = aws_s3_bucket.reports.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "reports" {
  bucket = aws_s3_bucket.reports.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# --------------------------------------------------------------------------- #
# Secrets the application needs.
# --------------------------------------------------------------------------- #
resource "random_password" "ingest_id_secret" {
  length  = 48
  special = false
}

resource "random_password" "approval_token" {
  length  = 48
  special = false
}

resource "aws_secretsmanager_secret" "app" {
  name = "${var.name_prefix}/app"
  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "app" {
  secret_id = aws_secretsmanager_secret.app.id
  secret_string = jsonencode({
    # Keys ingested incident ids. Must be stable across replicas and restarts,
    # or dedupe breaks; must be secret, or ids become guessable and the
    # approval endpoint becomes addressable by outsiders.
    OPSCOMMANDER_INGEST_ID_SECRET = random_password.ingest_id_secret.result
    # Shared secret for POST /approve.
    OPSCOMMANDER_APPROVAL_TOKEN = random_password.approval_token.result
  })
}
