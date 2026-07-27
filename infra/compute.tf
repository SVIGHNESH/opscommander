# Compute: API Gateway -> api Lambda -> SQS -> worker Lambda.
#
# The split into two functions is not stylistic. Lambda freezes the execution
# environment as soon as a handler returns, so the pipeline cannot run in the
# background of the request that answers SNS - it would be suspended mid-call
# and, as often as not, never resumed. SNS also expects an answer within about
# 15 seconds, while a pipeline run calls Bedrock and reads logs. So the API
# function does the authenticated, fast part (verify, persist, enqueue) and the
# worker function exists solely to run the seven agents.

locals {
  api_env = {
    OPSCOMMANDER_MODE                  = "aws"
    OPSCOMMANDER_BEDROCK_MODEL         = var.bedrock_model_id
    OPSCOMMANDER_DDB_TABLE             = aws_dynamodb_table.incidents.name
    OPSCOMMANDER_S3_BUCKET             = aws_s3_bucket.reports.bucket
    OPSCOMMANDER_SNS_TOPIC_ARN         = aws_sns_topic.notifications.arn
    OPSCOMMANDER_SNS_ALLOWED_TOPICS    = aws_sns_topic.alarms.arn
    OPSCOMMANDER_INGEST_QUEUE_URL      = aws_sqs_queue.incidents.id
    # The default resolves to /var/data on Lambda, which is read-only; /tmp is
    # the only writable path. Reports are staged here before the S3 upload.
    OPSCOMMANDER_DATA_DIR              = "/tmp/opscommander-data"
    OPSCOMMANDER_INGEST_ID_SECRET      = random_password.ingest_id_secret.result
    OPSCOMMANDER_APPROVAL_TOKEN        = random_password.approval_token.result
    OPSCOMMANDER_AUTO_APPROVE_SEVERITY = var.auto_approve_severity
    # tostring() because this is the only numeric input in an otherwise
    # all-string map, and Lambda environment values must be strings.
    OPSCOMMANDER_INGEST_SUPPRESS_SECONDS = tostring(var.ingest_suppress_seconds)
    OPSCOMMANDER_LOG_LEVEL               = var.log_level
  }
}

# --------------------------------------------------------------------------- #
# Incident queue
#
# The handoff between "the alarm was accepted" and "the pipeline ran". Its
# depth is also the buffer during an alarm storm: work waits here instead of
# fanning out into unbounded concurrent Bedrock calls.
# --------------------------------------------------------------------------- #
resource "aws_sqs_queue" "incidents_dlq" {
  name                      = "${var.name_prefix}-incidents-dlq"
  message_retention_seconds = 1209600 # 14 days
  tags                      = var.tags
}

resource "aws_sqs_queue" "incidents" {
  name = "${var.name_prefix}-incidents"

  # Must be at least the worker's timeout, or SQS will hand the same incident
  # to a second worker while the first is still running it.
  visibility_timeout_seconds = var.worker_timeout_seconds

  message_retention_seconds = 345600 # 4 days

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.incidents_dlq.arn
    # The worker is idempotent on anything past QUEUED, so a couple of retries
    # cost nothing; beyond that the failure is not transient.
    maxReceiveCount = 3
  })

  tags = var.tags
}

# --------------------------------------------------------------------------- #
# Functions
# --------------------------------------------------------------------------- #
resource "aws_lambda_function" "api" {
  function_name = "${var.name_prefix}-api"
  role          = aws_iam_role.task.arn
  handler       = "opscommander.lambda_handlers.api_handler"
  runtime       = var.lambda_runtime
  architectures = [var.lambda_architecture]

  filename         = var.lambda_package
  source_code_hash = filebase64sha256(var.lambda_package)

  # Short on purpose: everything this function does is bounded, and SNS gives
  # up on the delivery long before a larger timeout would matter.
  timeout     = 20
  memory_size = var.api_memory_mb

  environment {
    variables = local.api_env
  }

  tags = var.tags
}

resource "aws_lambda_function" "worker" {
  function_name = "${var.name_prefix}-worker"
  role          = aws_iam_role.task.arn
  handler       = "opscommander.lambda_handlers.worker_handler"
  runtime       = var.lambda_runtime
  architectures = [var.lambda_architecture]

  filename         = var.lambda_package
  source_code_hash = filebase64sha256(var.lambda_package)

  timeout     = var.worker_timeout_seconds
  memory_size = var.worker_memory_mb

  # Concurrency is capped by the event source mapping's maximum_concurrency
  # rather than reserved concurrency: SQS is this function's only trigger, so
  # the cap is equivalent, and reserving is impossible on accounts still at
  # the default 10-concurrency quota (10 must stay unreserved).

  environment {
    variables = local.api_env
  }

  tags = var.tags
}

resource "aws_lambda_event_source_mapping" "worker" {
  event_source_arn = aws_sqs_queue.incidents.arn
  function_name    = aws_lambda_function.worker.arn

  # One incident per invocation: batching would tie unrelated incidents to a
  # single timeout, and a slow Bedrock call on one would drag the rest down.
  batch_size = 1

  # The worker returns batchItemFailures so a failed incident is retried on its
  # own rather than taking its batch with it.
  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = max(2, var.worker_max_concurrency)
  }
}

# Log groups are declared rather than left to Lambda's implicit creation, so
# retention is bounded instead of "never expire".
resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${aws_lambda_function.api.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/aws/lambda/${aws_lambda_function.worker.function_name}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

# --------------------------------------------------------------------------- #
# Public edge
#
# API Gateway supplies a publicly trusted TLS certificate on its own hostname,
# which is what SNS requires to confirm an HTTPS subscription. That is the
# reason this is here rather than an ALB: no domain and no ACM certificate are
# needed to get a working endpoint.
#
# Only POST /webhook/sns is routed. There is deliberately no $default route:
# GET /report/{id} returns root causes and sampled log lines, and POST /approve
# executes infrastructure changes, so neither should be reachable from the
# internet. Reach those by running the API or dashboard against the same table
# from inside your network.
# --------------------------------------------------------------------------- #
resource "aws_apigatewayv2_api" "api" {
  name          = "${var.name_prefix}-api"
  protocol_type = "HTTP"
  tags          = var.tags
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

resource "aws_apigatewayv2_route" "webhook" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "POST /webhook/sns"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "api" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn
    format = jsonencode({
      requestId = "$context.requestId"
      route     = "$context.routeKey"
      status    = "$context.status"
      error     = "$context.integrationErrorMessage"
      sourceIp  = "$context.identity.sourceIp"
      time      = "$context.requestTime"
    })
  }

  default_route_settings {
    # A cap on how fast anyone can make us do work. The webhook is public, and
    # every accepted message costs a DynamoDB write and an SQS send.
    throttling_burst_limit = var.api_throttle_burst
    throttling_rate_limit  = var.api_throttle_rate
  }

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "access" {
  name              = "/aws/apigateway/${var.name_prefix}"
  retention_in_days = var.log_retention_days
  tags              = var.tags
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  # Scoped to this API's webhook route rather than the whole account.
  source_arn = "${aws_apigatewayv2_api.api.execution_arn}/*/POST/webhook/sns"
}
