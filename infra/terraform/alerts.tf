# Alert email. The subscription stays pending until the address confirms
# it from the email AWS sends after `apply`.
resource "aws_sns_topic" "alerts" {
  name = "${var.name_prefix}-alerts"
}

# The notifier only publishes likely_death, but the filter keeps the email
# to that detector even if it later publishes more.
resource "aws_sns_topic_subscription" "email" {
  topic_arn     = aws_sns_topic.alerts.arn
  protocol      = "email"
  endpoint      = var.alert_email
  filter_policy = jsonencode({ detector = ["likely_death"] })
}

# Account-wide rather than filtered by tag, so it also catches anything
# `destroy` failed to remove. Budgets themselves are free.
resource "aws_budgets_budget" "monthly" {
  name         = "${var.name_prefix}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}
