# The publisher's slices. FIFO with one message group per run and
# deployment, so each collar has one batch in flight and its messages
# apply in order. Deduplication IDs come from the publisher
# (run#deployment#seq), not from the content.
resource "aws_sqs_queue" "slices" {
  name                        = "${var.name_prefix}-slices.fifo"
  fifo_queue                  = true
  content_based_deduplication = false

  # AWS's guidance: at least six times the function timeout, so a slow
  # batch is not handed to a second instance while the first still runs.
  visibility_timeout_seconds = 6 * local.processor_timeout
  message_retention_seconds  = 4 * 24 * 3600

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.slices_dlq.arn
    maxReceiveCount     = 5
  })
}

# A FIFO queue's dead-letter queue must be FIFO too. Once a message lands
# here its collar stops: every later message fails the processor's
# sequence check and follows it, rather than being applied past a gap.
resource "aws_sqs_queue" "slices_dlq" {
  name                      = "${var.name_prefix}-slices-dlq.fifo"
  fifo_queue                = true
  message_retention_seconds = 14 * 24 * 3600
}

# Stream batches the notifier gave up on. The stream record itself expires
# after 24 hours, so this keeps a pointer to what was not sent.
resource "aws_sqs_queue" "notify_failures" {
  name                      = "${var.name_prefix}-notify-failures"
  message_retention_seconds = 14 * 24 * 3600
}
