# On-demand tables: no idle cost, and the largest state item measured is
# 62 KB, well under the 400 KB item limit (results/cloud/sizing.json).

# One item per run and deployment: the detectors' state, the clock cursor
# and the last message sequence applied.
resource "aws_dynamodb_table" "state" {
  name         = "${var.name_prefix}-state"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "key"

  attribute {
    name = "key"
    type = "S"
  }
}

# Incidents, keyed by run. The stream is the notifier's outbox; both images
# so the notifier can tell its own notified_at write from a new incident.
resource "aws_dynamodb_table" "incidents" {
  name         = "${var.name_prefix}-incidents"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "run_id"
  range_key    = "incident_id"

  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "run_id"
    type = "S"
  }

  attribute {
    name = "incident_id"
    type = "S"
  }
}
