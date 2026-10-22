# Both handlers ship in one zip (`make lambda-zip`); the handler setting
# picks the entry point. Runtime and architecture must match the wheels
# scripts/lambda_zip.py installs.
locals {
  runtime           = "python3.14"
  architecture      = "x86_64"
  processor_timeout = 60
  notifier_timeout  = 30
  package_hash      = filebase64sha256(var.lambda_zip)

  tables = {
    STATE_TABLE     = aws_dynamodb_table.state.name
    INCIDENTS_TABLE = aws_dynamodb_table.incidents.name
  }
}

# Managed here rather than left to Lambda, so they have a retention
# period and `destroy` removes them.
resource "aws_cloudwatch_log_group" "processor" {
  name              = "/aws/lambda/${var.name_prefix}-processor"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "notifier" {
  name              = "/aws/lambda/${var.name_prefix}-notifier"
  retention_in_days = 7
}

resource "aws_lambda_function" "processor" {
  function_name    = "${var.name_prefix}-processor"
  role             = aws_iam_role.processor.arn
  filename         = var.lambda_zip
  source_code_hash = local.package_hash
  handler          = "cloud.processor.handler"
  runtime          = local.runtime
  architectures    = [local.architecture]
  memory_size      = 512
  timeout          = local.processor_timeout

  environment {
    variables = merge(local.tables, {
      BOUNDARIES_DIR = "/var/task/boundaries"
    })
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.processor.name
  }
}

resource "aws_lambda_function" "notifier" {
  function_name    = "${var.name_prefix}-notifier"
  role             = aws_iam_role.notifier.arn
  filename         = var.lambda_zip
  source_code_hash = local.package_hash
  handler          = "cloud.notifier.handler"
  runtime          = local.runtime
  architectures    = [local.architecture]
  memory_size      = 256
  timeout          = local.notifier_timeout

  environment {
    variables = merge(local.tables, {
      TOPIC_ARN      = aws_sns_topic.alerts.arn
      NOTIFY_ENABLED = tostring(var.notify_enabled)
    })
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.notifier.name
  }
}

# The processor reports the first failed record and everything after it
# (batchItemFailures), so the rest of the batch is not redone and order
# holds within each collar's message group.
resource "aws_lambda_event_source_mapping" "slices" {
  event_source_arn        = aws_sqs_queue.slices.arn
  function_name           = aws_lambda_function.processor.arn
  batch_size              = 10
  function_response_types = ["ReportBatchItemFailures"]

  scaling_config {
    maximum_concurrency = var.processor_concurrency
  }
}

# Only potential_death incidents reach the notifier; the rest of the stream
# (every other detector, and bulk replays) never invokes it. The notifier
# also skips its own notified_at writes, which match this filter.
resource "aws_lambda_event_source_mapping" "incidents" {
  event_source_arn        = aws_dynamodb_table.incidents.stream_arn
  function_name           = aws_lambda_function.notifier.arn
  starting_position       = "TRIM_HORIZON"
  batch_size              = 100
  function_response_types = ["ReportBatchItemFailures"]
  maximum_retry_attempts  = 10

  filter_criteria {
    filter {
      pattern = jsonencode({
        dynamodb = { NewImage = { detector = { S = ["potential_death"] } } }
      })
    }
  }

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.notify_failures.arn
    }
  }
}
