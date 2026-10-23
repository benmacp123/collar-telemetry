# Live mode's clock: EventBridge Scheduler invokes the clock handler on a
# fixed rate, and it sends every deployment of the live run a tick through
# the slices queue (src/cloud/clock.py), so a silent collar still raises
# its gap alert. Deployed disabled: replays carry their own clock in each
# slice, and a tick mid-replay would be one message the replay never had.

resource "aws_cloudwatch_log_group" "clock" {
  name              = "/aws/lambda/${var.name_prefix}-clock"
  retention_in_days = 7
}

resource "aws_lambda_function" "clock" {
  function_name    = "${var.name_prefix}-clock"
  role             = aws_iam_role.clock.arn
  s3_bucket        = aws_s3_object.lambda.bucket
  s3_key           = aws_s3_object.lambda.key
  source_code_hash = local.package_hash
  handler          = "cloud.clock.handler"
  runtime          = local.runtime
  architectures    = [local.architecture]
  memory_size      = 256
  timeout          = 60

  environment {
    variables = merge(local.tables, {
      QUEUE_URL = aws_sqs_queue.slices.url
    })
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.clock.name
  }
}

# Clock: list the run's deployments, send their ticks.
data "aws_iam_policy_document" "clock" {
  statement {
    sid       = "State"
    actions   = ["dynamodb:Scan"]
    resources = [aws_dynamodb_table.state.arn]
  }

  statement {
    sid       = "Queue"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.slices.arn]
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.clock.arn}:*"]
  }
}

resource "aws_iam_role" "clock" {
  name               = "${var.name_prefix}-clock"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "clock" {
  name   = "${var.name_prefix}-clock"
  role   = aws_iam_role.clock.id
  policy = data.aws_iam_policy_document.clock.json
}

# The scheduler's own role: it may only invoke the clock handler.
data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    sid       = "Invoke"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.clock.arn]
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name_prefix}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "${var.name_prefix}-scheduler"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

# Schedules take no tags, so cloud-leftovers looks this one up by name.
resource "aws_scheduler_schedule" "clock" {
  name                = "${var.name_prefix}-clock"
  schedule_expression = var.clock_rate
  state               = var.clock_enabled ? "ENABLED" : "DISABLED"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_lambda_function.clock.arn
    role_arn = aws_iam_role.scheduler.arn
    # The scheduled time, not the invocation time, so a retry sends the
    # same ticks.
    input = jsonencode({
      run_id = var.live_run_id
      until  = "<aws.scheduler.scheduled-time>"
    })

    # A tick an hour late is overtaken by the next one.
    retry_policy {
      maximum_event_age_in_seconds = 3600
      maximum_retry_attempts       = 3
    }
  }
}
