# Alarm ingestion path: CloudWatch Alarm -> SNS -> HTTPS -> OpsCommander.
#
# This file provisions the ingestion plumbing only. It assumes you already
# have somewhere to run the API and a DNS name pointing at it; see
# `ecs.tf` for a reference deployment.

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.5"
    }
  }
}

provider "aws" {
  region  = var.aws_region
  profile = var.aws_profile
}

# --------------------------------------------------------------------------- #
# Ingest topic
#
# Deliberately separate from the topic the reporting agent publishes to. If
# they were the same, every incident report would notify itself back into the
# webhook. The application refuses that configuration at runtime, but the two
# topics should never be the same object in the first place.
# --------------------------------------------------------------------------- #
resource "aws_sns_topic" "alarms" {
  name = "${var.name_prefix}-alarms"

  # SignatureVersion 2 uses SHA-256 rather than SHA-1.
  signature_version = 2

  tags = var.tags
}

resource "aws_sns_topic" "notifications" {
  name = "${var.name_prefix}-notifications"
  tags = var.tags
}

data "aws_iam_policy_document" "alarms_publish" {
  statement {
    sid    = "AllowCloudWatchAlarmsToPublish"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["cloudwatch.amazonaws.com"]
    }
    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.alarms.arn]
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

data "aws_caller_identity" "current" {}

resource "aws_sns_topic_policy" "alarms" {
  arn    = aws_sns_topic.alarms.arn
  policy = data.aws_iam_policy_document.alarms_publish.json
}

# --------------------------------------------------------------------------- #
# Delivery to the webhook
#
# Deliveries that exhaust the retry policy land in the DLQ. Without it a
# rejected or failed delivery leaves no trace at all, and the DLQ is the only
# forensic record of alarms that never became incidents.
# --------------------------------------------------------------------------- #
resource "aws_sqs_queue" "ingest_dlq" {
  name                      = "${var.name_prefix}-ingest-dlq"
  message_retention_seconds = 1209600 # 14 days
  tags                      = var.tags
}

resource "aws_sqs_queue_policy" "ingest_dlq" {
  queue_url = aws_sqs_queue.ingest_dlq.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.ingest_dlq.arn
      Condition = { ArnEquals = { "aws:SourceArn" = aws_sns_topic.alarms.arn } }
    }]
  })
}

resource "aws_sns_topic_subscription" "webhook" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "https"
  # API Gateway's own hostname carries a publicly trusted certificate, which is
  # what SNS requires; a self-signed endpoint never gets past confirmation.
  # trimsuffix because the $default stage's invoke_url ends in "/", and a
  # "//webhook/sns" path matches no route.
  endpoint = "${trimsuffix(aws_apigatewayv2_stage.api.invoke_url, "/")}/webhook/sns"

  # The application confirms the subscription itself via the SNS API when the
  # topic is in its allowlist, so Terraform must not wait on it here.
  endpoint_auto_confirms          = true
  confirmation_timeout_in_minutes = 5

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ingest_dlq.arn
  })

  delivery_policy = jsonencode({
    healthyRetryPolicy = {
      numRetries         = 10
      minDelayTarget     = 5
      maxDelayTarget     = 300
      numMinDelayRetries = 3
      numMaxDelayRetries = 3
      backoffFunction    = "exponential"
    }
  })
}

# --------------------------------------------------------------------------- #
# Example alarms
#
# The Severity tag is what the ingestion path reads to set incident severity;
# without it severity is inferred from the alarm text.
# --------------------------------------------------------------------------- #
resource "aws_cloudwatch_metric_alarm" "example_lambda_errors" {
  alarm_name          = "${var.name_prefix}-orders-api-errors"
  alarm_description   = "Elevated error rate on the orders API"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = "orders-api" }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 10
  comparison_operator = "GreaterThanThreshold"

  alarm_actions = [aws_sns_topic.alarms.arn]

  tags = merge(var.tags, { Severity = "High" })
}
