# Task role for the OpsCommander service.
#
# Scoped to the specific resources the seven agents touch. The remediation
# permissions are the ones worth reviewing: they are what an approved action
# actually executes, so this policy is the outer bound on the blast radius of
# a mistaken approval.

data "aws_iam_policy_document" "task_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "task" {
  name               = "${var.name_prefix}-task"
  assume_role_policy = data.aws_iam_policy_document.task_assume.json
  tags               = var.tags
}

locals {
  # An inference profile id carries a routing prefix the foundation-model ARN
  # does not: "global.anthropic.claude-haiku-4-5-..." names the profile, while
  # the model underneath it is "anthropic.claude-haiku-4-5-...".
  bedrock_foundation_model_id  = replace(var.bedrock_model_id, "/^(global|apac|us|eu)\\./", "")
  bedrock_is_inference_profile = local.bedrock_foundation_model_id != var.bedrock_model_id
}

data "aws_iam_policy_document" "task" {
  # Recommendation agent.
  #
  # Invoking through an inference profile is authorised against two resources,
  # not one: the profile itself, and the foundation model in every region the
  # profile may route to. Granting only the profile fails closed at call time,
  # and because the Recommendation Agent treats a Bedrock error as a soft
  # failure, the symptom is rule-based recommendations rather than an alarm.
  statement {
    sid     = "InvokeBedrock"
    effect  = "Allow"
    actions = ["bedrock:InvokeModel"]
    resources = compact([
      local.bedrock_is_inference_profile
      ? "arn:aws:bedrock:${var.aws_region}:${data.aws_caller_identity.current.account_id}:inference-profile/${var.bedrock_model_id}"
      : null,
      # Region-less form is what a "global." profile presents; the wildcard
      # covers the regional copies it fans out to.
      "arn:aws:bedrock:::foundation-model/${local.bedrock_foundation_model_id}",
      "arn:aws:bedrock:*::foundation-model/${local.bedrock_foundation_model_id}",
    ])
  }

  # Log analysis agent.
  statement {
    sid    = "ReadLogs"
    effect = "Allow"
    actions = [
      "logs:DescribeLogStreams",
      "logs:GetLogEvents",
      "logs:FilterLogEvents",
    ]
    resources = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:*"]
  }

  # Detection agent metrics, plus the alarm tags that carry severity.
  statement {
    sid    = "ReadCloudWatch"
    effect = "Allow"
    actions = [
      "cloudwatch:GetMetricData",
      "cloudwatch:GetMetricStatistics",
      "cloudwatch:ListTagsForResource",
      "cloudwatch:DescribeAlarms",
    ]
    resources = ["*"]
  }

  # Infrastructure agent health checks on the services alarms point at.
  statement {
    sid    = "ReadLambdaConfig"
    effect = "Allow"
    actions = [
      "lambda:GetFunctionConfiguration",
    ]
    resources = ["arn:aws:lambda:${var.aws_region}:${data.aws_caller_identity.current.account_id}:function:*"]
  }

  # Incident persistence.
  statement {
    sid    = "IncidentStore"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:Scan",
    ]
    resources = [aws_dynamodb_table.incidents.arn]
  }

  # Report archive.
  statement {
    sid       = "ReportBucket"
    effect    = "Allow"
    actions   = ["s3:PutObject", "s3:GetObject"]
    resources = ["${aws_s3_bucket.reports.arn}/*"]
  }

  # Outbound notifications, and confirming our own ingest subscription.
  statement {
    sid       = "Notify"
    effect    = "Allow"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.notifications.arn]
  }

  statement {
    sid       = "ConfirmIngestSubscription"
    effect    = "Allow"
    actions   = ["sns:ConfirmSubscription"]
    resources = [aws_sns_topic.alarms.arn]
  }

  # The handoff from the API function to the worker.
  statement {
    sid       = "EnqueueIncidents"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.incidents.arn]
  }

  # The worker's side of it. Lambda's SQS event source polls using the
  # function's own role, so these are required for the trigger to work at all -
  # without them the mapping silently never delivers.
  statement {
    sid    = "ConsumeIncidents"
    effect = "Allow"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:GetQueueAttributes",
    ]
    resources = [aws_sqs_queue.incidents.arn]
  }

  statement {
    sid    = "WriteLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${var.name_prefix}-*:*"]
  }
}

resource "aws_iam_role_policy" "task" {
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.task.json
}

# --------------------------------------------------------------------------- #
# Remediation permissions.
#
# Separated into their own policy so they can be reviewed, restricted, or
# detached independently of everything above. Attach only the actions you
# actually want the Remediation Agent to be able to execute; the approval gate
# is a control, not a guarantee, and this policy is what bounds it.
# --------------------------------------------------------------------------- #
data "aws_iam_policy_document" "remediation" {
  statement {
    sid    = "SafeRemediations"
    effect = "Allow"
    actions = [
      "lambda:UpdateFunctionConfiguration",
      "lambda:GetFunctionConfiguration",
      "ecs:UpdateService",
      "ecs:DescribeServices",
    ]
    resources = var.remediation_target_arns
  }

  # autoscaling:UpdateAutoScalingGroup backs the "scale_asg" action, which the
  # Approval Agent classifies risky and never auto-approves.
  statement {
    sid       = "RiskyRemediations"
    effect    = "Allow"
    actions   = ["autoscaling:UpdateAutoScalingGroup"]
    resources = var.autoscaling_group_arns
  }
}

resource "aws_iam_role_policy" "remediation" {
  count  = var.enable_remediation ? 1 : 0
  name   = "${var.name_prefix}-remediation"
  role   = aws_iam_role.task.id
  policy = data.aws_iam_policy_document.remediation.json
}
