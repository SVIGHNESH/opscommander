output "ingest_topic_arn" {
  value       = aws_sns_topic.alarms.arn
  description = "Set as OPSCOMMANDER_SNS_ALLOWED_TOPICS on the service."
}

output "notification_topic_arn" {
  value       = aws_sns_topic.notifications.arn
  description = "Set as OPSCOMMANDER_SNS_TOPIC_ARN. Must differ from the ingest topic."
}

output "ingest_dlq_url" {
  value       = aws_sqs_queue.ingest_dlq.id
  description = "Deliveries that exhausted retries. Check here when an alarm produced no incident."
}

output "incidents_table" {
  value = aws_dynamodb_table.incidents.name
}

output "reports_bucket" {
  value = aws_s3_bucket.reports.bucket
}

output "app_secret_arn" {
  value       = aws_secretsmanager_secret.app.arn
  description = "Holds OPSCOMMANDER_INGEST_ID_SECRET and OPSCOMMANDER_APPROVAL_TOKEN."
}

output "webhook_url" {
  value       = "${trimsuffix(aws_apigatewayv2_stage.api.invoke_url, "/")}/webhook/sns"
  description = "The only publicly routed path. SNS is subscribed to it already."
}

output "incident_queue_url" {
  value       = aws_sqs_queue.incidents.id
  description = "Set as OPSCOMMANDER_INGEST_QUEUE_URL. Depth here is the pipeline backlog."
}

output "incident_dlq_url" {
  value       = aws_sqs_queue.incidents_dlq.id
  description = "Incidents whose pipeline failed every retry. Should stay empty."
}

output "worker_log_group" {
  value       = aws_cloudwatch_log_group.worker.name
  description = "Where a pipeline run's agent-by-agent trace ends up."
}
