# One role per handler, each allowed only the calls its code makes
# (src/cloud/store.py, processor.py, notifier.py).

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# Processor: read state, then one TransactWriteItems that puts state and
# updates incidents (a transaction needs each item action's permission).
data "aws_iam_policy_document" "processor" {
  statement {
    sid       = "State"
    actions   = ["dynamodb:GetItem", "dynamodb:PutItem"]
    resources = [aws_dynamodb_table.state.arn]
  }

  statement {
    sid       = "Incidents"
    actions   = ["dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.incidents.arn]
  }

  statement {
    sid = "Queue"
    actions = [
      "sqs:ReceiveMessage",
      "sqs:DeleteMessage",
      "sqs:ChangeMessageVisibility",
      "sqs:GetQueueAttributes",
    ]
    resources = [aws_sqs_queue.slices.arn]
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.processor.arn}:*"]
  }
}

# Notifier: read the stream, check and mark incidents, publish, and record
# batches it gives up on.
data "aws_iam_policy_document" "notifier" {
  statement {
    sid = "Stream"
    actions = [
      "dynamodb:DescribeStream",
      "dynamodb:GetRecords",
      "dynamodb:GetShardIterator",
      "dynamodb:ListStreams",
    ]
    resources = [aws_dynamodb_table.incidents.stream_arn]
  }

  statement {
    sid       = "Incidents"
    actions   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
    resources = [aws_dynamodb_table.incidents.arn]
  }

  statement {
    sid       = "Publish"
    actions   = ["sns:Publish"]
    resources = [aws_sns_topic.alerts.arn]
  }

  statement {
    sid       = "Failures"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.notify_failures.arn]
  }

  statement {
    sid       = "Logs"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.notifier.arn}:*"]
  }
}

resource "aws_iam_role" "processor" {
  name               = "${var.name_prefix}-processor"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "processor" {
  name   = "${var.name_prefix}-processor"
  role   = aws_iam_role.processor.id
  policy = data.aws_iam_policy_document.processor.json
}

resource "aws_iam_role" "notifier" {
  name               = "${var.name_prefix}-notifier"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy" "notifier" {
  name   = "${var.name_prefix}-notifier"
  role   = aws_iam_role.notifier.id
  policy = data.aws_iam_policy_document.notifier.json
}
