# What the publisher and the comparison script need after `apply`. The
# URLs and ARNs include the account ID: read them from `terraform output`,
# never commit them.

output "queue_url" {
  description = "Slices queue, for the publisher."
  value       = aws_sqs_queue.slices.url
}

output "state_table" {
  description = "State table name."
  value       = aws_dynamodb_table.state.name
}

output "incidents_table" {
  description = "Incidents table name, for comparing against the replay."
  value       = aws_dynamodb_table.incidents.name
}

output "topic_arn" {
  description = "Alerts topic."
  value       = aws_sns_topic.alerts.arn
}

output "dead_letter_queue_url" {
  description = "Slices that failed five times."
  value       = aws_sqs_queue.slices_dlq.url
}

output "notify_failures_url" {
  description = "Stream batches the notifier gave up on."
  value       = aws_sqs_queue.notify_failures.url
}
